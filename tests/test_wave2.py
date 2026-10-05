"""Wave 2: agent JSON, typed notes, handoff ranking, MCP, Ask threads."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.agent_json import EXIT_PARTIAL, batch_exit, envelope
from paperful.handoff import HINT_OPENABLE, MissingPdf
from paperful.handoff_rank import rank_missing
from paperful.mcp_server import dispatch
from paperful.notehtml import first_line, parse, wrap
from paperful.rag.thread import load_thread, new_id, rewrite_query, save_thread


def test_batch_exit_partial():
    assert batch_exit(ok=2, failed=1) == EXIT_PARTIAL
    assert batch_exit(ok=0, failed=1) == 1
    assert batch_exit(ok=1, failed=0) == 0


def test_envelope_schema():
    body = envelope(command="run", summary={"n": 1}, exit_code=0)
    assert body["schema"] == "paperful.agent.json.v1"
    assert body["ok"] is True and body["partial"] is False


def test_note_wrap_idempotent():
    html = wrap("<p>body</p>", note_type="summary", verb="summarize", model="qwen")
    assert first_line("summary", model="qwen") in html
    assert parse(html)["schema"] == "paperful.note.v1"
    again = wrap(html, note_type="summary", verb="summarize", model="qwen")
    assert again == html


def test_handoff_ranks_cites_times_severity(tmp_path: Path):
    pack_dir = tmp_path / "refs-gaps" / "20260101T000000Z-bbnj"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "already_exists": True,
                        "exists_key": "HOT",
                        "doi": "10.1/hot",
                        "citing_keys": ["A", "B", "C"],
                        "cited_by_count_in_scope": 3,
                    },
                    {
                        "already_exists": True,
                        "exists_key": "COLD",
                        "doi": "10.1/cold",
                        "citing_keys": ["A"],
                        "cited_by_count_in_scope": 1,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    hot = MissingPdf(
        key="HOT",
        title="Z last",
        doi="10.1/hot",
        url="",
        hint="doi_only",
        attempts=[],
        miss_surface="paywalled",
    )
    cold = MissingPdf(
        key="COLD",
        title="A first",
        doi="10.1/cold",
        url="https://example.org/a.pdf",
        hint=HINT_OPENABLE,
        attempts=[],
        miss_surface="no_oa",
    )
    ranked = rank_missing([cold, hot], tmp_path)
    assert [r.key for r in ranked] == ["HOT", "COLD"]


def test_mcp_lists_refs_gap_and_ask():
    cfg = type("C", (), {})()
    listed = dispatch(cfg, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names == {"refs_gap", "ask"}
    init = dispatch(cfg, {"jsonrpc": "2.0", "id": 2, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "paperful"


def test_rewrite_query_uses_history():
    class Client:
        def complete(self, request):
            assert "Follow-up:" in request.prompt
            return "BBNJ EIA procedure"

    cfg = type("C", (), {"rag_model": "m", "llm_model": "m", "llm_timeout_s": 10, "llm_max_num_ctx": 2048})()
    q = rewrite_query(
        cfg,
        "and the EIA part?",
        [{"role": "user", "content": "What is BBNJ?"}, {"role": "assistant", "content": "A treaty."}],
        client=Client(),
    )
    assert q == "BBNJ EIA procedure"


def test_thread_roundtrip(tmp_path: Path):
    from paperful.rag.thread import Thread

    tid = new_id()
    save_thread(
        tmp_path,
        Thread(thread_id=tid, turns=[{"role": "user", "content": "hi"}], last_query="hi"),
    )
    loaded = load_thread(tmp_path, tid)
    assert loaded.turns[0]["content"] == "hi"


def test_note_prefixes():
    assert first_line("attach", extra="oa:unpaywall") == "Attach: oa:unpaywall"
    assert first_line("duplicate") == "Duplicate:"


def test_mcp_unknown_tool_and_disabled_ask():
    from paperful.mcp_server import call_ask, handle_tools_call

    cfg = type("C", (), {})()
    err = handle_tools_call(cfg, 9, {"name": "collections_add", "arguments": {}})
    assert err["error"]["code"] == -32601
    off = type("C", (), {"rag_enabled": False})()
    body = call_ask(off, "What is BBNJ?")
    assert body["exit"] == 1 and "rag.enabled" in body["summary"]["error"]
