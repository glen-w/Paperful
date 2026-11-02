"""1.8 crash-resume, review counts, grey miss labels, and log redaction."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from paperful.config import Config
from paperful.fsio import append_jsonl, atomic_write_json
from paperful.http import client
from paperful.log import redact
from paperful.miss_reasons import reason_from_attempts
from paperful.search.watch import due_watches, save_watch
from paperful.sr.exchange import apply_import, export_text, parse_import
from paperful.sr.prisma import counts_hold, prisma_counts, prisma_svg
from paperful.sr.protocol import save_protocol
from paperful.sr.screen import append_screen_decision, load_screen_ledger
from paperful.sr_cmd import review_counts, run_sr_init
from paperful.store import Manifest, Record, load_json


def test_torn_manifest_line_is_skipped(tmp_path: Path):
    path = tmp_path / "manifest.jsonl"
    append_jsonl(path, '{"itemKey": "A", "status": "ok"}')
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"itemKey": "B", "sta')
    manifest = Manifest(path)
    assert manifest.get("A") is not None
    assert manifest.get("B") is None


def test_leftover_part_does_not_replace_sync_state(tmp_path: Path):
    path = tmp_path / "_sync.json"
    atomic_write_json(path, {"schema": "paperful.sync.v1", "version": 3})
    path.with_name("_sync.json.9.part").write_text("{torn", encoding="utf-8")
    assert load_json(path)["version"] == 3


def test_screening_skips_a_torn_last_line(tmp_path: Path):
    state = tmp_path / "state"
    save_protocol(state, "demo", {"title": "T", "question": "Q"})
    append_screen_decision(
        state,
        "demo",
        identity="10.1000/a",
        decision="include",
        reason="",
        reviewer="r",
    )
    from paperful.sr.protocol import review_dir

    ledger = review_dir(state, "demo") / "screening.jsonl"
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write('{"identity": "10.1000/b", "dec')
    rows = load_screen_ledger(state, "demo")
    assert [row["identity"] for row in rows] == ["10.1000/a"]


def test_exclude_reason_must_be_on_the_protocol(tmp_path: Path):
    state = tmp_path / "state"
    save_protocol(
        state,
        "demo",
        {"title": "T", "question": "Q", "exclude_reasons": ["off_topic"]},
    )
    with pytest.raises(ValueError):
        append_screen_decision(
            state,
            "demo",
            identity="10.1000/a",
            decision="exclude",
            reason="nope",
            reviewer="r",
        )
    append_screen_decision(
        state,
        "demo",
        identity="10.1000/a",
        decision="exclude",
        reason="off_topic",
        reviewer="r",
    )
    append_screen_decision(
        state,
        "demo",
        identity="10.1000/b",
        decision="exclude",
        reason="off_topic",
        reviewer="r2",
    )
    from paperful.sr_cmd import exclude_histogram

    assert exclude_histogram(load_screen_ledger(state, "demo"))["off_topic"] == 2
    append_screen_decision(
        state,
        "demo",
        identity="10.1000/c",
        decision="maybe",
        reason="",
        reviewer="r",
    )


def test_prisma_counts_never_go_negative():
    counts = prisma_counts(1, included=2, excluded=1, maybe=0)
    assert counts["pending"] == 0
    assert counts["identified"] == counts["screened"]
    assert counts_hold(counts)
    svg = prisma_svg(counts)
    assert "Included: 2" in svg
    assert "recall" not in svg.lower()


def test_review_links_an_existing_search_pack(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir()
    pack = cfg.state_dir / "search" / "run1"
    pack.mkdir(parents=True)
    (pack / "candidates.jsonl").write_text(
        '{"doi": "10.1000/z", "title": "Zed"}\n', encoding="utf-8"
    )
    assert (
        run_sr_init(cfg, slug="rev", title="Rev", question="Q", search_run="run1") == 0
    )
    counts = review_counts(cfg, "rev")
    assert counts["identified"] == 1
    assert counts["pending"] == 1
    text = export_text(
        [{"doi": "10.1000/z", "title": "Zed", "decision": "include"}],
        fmt="ris",
        decisions={"10.1000/z": {"decision": "include", "reason": ""}},
    )
    parsed = parse_import(text, fmt="ris")
    result = apply_import(cfg.state_dir, "rev", parsed, reviewer="r", apply=False)
    assert result["written"] == 0 and result["planned"] == 1


def test_host_blocked_and_html_labels():
    assert reason_from_attempts(["oa:download-failed(HTTP 403)"]) == "host_blocked"
    assert (
        reason_from_attempts(["oa:download-failed(not a PDF (content-type text/html))"])
        == "html_not_pdf"
    )


def test_httpx_client_construction_stays_central():
    root = Path(__file__).resolve().parents[1] / "paperful"
    allowed = {"paperful/http.py", "paperful/llm/client.py"}
    found = [
        path.relative_to(root.parent).as_posix()
        for path in root.rglob("*.py")
        if "httpx.Client(" in path.read_text(encoding="utf-8")
    ]
    extra = sorted(set(found) - allowed)
    assert extra == []


def test_http_guard_rejects_loopback_and_does_not_retry_403():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403)

    blocked = client(transport=httpx.MockTransport(handler), guard=True, retries=2)
    with pytest.raises(httpx.RequestError):
        blocked.get("http://127.0.0.1/secret")
    assert calls["n"] == 0
    allowed = client(transport=httpx.MockTransport(handler), guard=False, retries=2)
    response = allowed.get("https://example.test/a")
    assert response.status_code == 403
    assert calls["n"] == 1


def test_log_redacts_bearer_tokens():
    raw = "Authorization: Bearer super-secret-token"
    cleaned = redact(raw)
    assert "super-secret-token" not in cleaned
    assert "[redacted]" in cleaned


def test_search_watch_due_lists_a_new_watch(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir()
    save_watch(cfg, "gjerde", terms=["Kristina Gjerde"], interval_days=7)
    names = [row["name"] for row in due_watches(cfg)]
    assert names == ["gjerde"]


def test_bench_budget_flags_a_ten_percent_regression():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "bench_synthetic.py"
    spec = importlib.util.spec_from_file_location("bench_synthetic", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.over_budget(1.11, 1.0) is True
    assert mod.over_budget(1.10, 1.0) is False


def test_manifest_roundtrip_record(tmp_path: Path):
    path = tmp_path / "manifest.jsonl"
    rec = Record(itemKey="K", status="not_found", reason="host_blocked")
    Manifest(path).write(rec)
    again = Manifest(path)
    assert again.get("K").reason == "host_blocked"
