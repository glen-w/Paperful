"""Shared builders for ``--format json`` and the thin MCP server."""

from __future__ import annotations

from typing import Any

from .agent_json import EXIT_USER, batch_exit, envelope
from .config import Config
from .library import LibraryError
from .scope import ScopeError, load_scope


def refs_gap_envelope(
    *,
    refs: list[Any],
    findings: list[Any],
    folder: Any,
    flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing = [r for r in refs if not r.already_exists]
    items_out = [
        {
            "doi": r.doi,
            "title": r.title,
            "cited_by_count_in_scope": len(r.citing_keys),
            "suggested_action": r.suggested_action,
        }
        for r in sorted(missing, key=lambda r: (-len(r.citing_keys), r.doi or r.title))
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
        flags={"dry_run": True, **(flags or {})},
    )


def run_refs_gap(cfg: Config, collection: str) -> dict[str, Any]:
    """MCP / shared scan: always dry-run, never creates parents."""
    from .catalogue import open_library
    from .identity import LibraryFingerprint
    from .mirror import pdf_for
    from .refs_gap import scan_items, write_pack

    spec = (collection or "").strip()
    if not spec:
        return envelope(
            command="refs gap",
            exit_code=EXIT_USER,
            summary={"error": "collection is required"},
        )
    try:
        backend = open_library(cfg)
        loaded = load_scope(backend, collections=[spec], library=False)
    except (LibraryError, ScopeError) as exc:
        return envelope(
            command="refs gap",
            exit_code=2 if isinstance(exc, LibraryError) else EXIT_USER,
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
    return refs_gap_envelope(refs=refs, findings=findings, folder=folder)


def ask_envelope(
    *,
    items: list[dict[str, Any]],
    flags: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    exit_code: int = 0,
) -> dict[str, Any]:
    answered = sum(1 for row in items if row.get("answer"))
    body = summary or {
        "questions": len(items),
        "answered": answered,
    }
    return envelope(
        command="ask",
        summary=body,
        items=items,
        flags={"read_only": True, **(flags or {})},
        exit_code=exit_code,
    )


def run_ask(cfg: Config, question: str, collection: str = "") -> dict[str, Any]:
    """One-shot RAG answer. Read-only for the reference manager."""
    from .llm import LLMClientError
    from .rag.answer import answer
    from .rag.retrieve import scope_keys

    q = (question or "").strip()
    if not q:
        return envelope(
            command="ask",
            exit_code=EXIT_USER,
            summary={"error": "question is required"},
        )
    if not cfg.rag_enabled:
        return envelope(
            command="ask",
            exit_code=EXIT_USER,
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
        return ask_envelope(
            summary={"question": q, "questions": 1, "answered": 1},
            items=[
                {
                    "question": q,
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
        return envelope(command="ask", exit_code=EXIT_USER, summary={"error": str(exc)})


def ingest_dois_exit(*, apply: bool, created: int, failed: int) -> int:
    """Held/unresolved stay findings (exit 0). Mixed create+error on --apply is 3."""
    if not apply:
        return 0
    return batch_exit(ok=created, failed=failed)
