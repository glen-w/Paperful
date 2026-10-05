"""Thin MCP stdio server over the same JSON channel as ``--format json``.

Tools: ``refs_gap`` (never writes parents) and ``ask`` (index read + LLM).
``collections add`` is CLI-only (``--apply`` writes). Prefer CLI ``--format json``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, TextIO

from .agent_json import dumps
from .agent_ops import run_ask, run_refs_gap
from .config import Config
from . import __version__

PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "refs_gap",
        "description": (
            "Cited works inside collection PDFs that are not in the library. "
            "Always dry-run. Never creates parents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection path, name, or key.",
                }
            },
            "required": ["collection"],
        },
    },
    {
        "name": "ask",
        "description": (
            "Answer a question from the on-disk RAG index. Read-only for the "
            "reference manager. Needs rag ingest first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "collection": {
                    "type": "string",
                    "description": "Optional mirror collection path.",
                },
            },
            "required": ["question"],
        },
    },
]


def _as_binary(stream: TextIO | BinaryIO) -> BinaryIO:
    buf = getattr(stream, "buffer", None)
    if buf is not None:
        return buf
    return stream  # type: ignore[return-value]


def _read_message(stdin: TextIO | BinaryIO) -> dict[str, Any] | None:
    buf = _as_binary(stdin)
    headers: dict[str, str] = {}
    while True:
        line = buf.readline()
        if line == b"" or line == "":
            return None
        if line in (b"\r\n", b"\n", "\r\n", "\n"):
            break
        text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
        stripped = text.strip()
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return None
        if ":" not in text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
        key, value = text.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    n = int(headers.get("content-length") or "0")
    if n < 1:
        return None
    body = buf.read(n)
    if isinstance(body, str):
        return json.loads(body)
    return json.loads(body.decode("utf-8"))


def _write_message(stdout: TextIO | BinaryIO, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
    buf = _as_binary(stdout)
    buf.write(header + raw)
    buf.flush()


def _result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": dumps(payload)}]}


def handle_initialize(req_id: Any) -> dict[str, Any]:
    return _result(
        req_id,
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "paperful", "version": __version__},
        },
    )


def handle_tools_list(req_id: Any) -> dict[str, Any]:
    return _result(req_id, {"tools": TOOLS})


def call_refs_gap(cfg: Config, collection: str) -> dict[str, Any]:
    return run_refs_gap(cfg, collection)


def call_ask(cfg: Config, question: str, collection: str = "") -> dict[str, Any]:
    return run_ask(cfg, question, collection)


def handle_tools_call(cfg: Config, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    if name == "refs_gap":
        body = call_refs_gap(cfg, str(args.get("collection") or ""))
    elif name == "ask":
        body = call_ask(
            cfg,
            str(args.get("question") or ""),
            str(args.get("collection") or ""),
        )
    else:
        return _error(req_id, -32601, f"unknown tool {name}")
    return _result(req_id, _text(body))


def dispatch(cfg: Config, message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    req_id = message.get("id")
    if method == "initialize":
        return handle_initialize(req_id)
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return handle_tools_list(req_id)
    if method == "tools/call":
        return handle_tools_call(cfg, req_id, message.get("params") or {})
    if method in {"shutdown", "exit"}:
        return _result(req_id, {}) if req_id is not None else None
    if req_id is None:
        return None
    return _error(req_id, -32601, f"unknown method {method}")


def serve_stdio(
    cfg: Config,
    stdin: TextIO | BinaryIO | None = None,
    stdout: TextIO | BinaryIO | None = None,
) -> None:
    """MCP JSON-RPC over stdio (Content-Length framing, or one JSON object per line)."""
    inn = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    while True:
        try:
            message = _read_message(inn)
        except json.JSONDecodeError:
            continue
        if message is None:
            return
        reply = dispatch(cfg, message)
        if reply is not None:
            _write_message(out, reply)
        if str(message.get("method") or "") == "exit":
            return
