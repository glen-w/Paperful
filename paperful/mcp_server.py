"""Thin MCP stdio server over the same JSON channel as ``--format json``.

Tools: ``refs_gap`` (never writes parents) and ``ask`` (index read + LLM).
No ``collections add`` — that verb is parked.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .agent_json import dumps, envelope
from .config import Config
from .library import LibraryError
from .scope import ScopeError, load_scope
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


def _read_message(stdin: TextIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if line == "":
            return None
        if line in ("\r\n", "\n"):
            break
        if ":" not in line:
            # JSON-RPC newline mode (tests / simple clients).
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    n = int(headers.get("content-length") or "0")
    if n < 1:
        return None
    body = stdin.read(n)
    return json.loads(body)


def _write_message(stdout: TextIO, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    stdout.write(f"Content-Length: {len(raw.encode())}\r\n\r\n{raw}")
    stdout.flush()


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
    from .catalogue import open_library
    from .identity import LibraryFingerprint
    from .mirror import pdf_for
    from .refs_gap import scan_items, write_pack

    spec = (collection or "").strip()
    if not spec:
        return envelope(
            command="refs gap",
            exit_code=1,
            summary={"error": "collection is required"},
        )
    try:
        backend = open_library(cfg)
        loaded = load_scope(backend, collections=[spec], library=False)
    except (LibraryError, ScopeError) as exc:
        return envelope(
            command="refs gap",
            exit_code=2 if isinstance(exc, LibraryError) else 1,
            summary={"error": str(exc)},
        )
    items = loaded.items
    fingerprint = LibraryFingerprint.from_items(
        list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else items,
        scope="library",
        collection=spec,
    )
    refs, findings = scan_items(items, lambda it: pdf_for(cfg.out_dir, it), fingerprint)
    folder = write_pack(cfg.state_dir, loaded.label, refs, findings)
    missing = [r for r in refs if not r.already_exists]
    items_out = [
        {
            "doi": r.doi,
            "title": r.title,
            "cited_by_count_in_scope": len(r.citing_keys),
            "suggested_action": r.suggested_action,
        }
        for r in missing[:100]
    ]
    return envelope(
        command="refs gap",
        summary={
            "cited": len(refs),
            "missing": len(missing),
            "needs_ocr": sum(1 for f in findings if f.finding == "needs_ocr"),
        },
        items=items_out,
        paths={"pack": str(folder)},
        flags={"dry_run": True},
    )


def call_ask(cfg: Config, question: str, collection: str = "") -> dict[str, Any]:
    from .llm import LLMClientError
    from .rag.answer import answer
    from .rag.retrieve import scope_keys

    q = (question or "").strip()
    if not q:
        return envelope(command="ask", exit_code=1, summary={"error": "question is required"})
    if not cfg.rag_enabled:
        return envelope(
            command="ask",
            exit_code=1,
            summary={"error": "rag.enabled is false"},
        )
    try:
        from .rag.index import Index, ledger_path
        from .rag.ledger import Ledger

        index = Index.open(cfg)
        ledger = Ledger(ledger_path(cfg))
        keys = None
        if (collection or "").strip():
            keys = scope_keys(ledger, collections=[collection.strip()])
        reply = answer(cfg, q, keys=keys, index=index, ledger=ledger)
        text = reply.read()
        cited = reply.cited() or reply.sources
        return envelope(
            command="ask",
            summary={"question": q},
            items=[
                {
                    "answer": text,
                    "sources": [
                        {"marker": s.marker, "itemKey": s.item_key, "title": s.title}
                        for s in cited
                    ],
                }
            ],
            flags={"read_only": True},
        )
    except (LLMClientError, Exception) as exc:
        return envelope(command="ask", exit_code=1, summary={"error": str(exc)})


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


def serve_stdio(cfg: Config, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    """MCP JSON-RPC over stdio (Content-Length framing, or one JSON object per line)."""
    inn = stdin or sys.stdin
    out = stdout or sys.stdout
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
