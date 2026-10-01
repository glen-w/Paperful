"""`paperful rag …` and `paperful ask` through CliRunner. No Ollama, no Zotero."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.config import load_config
from paperful.rag.index import ledger_path
from paperful.rag.ledger import Ledger
from paperful.store import STATUS_OK, Manifest, Record
from tests.ragfakes import BODY, FakeEmbedder, StubChat, TextFileParser, add_item
from tests.textutil import plain_text

pytest.importorskip("lancedb")

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(cli, "console", Console(highlight=False, width=250, height=100))


@pytest.fixture(autouse=True)
def no_reference_manager(monkeypatch):
    """Every rag verb must work with the reference manager unreachable."""

    def boom(*args, **kwargs):
        raise AssertionError("rag verbs must not open the reference manager")

    monkeypatch.setattr(cli, "ZoteroLocal", boom)
    monkeypatch.setattr(cli, "get_backend", boom)


def _write_config(tmp_path, *, rag="enabled = true", llm="enabled = true"):
    path = tmp_path / "config.toml"
    path.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n\n[llm]\n{llm}\n\n[rag]\n{rag}\nhybrid = false\n'
    )
    return path


@pytest.fixture
def fakes(monkeypatch):
    """Swap the embedder, parser and chat client for offline stand-ins."""
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
    """A config with RAG on and a two-item mirror, not yet indexed."""
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
        abstract="Royalties for seabed mining.",
    )
    return {"config": config, "cfg": cfg, **fakes}


def _run(args, config, **kw):
    return runner.invoke(cli.app, [*args, "--config", str(config)], **kw)


def _ingest(mirror, *extra):
    res = _run(["rag", "ingest", "--library", *extra], mirror["config"])
    assert res.exit_code == 0, res.stdout
    return res


# ---- gates -------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [["rag", "ingest", "--library"], ["rag", "search", "krill"], ["ask", "krill?"]],
)
def test_verbs_refuse_when_rag_is_off(tmp_path, fakes, args):
    config = _write_config(tmp_path, rag="enabled = false")
    res = _run(args, config)
    assert res.exit_code == 1
    assert "rag.enabled is false" in plain_text(res.stdout)


def test_ingest_needs_a_scope(mirror):
    res = _run(["rag", "ingest"], mirror["config"])
    assert res.exit_code == 1 and "--collection / --library" in plain_text(res.stdout)


def test_search_and_ask_before_ingest_point_at_ingest(mirror):
    for args in (["rag", "search", "krill"], ["ask", "krill?"]):
        res = _run(args, mirror["config"])
        assert res.exit_code == 1
        assert "paperful rag ingest" in plain_text(res.stdout)


def test_ask_needs_the_llm_switch(tmp_path, monkeypatch):
    config = _write_config(tmp_path, llm="enabled = false")
    monkeypatch.setattr("paperful.llm.validate_embedder", lambda cfg: FakeEmbedder())
    res = _run(["ask", "krill?"], config)
    assert res.exit_code == 1 and "llm.enabled is false" in plain_text(res.stdout)


def test_embedder_problem_is_reported_before_any_work(mirror, monkeypatch):
    from paperful.llm.validate import LlmConfigError

    def broken(cfg):
        raise LlmConfigError("Try: ollama pull nomic-embed-text")

    monkeypatch.setattr("paperful.llm.validate_embedder", broken)
    res = _run(["rag", "ingest", "--library"], mirror["config"])
    assert res.exit_code == 1 and "ollama pull" in plain_text(res.stdout)
    assert not mirror["cfg"].rag_dir.exists()


# ---- ingest ------------------------------------------------------------------


def test_dry_run_builds_nothing_and_skips_the_embedder_check(mirror, monkeypatch):
    def unreachable(cfg):
        raise AssertionError("a dry run must not need the embedding model")

    monkeypatch.setattr("paperful.llm.validate_embedder", unreachable)
    res = _run(["rag", "ingest", "--library", "--dry-run"], mirror["config"])
    out = plain_text(res.stdout)
    assert res.exit_code == 0, out
    assert "Would index 1 PDFs (0 after OCR) and 1 abstracts" in out
    assert not mirror["cfg"].rag_dir.exists()


def test_ingest_then_rerun(mirror):
    out = plain_text(_ingest(mirror).stdout)
    assert "Indexed 1 PDFs (0 after OCR) and 1 abstracts" in out
    assert "AAAA1111" in out and "BBBB2222" in out
    ledger = Ledger(ledger_path(mirror["cfg"]))
    assert ledger.keys() == {"AAAA1111", "BBBB2222"}
    report = sorted((mirror["cfg"].state_dir / "runs").glob("*-rag-ingest.json"))[-1]
    data = json.loads(report.read_text())
    assert data["command"] == "rag-ingest" and data["summary"]["pdf"] == 1
    again = plain_text(_ingest(mirror).stdout)
    assert "Indexed 0 PDFs" in again and "Unchanged 2" in again


def test_ingest_scope_limit_and_collection(mirror):
    res = _run(["rag", "ingest", "-C", "law"], mirror["config"])
    assert res.exit_code == 0
    assert Ledger(ledger_path(mirror["cfg"])).keys() == {"BBBB2222"}
    res = _run(["rag", "ingest", "--library", "--limit", "0"], mirror["config"])
    assert Ledger(ledger_path(mirror["cfg"])).keys() == {"BBBB2222"}
    res = _run(["rag", "ingest", "--item", "AAAA1111"], mirror["config"])
    assert res.exit_code == 0
    assert Ledger(ledger_path(mirror["cfg"])).keys() == {"AAAA1111", "BBBB2222"}


def test_library_ingest_prunes_but_scoped_ingest_does_not(mirror):
    import shutil

    _ingest(mirror)
    shutil.rmtree(mirror["cfg"].out_dir / "law")
    _run(["rag", "ingest", "-C", "ocean"], mirror["config"])
    assert "BBBB2222" in Ledger(ledger_path(mirror["cfg"])).keys()
    _run(["rag", "ingest", "--library", "--year-from", "1900"], mirror["config"])
    assert "BBBB2222" in Ledger(ledger_path(mirror["cfg"])).keys()
    _ingest(mirror)
    assert Ledger(ledger_path(mirror["cfg"])).keys() == {"AAAA1111"}


def test_embedding_outage_stops_with_a_resume_hint(mirror):
    from paperful.llm.embed import EmbedError

    def down(texts):
        raise EmbedError("Ollama unreachable: connection refused")

    mirror["embedder"].embed_documents = down
    res = _run(["rag", "ingest", "--library"], mirror["config"])
    out = plain_text(res.stdout)
    assert res.exit_code == 1
    assert "Ollama unreachable" in out and "Run again to continue" in out


# ---- status ------------------------------------------------------------------


def test_status_before_and_after_ingest(mirror):
    res = _run(["rag", "status", "--json"], mirror["config"])
    before = json.loads(res.stdout)
    assert before["exists"] is False and before["items"] == 0
    assert before["mirror"] == {
        "items": 2,
        "with_pdf": 1,
        "pdf_not_in_mirror": 0,
        "stale": 2,
    }
    _ingest(mirror)
    after = json.loads(_run(["rag", "status", "--json"], mirror["config"]).stdout)
    assert after["exists"] and after["items_pdf"] == 1 and after["items_abstract"] == 1
    assert after["index_rows"] == after["chunks"] and after["mirror"]["stale"] == 0
    table = plain_text(_run(["rag", "status"], mirror["config"]).stdout)
    assert "ollama / nomic-embed-text" in table and "from abstract only" in table


def test_status_works_with_rag_off_and_counts_manager_only_pdfs(tmp_path, fakes):
    from paperful.store import write_json

    config = _write_config(tmp_path, rag="enabled = false")
    cfg = load_config(config)
    cfg.out_dir.mkdir(parents=True)
    folder = add_item(cfg, "CCCC3333")
    record = json.loads((folder / "record.json").read_text())
    record["attachments"] = [
        {"key": "X", "filename": "a.pdf", "linkMode": "imported_file",
         "contentType": "application/pdf"},
    ]
    write_json(folder / "record.json", record)
    linked = add_item(cfg, "DDDD4444", title="Linked only")
    record = json.loads((linked / "record.json").read_text())
    record["attachments"] = [
        {"key": "Y", "filename": "b", "linkMode": "linked_url",
         "contentType": "application/pdf"},
    ]
    write_json(linked / "record.json", record)
    res = _run(["rag", "status"], config)
    out = plain_text(res.stdout)
    assert res.exit_code == 0 and "rag.enabled is false" in out
    assert "1 items have a PDF in the reference manager" in out
    assert "snapshot --pdfs all" in out


# ---- search ------------------------------------------------------------------


def test_search_prints_passages_with_their_paper(mirror):
    _ingest(mirror)
    res = _run(["rag", "search", "krill under ice", "-k", "5"], mirror["config"])
    out = plain_text(res.stdout)
    assert res.exit_code == 0, out
    assert "Chen (2019). Krill in winter, p. 1 [AAAA1111]" in out
    assert "Silva (2021). Seabed mining, abstract [BBBB2222]" in out
    assert mirror["chat"].requests == []


def test_search_json_and_scope(mirror):
    _ingest(mirror)
    res = _run(["rag", "search", "krill", "-C", "law", "--json"], mirror["config"])
    hits = json.loads(res.stdout)
    assert [h["item_key"] for h in hits] == ["BBBB2222"]
    assert hits[0]["source"] == "abstract" and hits[0]["authors"] == ["Silva"]
    res = _run(["rag", "search", "krill", "--year-from", "2030"], mirror["config"])
    assert "No passages match" in plain_text(res.stdout)


# ---- ask ---------------------------------------------------------------------


def test_ask_streams_an_answer_and_lists_cited_sources(mirror):
    _ingest(mirror)
    res = _run(["ask", "What do krill eat?"], mirror["config"])
    out = plain_text(res.stdout)
    assert res.exit_code == 0, out
    # The [S1] marker must survive Rich, which would otherwise read it as markup.
    assert "Krill eat algae [S1]." in out
    assert "Sources" in out and "Retrieved, not cited" not in out
    assert out.count("[S1] ") == 1  # one source line; S2 was offered but not cited
    request = mirror["chat"].requests[0]
    assert request.messages[-1]["content"].endswith("Question: What do krill eat?")
    report = sorted((mirror["cfg"].state_dir / "runs").glob("*-ask.json"))[-1]
    item = json.loads(report.read_text())["items"][0]
    assert item["question"] == "What do krill eat?" and item["cited"] == ["S1"]
    assert item["answer"] == "Krill eat algae [S1]."


def test_ask_no_stream_and_show_context(mirror):
    _ingest(mirror)
    res = _run(["ask", "krill?", "--no-stream", "--show-context", "-k", "2"], mirror["config"])
    out = plain_text(res.stdout)
    assert res.exit_code == 0, out
    assert out.index("Passages") < out.index("Krill eat algae [S1].") < out.index("Sources")


def test_ask_lists_retrieved_sources_when_none_were_cited(mirror):
    _ingest(mirror)
    mirror["chat"].pieces = ["The excerpts do not say."]
    out = plain_text(_run(["ask", "tax law?"], mirror["config"]).stdout)
    assert "Retrieved, not cited" in out and "[S1] " in out


def test_ask_scope_with_no_indexed_items_skips_the_model(mirror):
    _ingest(mirror)
    res = _run(["ask", "krill?", "-C", "nowhere"], mirror["config"])
    assert "Nothing in the index matches" in plain_text(res.stdout)
    assert mirror["chat"].requests == []


def test_ask_model_error_exits_1(mirror):
    _ingest(mirror)
    mirror["chat"].error = "Ollama timed out after 120s"
    res = _run(["ask", "krill?"], mirror["config"])
    assert res.exit_code == 1 and "timed out" in plain_text(res.stdout)


def test_ask_without_a_question_reads_one_per_line(mirror):
    _ingest(mirror)
    res = _run(["ask"], mirror["config"], input="What do krill eat?\n\nAnd whales?\n:q\nignored\n")
    out = plain_text(res.stdout)
    assert res.exit_code == 0, out
    assert [r.messages[-1]["content"].rsplit("Question: ", 1)[1] for r in mirror["chat"].requests] == [
        "What do krill eat?",
        "And whales?",
    ]
    # Questions are independent for now: no earlier turn is sent along.
    assert all(len(r.messages) == 2 for r in mirror["chat"].requests)
    report = sorted((mirror["cfg"].state_dir / "runs").glob("*-ask.json"))[-1]
    assert json.loads(report.read_text())["summary"] == {
        "questions": 2,
        "answered": 2,
        "write_api": None,
    }


def test_ask_loop_keeps_going_after_a_failed_question(mirror):
    _ingest(mirror)
    chat = mirror["chat"]
    real = chat.chat_stream
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            from paperful.llm.client import LLMClientError

            raise LLMClientError("model crashed")
        return real(request)

    chat.chat_stream = flaky
    res = _run(["ask"], mirror["config"], input="first?\nsecond?\n")
    out = plain_text(res.stdout)
    assert res.exit_code == 0 and "model crashed" in out and "Krill eat algae [S1]." in out


# ---- auto-ingest -------------------------------------------------------------


def test_rag_auto_is_silent_when_the_switch_is_off(mirror, monkeypatch):
    def unreachable(*a, **k):
        raise AssertionError("auto-ingest is off by default")

    monkeypatch.setattr("paperful.rag.auto.ingest_entries", unreachable)
    assert mirror["cfg"].rag_auto_ingest is False
    cli._rag_auto(mirror["cfg"], 0.0, keys=["AAAA1111"])
    assert not mirror["cfg"].rag_dir.exists()


def test_rag_auto_indexes_named_and_manifest_logged_items(mirror, monkeypatch):
    cfg = mirror["cfg"]
    cfg.rag_auto_ingest = True
    monkeypatch.setattr("paperful.rag.ingest.get_embedder", lambda cfg: mirror["embedder"])
    manifest = Manifest(cfg.manifest_path)
    manifest.write(Record(itemKey="AAAA1111", status=STATUS_OK, path="ocean/x.pdf"))
    since = manifest.get("AAAA1111").ts - 1
    cli._rag_auto(cfg, since)
    assert Ledger(ledger_path(cfg)).keys() == {"AAAA1111"}
    cli._rag_auto(cfg, since + 10_000, keys=["BBBB2222"])
    assert Ledger(ledger_path(cfg)).keys() == {"AAAA1111", "BBBB2222"}


def test_rag_auto_never_fails_the_parent_command(mirror, monkeypatch, capsys):
    cfg = mirror["cfg"]
    cfg.rag_auto_ingest = True

    def broken(*a, **k):
        raise RuntimeError("Ollama unreachable")

    monkeypatch.setattr("paperful.rag.auto.ingest_entries", broken)
    cli._rag_auto(cfg, 0.0, keys=["AAAA1111"])
    out = plain_text(capsys.readouterr().out)
    assert "Index not updated: Ollama unreachable" in out
    assert "paperful rag ingest" in out
