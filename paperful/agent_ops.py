"""Shared builders for ``--format json`` and the thin MCP server."""

from __future__ import annotations

import json
from pathlib import Path
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


def coverage_envelope(
    *,
    rows: list[Any],
    folder: Any,
    flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interesting = [r for r in rows if getattr(r, "status", "") != "in_collection"]
    items_out = [
        {
            "doi": getattr(r, "doi", "") or "",
            "title": getattr(r, "title", "") or "",
            "status": getattr(r, "status", "") or "",
            "suggested_action": getattr(r, "suggested_action", "") or "",
            "item_key": getattr(r, "item_key", "") or "",
        }
        for r in interesting
    ]
    return envelope(
        command="coverage",
        summary={
            "mentioned": len(rows),
            "in_collection": sum(
                1 for r in rows if getattr(r, "status", "") == "in_collection"
            ),
            "missing": sum(1 for r in rows if getattr(r, "status", "") == "missing"),
            "ambiguous": sum(
                1 for r in rows if getattr(r, "status", "") == "ambiguous"
            ),
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


def doctor_checks(cfg: Config, *, probe: bool = False) -> list[Any]:
    """Same checks as ``paperful doctor`` (no TTY guide)."""
    from .doctor import run_checks
    from .zot import ZoteroLocal

    try:
        return run_checks(cfg, ZoteroLocal(), probe=probe)
    except Exception:
        return run_checks(cfg, None, probe=probe)


def doctor_payload(cfg: Config, *, probe: bool = False) -> list[dict[str, Any]]:
    """``paperful doctor --json`` body."""
    return [
        {
            "name": c.name,
            "status": c.status,
            "code": c.code,
            "detail": c.detail,
        }
        for c in doctor_checks(cfg, probe=probe)
    ]


def collections_tree(cfg: Config) -> dict[str, Any]:
    """Collection paths with item counts. Read-only."""
    from .catalogue import open_library

    try:
        backend = open_library(cfg)
        cols = backend.collections()
        counts = backend.collection_counts()
    except LibraryError as exc:
        return {"ok": False, "exit": 2, "error": str(exc), "collections": []}
    rows = []
    for c in sorted(cols.values(), key=lambda c: c.path.lower()):
        n, missing = counts.get(c.key, (0, 0))
        rows.append(
            {
                "path": c.path,
                "name": c.name,
                "key": c.key,
                "items": n,
                "missing_pdf": missing,
            }
        )
    return {"ok": True, "collections": rows}


def last_run(cfg: Config) -> dict[str, Any] | None:
    """``state/last-run.json`` when present."""
    import json

    path = cfg.state_dir / "last-run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def ingest_dois_exit(*, apply: bool, created: int, failed: int) -> int:
    """Held/unresolved stay findings (exit 0). Mixed create+error on --apply is 3."""
    if not apply:
        return 0
    return batch_exit(ok=created, failed=failed)


def collections_add_exit(*, apply: bool, added: int, failed: int) -> int:
    """not-found / already-in stay findings (exit 0). Mixed add+error on --apply is 3."""
    if not apply:
        return 0
    return batch_exit(ok=added, failed=failed)


def gaps_envelope(
    items: list[Any],
    *,
    list_missing: bool = False,
    handoff: str = "",
    missing_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .dedupe import summarize_gaps

    counts = summarize_gaps(items)
    rows: list[dict[str, Any]] = []
    for it in items:
        codes: list[str] = []
        if not it.has_pdf:
            codes.append("no_stored_pdf")
        if it.has_linked_url and not it.has_pdf:
            codes.append("linked_url_only")
        if not it.doi:
            codes.append("missing_doi")
        if it.pdf_tier == "snapshot":
            codes.append("snapshot_only")
        if codes:
            rows.append(
                {"itemKey": it.key, "title": it.title, "status": ",".join(codes)}
            )
    summary: dict[str, Any] = {
        "items": counts.items,
        "no_stored_pdf": counts.no_stored_pdf,
        "linked_url_only": counts.linked_url_only,
        "missing_doi": counts.missing_doi,
        "snapshot_only": counts.snapshot_only,
    }
    if missing_rows is not None:
        summary["missing_pdfs"] = len(missing_rows)
    body = envelope(
        command="gaps",
        summary=summary,
        items=missing_rows if missing_rows is not None else rows,
        flags={"list_missing": list_missing, "handoff": handoff if list_missing else ""},
    )
    return body


def run_gaps(
    cfg: Config,
    *,
    collection: str | list[str] | None = None,
    library: bool = False,
) -> dict[str, Any]:
    """Counts and gap rows for scoped items. MCP: no handoff / list-missing."""
    from .catalogue import open_library

    cols = collection
    if isinstance(cols, str):
        cols = [cols] if cols.strip() else []
    elif cols is None:
        cols = []
    if not cols and not library:
        return envelope(
            command="gaps",
            exit_code=EXIT_USER,
            summary={"error": "collection or library is required"},
        )
    try:
        backend = open_library(cfg)
        loaded = load_scope(
            backend,
            collections=list(cols) if cols else None,
            library=library,
        )
    except (LibraryError, ScopeError) as exc:
        return envelope(
            command="gaps",
            exit_code=2 if isinstance(exc, LibraryError) else EXIT_USER,
            summary={"error": str(exc)},
        )
    return gaps_envelope(loaded.items)


def snowball_result_envelope(
    command: str,
    result: Any,
    *,
    flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = getattr(result, "summary", None) or {}
    run_dir = Path(getattr(result, "run_dir", "") or "")
    if not summary and run_dir.is_dir():
        summary_path = run_dir / "summary.json"
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except ValueError:
                summary = {}
    return envelope(
        command=command,
        summary=summary if isinstance(summary, dict) else {},
        paths={"run": str(run_dir)} if str(run_dir) else {},
        flags=flags or {},
        exit_code=int(getattr(result, "exit_code", 0) or 0),
    )


def run_snowball_search(
    cfg: Config,
    query: str,
    *,
    depth: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict[str, Any]:
    """Keyword preview; always dry-run (no parent creates)."""
    import sys

    from rich.console import Console

    from .snowball.command import SnowballError, SnowballRequest, run_search

    q = (query or "").strip()
    if not q:
        return envelope(
            command="snowball search",
            exit_code=EXIT_USER,
            summary={"error": "query is required"},
        )
    request = SnowballRequest(
        gate="dry-run",
        collection=cfg.snowball_target_collection or "",
        fetch_pdfs=False,
        depth=depth,
        year_from=year_from,
        year_to=year_to,
        direction=cfg.snowball_direction or "refs",
    )
    console = Console(file=sys.stderr, highlight=False, quiet=True)
    try:
        result = run_search(cfg, q, request, console=console)
    except SnowballError as exc:
        return envelope(
            command="snowball search",
            exit_code=exc.code,
            summary={"error": str(exc)},
        )
    return snowball_result_envelope(
        "snowball search",
        result,
        flags={"dry_run": True, "read_only": True},
    )


def run_export(
    cfg: Config,
    *,
    collection: str | list[str] | None = None,
    library: bool = False,
    kind: str = "bibtex",
) -> dict[str, Any]:
    """Bibliography text from the scoped library (read-only)."""
    from .catalogue import open_library
    from .export_build import build_scope_records
    from .interop.load import dump_records

    cols = collection
    if isinstance(cols, str):
        cols = [cols] if cols.strip() else []
    elif cols is None:
        cols = []
    fmt = kind.strip().lower().replace("_", "-")
    if fmt in {"bib", "biblatex"}:
        fmt = "bibtex"
    if fmt not in {"ris", "bibtex"}:
        return envelope(
            command="export",
            exit_code=EXIT_USER,
            summary={"error": "format must be ris or bibtex"},
        )
    if not cols and not library:
        return envelope(
            command="export",
            exit_code=EXIT_USER,
            summary={"error": "collection or library is required"},
        )
    try:
        backend = open_library(cfg)
        loaded = load_scope(
            backend,
            collections=list(cols) if cols else None,
            library=library,
        )
    except (LibraryError, ScopeError) as exc:
        return envelope(
            command="export",
            exit_code=2 if isinstance(exc, LibraryError) else EXIT_USER,
            summary={"error": str(exc)},
        )
    records, _ = build_scope_records(cfg, backend, loaded.items, include_notes=False)
    if not records:
        return envelope(
            command="export",
            summary={"records": 0, "scope": loaded.label},
            flags={"format": fmt, "read_only": True},
        )
    text = dump_records(records, fmt)
    return envelope(
        command="export",
        summary={
            "records": len(records),
            "scope": loaded.label,
            "bibliography": text,
        },
        flags={"format": fmt, "read_only": True},
    )


def run_snowball_trends(
    cfg: Config,
    query: str | None = None,
    *,
    profile: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict[str, Any]:
    """Publication-year histogram; read-only (no library access)."""
    from .agent_json import envelope, EXIT_USER
    from .snowball.command import SnowballError
    from .snowball.trends import trends_for_scope

    if not (query or "").strip() and not (profile or "").strip():
        return envelope(
            command="snowball trends",
            exit_code=EXIT_USER,
            summary={"error": "query or profile is required"},
            flags={"read_only": True},
        )
    try:
        report = trends_for_scope(
            cfg,
            query=query,
            profile=profile,
            year_from=year_from,
            year_to=year_to,
        )
    except SnowballError as exc:
        return envelope(
            command="snowball trends",
            exit_code=exc.code,
            summary={"error": str(exc)},
            flags={"read_only": True},
        )
    return envelope(
        command="snowball trends",
        summary={
            "query": report.query,
            "profile": report.profile or "",
            "total": report.total,
            "years": [{"year": row.year, "count": row.count} for row in report.years],
        },
        flags={"read_only": True, "dry_run": True},
    )


def run_proposal_export(cfg: Config, pack: str, *, kind: str = "bibtex") -> dict[str, Any]:
    """BibTeX or RIS from a snowball / authorwatch proposal pack on disk."""
    from .pack_bib import export_pack_text

    fmt = kind.strip().lower().replace("_", "-")
    if fmt in {"bib", "biblatex"}:
        fmt = "bibtex"
    if fmt not in {"ris", "bibtex"}:
        return envelope(
            command="export-proposals",
            exit_code=EXIT_USER,
            summary={"error": "format must be ris or bibtex"},
        )
    spec = (pack or "").strip()
    if not spec:
        return envelope(
            command="export-proposals",
            exit_code=EXIT_USER,
            summary={"error": "pack path is required"},
        )
    path = Path(spec)
    if not path.is_absolute():
        path = cfg.state_dir / spec
    try:
        text, jsonl, n = export_pack_text(path, fmt)
    except (FileNotFoundError, ValueError) as exc:
        return envelope(
            command="export-proposals",
            exit_code=EXIT_USER,
            summary={"error": str(exc)},
        )
    return envelope(
        command="export-proposals",
        summary={"records": n, "bibliography": text},
        paths={"pack": str(path), "jsonl": str(jsonl)},
        flags={"format": fmt, "read_only": True},
    )
