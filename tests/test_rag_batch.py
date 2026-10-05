"""Batch ask, focus presets, RQ extract, and answered packs."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.config import load_config
from paperful.rag.answered import keys_after_item, parse_verdict
from paperful.rag.prompt import FOCI, parse_focus, resolve_system_prompt
from paperful.rag.questions import extract_rules
from tests.ragfakes import BODY, FakeEmbedder, StubChat, TextFileParser, add_item
from tests.test_rag_cli import _ingest, _run, _write_config
from tests.textutil import plain_text

pytest.importorskip("lancedb")

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(cli, "console", Console(highlight=False, width=250, height=100))


@pytest.fixture(autouse=True)
def no_reference_manager(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("rag verbs must not open the reference manager")

    monkeypatch.setattr(cli, "ZoteroLocal", boom)
    monkeypatch.setattr(cli, "get_backend", boom)


@pytest.fixture
def fakes(monkeypatch):
    embedder, chat = FakeEmbedder(), StubChat()
    monkeypatch.setattr("paperful.llm.validate_embedder", lambda cfg: embedder)
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_ask", lambda cfg: "stub")
    monkeypatch.setattr("paperful.llm.get_client", lambda cfg: chat)
    monkeypatch.setattr("paperful.rag.ingest.get_parser", lambda cfg: TextFileParser())
    monkeypatch.setattr("paperful.rag.ingest.ocrmypdf_available", lambda: False)
    monkeypatch.setenv("PAPERFUL_PACK", "off")
    return {"embedder": embedder, "chat": chat}


@pytest.fixture
def mirror(tmp_path, fakes):
    config = _write_config(tmp_path)
    cfg = load_config(config)
    cfg.out_dir.mkdir(parents=True)
    add_item(cfg, "AAAA1111", pdf=BODY)
    add_item(
        cfg,
        "BBBB2222",
        collection="law",
        title="Seabed mining",
        author="Silva",
        year=2021,
        abstract="Royalties for seabed mining. We ask whether royalties are fair?",
        pdf=(
            "Research questions\n"
            "1. Are royalties for seabed mining fair?\n"
            "Methods\n"
            "We surveyed states.\n"
        ),
    )
    return {"config": config, "cfg": cfg, **fakes}


def test_focus_presets_resolve():
    assert set(FOCI) >= {"default", "questions", "gaps", "methods", "answered"}
    assert parse_focus("") == "default"
    system, name, label = resolve_system_prompt(focus="gaps")
    assert name == "gaps" == label and "gaps" in system.lower()


def test_ask_focus_changes_system_prompt(mirror):
    _ingest(mirror)
    res = _run(["ask", "What gaps remain?", "--focus", "gaps", "--no-stream"], mirror["config"])
    assert res.exit_code == 0, plain_text(res.stdout)
    system = mirror["chat"].requests[0].messages[0]["content"]
    assert "gaps" in system.lower()


def test_ask_batch_from_file_writes_pack_and_resumes(mirror, tmp_path):
    _ingest(mirror)
    qfile = tmp_path / "qs.txt"
    qfile.write_text("# comment\nWhat do krill eat?\nWhat about seabed?\n")
    res = _run(
        ["ask", "--from-file", str(qfile), "--no-stream", "--format", "json"],
        mirror["config"],
    )
    assert res.exit_code == 0, plain_text(res.stdout)
    payload = json.loads(res.stdout)
    assert payload["summary"]["answered"] == 2
    pack_dir = mirror["cfg"].state_dir / "ask-batch"
    stamps = [p for p in pack_dir.iterdir() if p.is_dir() and p.name != "by-hash"]
    assert stamps
    pack = json.loads((stamps[0] / "pack.json").read_text())
    assert pack["schema"] == "paperful.ask_batch.v1"
    assert pack["answered"] == 2
    first_calls = len(mirror["chat"].requests)
    res2 = _run(
        ["ask", "--from-file", str(qfile), "--no-stream", "--format", "json"],
        mirror["config"],
    )
    assert res2.exit_code == 0
    assert json.loads(res2.stdout)["summary"]["skipped"] == 2
    assert len(mirror["chat"].requests) == first_calls


def test_extract_rules_finds_numbered_rq():
    pages = [
        "Research questions\n1. Are royalties for seabed mining fair?\nMethods\nSurvey.\n"
    ]
    found = extract_rules(pages, abstract="We ask whether royalties are fair?")
    texts = " ".join(q.text for q in found)
    assert "royalties" in texts.lower()
    assert all(q.provenance == "rule" for q in found)


def test_rag_questions_and_answered(mirror, tmp_path):
    _ingest(mirror)
    res = _run(["rag", "questions", "--item", "BBBB2222"], mirror["config"])
    assert res.exit_code == 0, plain_text(res.stdout)
    qpath = mirror["cfg"].state_dir / "rag" / "questions" / "BBBB2222.json"
    assert qpath.is_file()
    data = json.loads(qpath.read_text())
    assert data["schema"] == "paperful.rag.questions.v1"
    assert data["questions"]

    mirror["chat"].pieces = ["ANSWERED\nLater work settles royalties [S1]."]
    res = _run(
        ["rag", "answered", "--from-extract", "--item", "BBBB2222", "--format", "json"],
        mirror["config"],
    )
    assert res.exit_code == 0, plain_text(res.stdout)
    payload = json.loads(res.stdout)
    assert payload["summary"]["questions"] >= 1
    folder = mirror["cfg"].state_dir / "rq-answered"
    stamps = list(folder.iterdir())
    assert stamps
    pack = json.loads((stamps[0] / "pack.json").read_text())
    assert pack["schema"] == "paperful.rq_answered.v1"
    assert pack["rows"][0]["verdict"] in {"answered", "partial", "not_found"}


def test_keys_after_item_and_verdict(mirror):
    _ingest(mirror)
    from paperful.rag.index import ledger_path
    from paperful.rag.ledger import Ledger

    ledger = Ledger(ledger_path(mirror["cfg"]))
    keys = keys_after_item(ledger, "AAAA1111")
    assert "AAAA1111" not in keys
    assert "BBBB2222" in keys
    assert parse_verdict("PARTIAL\nSome evidence [S1].") == "partial"


def test_prompt_file_wins_over_focus(mirror, tmp_path):
    _ingest(mirror)
    prompt = tmp_path / "custom.txt"
    prompt.write_text("You are a custom asker. Cite with [S#] only.")
    res = _run(
        [
            "ask",
            "What do krill eat?",
            "--focus",
            "gaps",
            "--prompt",
            str(prompt),
            "--no-stream",
        ],
        mirror["config"],
    )
    assert res.exit_code == 0, plain_text(res.stdout)
    system = mirror["chat"].requests[0].messages[0]["content"]
    assert "custom asker" in system
    assert "gaps" not in system.lower() or "custom" in system.lower()


def test_batch_force_reanswers(mirror, tmp_path):
    _ingest(mirror)
    qfile = tmp_path / "one.txt"
    qfile.write_text("What do krill eat?\n")
    _run(["ask", "--from-file", str(qfile), "--format", "json"], mirror["config"])
    n = len(mirror["chat"].requests)
    _run(["ask", "--from-file", str(qfile), "--format", "json"], mirror["config"])
    assert len(mirror["chat"].requests) == n
    _run(
        ["ask", "--from-file", str(qfile), "--force", "--format", "json"],
        mirror["config"],
    )
    assert len(mirror["chat"].requests) == n + 1


def test_batch_apply_conflicts_with_disk(mirror, tmp_path):
    _ingest(mirror)
    qfile = tmp_path / "one.txt"
    qfile.write_text("What do krill eat?\n")
    res = _run(
        [
            "ask",
            "--from-file",
            str(qfile),
            "--apply",
            "--to",
            "disk",
            "-C",
            "ocean",
        ],
        mirror["config"],
    )
    assert res.exit_code == 1
    assert "conflicts with --to disk" in plain_text(res.stdout)


def test_profile_focus_applies_to_ask(mirror, tmp_path):
    _ingest(mirror)
    profiles = mirror["cfg"].config_path.parent / "profiles"
    profiles.mkdir(exist_ok=True)
    (profiles / "gaps.toml").write_text(
        'description = "gaps ask"\ncollections = ["law"]\nfocus = "gaps"\n'
    )
    res = _run(
        ["ask", "What gaps remain?", "--profile", "gaps", "--no-stream"],
        mirror["config"],
    )
    assert res.exit_code == 0, plain_text(res.stdout)
    system = mirror["chat"].requests[0].messages[0]["content"]
    assert "gaps" in system.lower()
    # Scope from profile: only law (BBBB2222 abstract), not ocean PDF alone.
    user = mirror["chat"].requests[0].messages[-1]["content"]
    assert "Seabed" in user or "Silva" in user or "BBBB2222" in user or "royalties" in user.lower()
