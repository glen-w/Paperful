"""MCP stdio server: framing, dispatch and tool routing (every tool body stubbed)."""

from __future__ import annotations

import io
import json

import pytest

from paperful import mcp_server as mcp
from paperful.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")


def _frame(obj) -> bytes:
    raw = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n" % len(raw) + raw


def _read_frames(data: bytes) -> list[dict]:
    out, buf = [], io.BytesIO(data)
    while True:
        msg = mcp._read_message(buf)
        if msg is None:
            return out
        out.append(msg)


def test_read_message_content_length_and_line_json():
    framed = io.BytesIO(_frame({"id": 1, "method": "ping"}))
    assert mcp._read_message(framed) == {"id": 1, "method": "ping"}
    assert mcp._read_message(framed) is None  # EOF

    line = io.BytesIO(b'{"id": 2, "method": "tools/list"}\n')
    assert mcp._read_message(line) == {"id": 2, "method": "tools/list"}


@pytest.mark.parametrize(
    "raw",
    [b"", b"{not json}\n", b"nonsense without colon\n", b"Content-Length: 0\r\n\r\n"],
)
def test_read_message_returns_none_on_garbage(raw):
    assert mcp._read_message(io.BytesIO(raw)) is None


def test_read_message_reads_exact_body_for_text_streams():
    class TextStream:
        def __init__(self, data: bytes):
            self.buffer = io.BytesIO(data)

    msg = mcp._read_message(TextStream(_frame({"id": 7})))
    assert msg == {"id": 7}


def test_write_message_frames_utf8_payload():
    out = io.BytesIO()
    mcp._write_message(out, {"id": 1, "text": "café"})
    data = out.getvalue()
    header, _, body = data.partition(b"\r\n\r\n")
    assert header == b"Content-Length: %d" % len(body)
    assert json.loads(body) == {"id": 1, "text": "café"}


def test_initialize_and_tools_list(cfg):
    init = mcp.dispatch(cfg, {"method": "initialize", "id": 1})
    assert init["result"]["serverInfo"]["name"] == "paperful"
    assert init["result"]["capabilities"] == {"tools": {}}
    listed = mcp.dispatch(cfg, {"method": "tools/list", "id": 2})["result"]["tools"]
    names = {t["name"] for t in listed}
    assert {"refs_gap", "gaps", "snowball_search", "snowball_trends", "export", "proposal_export", "ask"} <= names
    for tool in listed:
        assert tool["inputSchema"]["type"] == "object"


def test_dispatch_notifications_unknown_methods_and_shutdown(cfg):
    assert mcp.dispatch(cfg, {"method": "notifications/initialized"}) is None
    assert mcp.dispatch(cfg, {"method": "mystery"}) is None  # notification: no id, no reply
    err = mcp.dispatch(cfg, {"method": "mystery", "id": 9})
    assert err["error"]["code"] == -32601 and "mystery" in err["error"]["message"]
    assert mcp.dispatch(cfg, {"method": "shutdown", "id": 3})["result"] == {}
    assert mcp.dispatch(cfg, {"method": "exit"}) is None


def test_unknown_tool_is_a_protocol_error(cfg):
    reply = mcp.dispatch(
        cfg, {"method": "tools/call", "id": 4, "params": {"name": "rm_rf", "arguments": {}}}
    )
    assert reply["error"]["code"] == -32601 and "rm_rf" in reply["error"]["message"]


def test_tools_call_routes_each_tool_with_normalised_args(cfg, monkeypatch):
    calls: dict[str, tuple] = {}

    def spy(name):
        def fn(*args, **kwargs):
            calls[name] = (args, kwargs)
            return {"ok": True, "tool": name}

        return fn

    monkeypatch.setattr(mcp, "run_refs_gap", spy("refs_gap"))
    monkeypatch.setattr(mcp, "run_gaps", spy("gaps"))
    monkeypatch.setattr(mcp, "run_snowball_search", spy("snowball_search"))
    monkeypatch.setattr(mcp, "run_snowball_trends", spy("snowball_trends"))
    monkeypatch.setattr(mcp, "run_export", spy("export"))
    monkeypatch.setattr(mcp, "run_proposal_export", spy("proposal_export"))
    monkeypatch.setattr(mcp, "run_ask", spy("ask"))

    def call(name, **arguments):
        reply = mcp.dispatch(
            cfg, {"method": "tools/call", "id": 1, "params": {"name": name, "arguments": arguments}}
        )
        return json.loads(reply["result"]["content"][0]["text"])

    assert call("refs_gap", collection="Ocean")["tool"] == "refs_gap"
    assert calls["refs_gap"][0] == (cfg, "Ocean")
    call("gaps", library=True)
    assert calls["gaps"][1] == {"collection": None, "library": True}
    call("snowball_search", query="bbnj", depth=2, year_from=2020)
    assert calls["snowball_search"][0] == (cfg, "bbnj")
    assert calls["snowball_search"][1] == {"depth": 2, "year_from": 2020, "year_to": None}
    call("snowball_trends", profile="p")
    assert calls["snowball_trends"][0] == (cfg, None)
    assert calls["snowball_trends"][1]["profile"] == "p"
    call("export", collection="Ocean")
    assert calls["export"][1] == {"collection": "Ocean", "library": False, "kind": "bibtex"}
    call("export", library=True, format="ris")
    assert calls["export"][1] == {"collection": None, "library": True, "kind": "ris"}
    call("proposal_export", pack="p1", format="csljson")
    assert calls["proposal_export"][0] == (cfg, "p1") and calls["proposal_export"][1] == {"kind": "csljson"}
    call("ask", question="what?", collection="C")
    assert calls["ask"][0] == (cfg, "what?", "C")
    assert calls["ask"][1] == {"ask_mode": None}
    call("ask", question="what?", ask_mode="advanced")
    assert calls["ask"][1] == {"ask_mode": "advanced"}


def test_tools_call_tolerates_non_dict_arguments(cfg, monkeypatch):
    monkeypatch.setattr(mcp, "run_refs_gap", lambda cfg, collection: {"collection": collection})
    reply = mcp.dispatch(
        cfg, {"method": "tools/call", "id": 1, "params": {"name": "refs_gap", "arguments": ["junk"]}}
    )
    assert json.loads(reply["result"]["content"][0]["text"])["collection"] == ""


def test_serve_stdio_end_to_end(cfg):
    stdin = io.BytesIO(
        _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        + _frame({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + _frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + _frame({"jsonrpc": "2.0", "id": 3, "method": "exit"})
        + _frame({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})  # after exit: never answered
    )
    stdout = io.BytesIO()
    mcp.serve_stdio(cfg, stdin, stdout)
    replies = _read_frames(stdout.getvalue())
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[1]["result"]["tools"]


def test_serve_stdio_stops_at_eof(cfg):
    out = io.BytesIO()
    mcp.serve_stdio(cfg, io.BytesIO(b""), out)
    assert out.getvalue() == b""


def test_mcp_surface_is_the_documented_read_only_set():
    """Adding a write-capable tool must be a deliberate change to this list and the docs."""
    names = {t["name"] for t in mcp.TOOLS}
    assert names == {
        "refs_gap", "gaps", "snowball_search", "snowball_trends",
        "export", "proposal_export", "ask",
    }
    verbs = ("apply", "attach", "delete", "trash", "write", "merge", "restore", "import")
    assert not [n for n in names if any(v in n for v in verbs)]
