"""Wanted Advanced jobs: attach, recover, handoff, inbox drain, reachout, pending add."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..store import Manifest
from . import commands
from .pages import scope_fingerprint

# Test hooks
attach_pending_fn: Callable[..., dict[str, Any]] | None = None
recover_fn: Callable[..., dict[str, Any]] | None = None
handoff_fn: Callable[..., dict[str, Any]] | None = None
inbox_drain_fn: Callable[..., dict[str, Any]] | None = None
reachout_fn: Callable[..., dict[str, Any]] | None = None


def _attach_result(cfg: Config, cmd_id: str, result: dict[str, Any]) -> None:
    rec = commands.read_command(cfg, cmd_id)
    if rec is None:
        return
    rec["result"] = result
    commands.write_command(cfg, rec)


def _load_items(cfg: Config, collection: str) -> tuple[Any, list[Any], Manifest]:
    from ..catalogue import open_library
    from ..scope import load_scope

    backend = open_library(cfg)
    coll = (collection or "").strip()
    loaded = load_scope(
        backend,
        collections=[coll] if coll else [],
        library=not bool(coll),
    )
    return backend, list(loaded.items), Manifest(cfg.manifest_path)


def attach_preview(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    keys: list[str] | None,
    allow_mismatch: bool,
    allow_short: bool,
) -> str:
    backend, items, manifest = _load_items(cfg, collection)
    del backend
    if keys:
        keyset = set(keys)
        items = [it for it in items if it.key in keyset]
    pending = manifest.pending_attach(
        allow_pdf_doi_mismatch=allow_mismatch,
        allow_short_pdf=allow_short,
    )
    if keys:
        keyset = set(keys)
        pending = [r for r in pending if r.itemKey in keyset]
    stored_keys = [r.itemKey for r in pending] or [it.key for it in items]
    fp_keyset = set(stored_keys)
    fp_items = [it for it in items if it.key in fp_keyset] if fp_keyset else items
    fp = scope_fingerprint(fp_items, manifest)
    return commands.create_review_token(
        cfg,
        verb="attach",
        collection=collection,
        preset="oa",
        keys=stored_keys,
        fingerprint=fp,
        command_id=cmd_id,
        flags={
            "allow_mismatch": allow_mismatch,
            "allow_short": allow_short,
        },
    )


def attach_apply(cfg: Config, *, token: str) -> tuple[bool, str]:
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    collection = str(review.get("collection") or "")
    flags = dict(review.get("flags") or {})
    allow_mismatch = bool(flags.get("allow_mismatch"))
    allow_short = bool(flags.get("allow_short"))
    backend, items, manifest = _load_items(cfg, collection)
    keyset = set(review.get("keys") or [])
    items = [it for it in items if it.key in keyset] if keyset else items
    fp = scope_fingerprint(items, manifest)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg
    if attach_pending_fn is not None:
        attach_pending_fn(
            cfg,
            keys=list(keyset),
            allow_mismatch=allow_mismatch,
            allow_short=allow_short,
        )
        return True, ""
    from ..pipeline import Pipeline
    from rich.console import Console

    pending = [
        r
        for r in manifest.pending_attach(
            allow_pdf_doi_mismatch=allow_mismatch,
            allow_short_pdf=allow_short,
        )
        if not keyset or r.itemKey in keyset
    ]
    if not pending:
        return True, ""
    pipe = Pipeline(
        cfg, Manifest(cfg.manifest_path), Console(quiet=True, file=None), attacher=backend
    )
    for rec in pending:
        pipe.attach_record(rec)
    flush = getattr(backend, "flush", None)
    if callable(flush):
        flush()
    return True, ""


def recover_preview(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    keys: list[str],
    from_last_run: bool,
    from_last_run_mode: str,
    limit: int | None,
) -> str:
    backend, items, manifest = _load_items(cfg, collection)
    del backend
    if keys:
        keyset = set(keys)
        items = [it for it in items if it.key in keyset]
    fp = scope_fingerprint(items, manifest)
    return commands.create_review_token(
        cfg,
        verb="recover",
        collection=collection,
        preset="oa",
        keys=[it.key for it in items] if keys else keys,
        fingerprint=fp,
        command_id=cmd_id,
        flags={
            "from_last_run": from_last_run,
            "from_last_run_mode": from_last_run_mode,
            "limit": limit,
            "keys": list(keys),
        },
    )


def recover_apply(cfg: Config, *, token: str) -> tuple[bool, str]:
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    collection = str(review.get("collection") or "")
    flags = dict(review.get("flags") or {})
    keys = list(flags.get("keys") or review.get("keys") or [])
    backend, items, manifest = _load_items(cfg, collection)
    del backend
    if keys:
        keyset = set(keys)
        scope_items = [it for it in items if it.key in keyset]
    else:
        scope_items = items
    fp = scope_fingerprint(scope_items, manifest)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg
    if recover_fn is not None:
        recover_fn(cfg, flags=flags)
        return True, ""
    from rich.console import Console

    from ..recover_cmd import run_recover

    run_recover(
        Console(quiet=True, file=None),
        item=keys,
        from_last_run=bool(flags.get("from_last_run")),
        from_last_run_mode=str(flags.get("from_last_run_mode") or "browser_agent_miss"),
        limit=flags.get("limit"),
        dry_run=False,
        no_attach=False,
        config=cfg.config_path,
        fmt="json",
    )
    return True, ""


def handoff_run(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    keys: list[str] | None,
    mode: str,
    include_doi_tabs: bool,
) -> dict[str, Any]:
    if handoff_fn is not None:
        result = handoff_fn(
            cfg,
            collection=collection,
            keys=keys,
            mode=mode,
            include_doi_tabs=include_doi_tabs,
        )
        _attach_result(cfg, cmd_id, result)
        return result
    from ..handoff import list_missing_pdfs, open_tabs, parse_handoff
    from ..handoff_rank import rank_missing

    mode = parse_handoff(mode)
    backend, items, manifest = _load_items(cfg, collection)
    del backend
    if keys:
        keyset = set(keys)
        items = [it for it in items if it.key in keyset]
    missing = list_missing_pdfs(items, manifest, cfg=cfg)
    missing = rank_missing(missing, cfg.state_dir)
    result: dict[str, Any] = {"mode": mode, "count": len(missing)}

    def _write_list(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Handoff", ""]
        for row in missing:
            lines.append(f"- {row.title} · {row.key} · {row.tab_url()}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if mode == "list":
        path = cfg.state_dir / "gui" / "handoff-list.md"
        _write_list(path)
        result["path"] = str(path)
    elif mode in {"tabs", "walk"}:
        opened = open_tabs(
            missing,
            include_doi_tabs=include_doi_tabs,
            confirm=lambda _n: True,
            scholar=True,
            cfg=cfg,
        )
        result["opened"] = opened
    elif mode == "watch":
        from ..inbox import ensure_inbox_dirs

        root = ensure_inbox_dirs(cfg)
        result["inbox"] = str(root)
        path = cfg.state_dir / "gui" / "handoff-list.md"
        _write_list(path)
        result["path"] = str(path)
    _attach_result(cfg, cmd_id, result)
    return result


def inbox_drain(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
) -> dict[str, Any]:
    if inbox_drain_fn is not None:
        result = inbox_drain_fn(cfg, collection=collection)
        _attach_result(cfg, cmd_id, result)
        return result
    from ..inbox import ensure_inbox_dirs, process_candidates

    ensure_inbox_dirs(cfg)
    backend, items, manifest = _load_items(cfg, collection)
    stats = process_candidates(
        cfg,
        backend,
        manifest,
        items,
        once=True,
        collection=collection,
    )
    result = {
        "attached": stats.attached,
        "unmatched": stats.unmatched,
        "held": stats.held,
        "proposed": stats.proposed,
        "errors": stats.errors,
    }
    _attach_result(cfg, cmd_id, result)
    return result


def reachout_run(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    keys: list[str] | None,
    non_oa_only: bool,
    lookup: bool,
    handoff_mode: str,
) -> dict[str, Any]:
    if reachout_fn is not None:
        result = reachout_fn(
            cfg,
            collection=collection,
            keys=keys,
            non_oa_only=non_oa_only,
            lookup=lookup,
            handoff_mode=handoff_mode,
        )
        _attach_result(cfg, cmd_id, result)
        return result
    from ..reachout import build_reachout_rows, write_reachout_export

    backend, items, manifest = _load_items(cfg, collection)
    del backend
    if keys:
        keyset = set(keys)
        items = [it for it in items if it.key in keyset]
    rows = build_reachout_rows(
        cfg,
        items,
        non_oa_only=non_oa_only,
        lookup=lookup,
        manifest=manifest,
    )
    path = cfg.state_dir / "gui" / "reachout.csv"
    write_reachout_export(rows, path)
    result: dict[str, Any] = {"rows": len(rows), "path": str(path)}
    if handoff_mode in {"tabs", "walk"}:
        from ..handoff import HINT_AUTHOR_REQUEST, MissingPdf, open_tabs

        targets = [
            MissingPdf(
                key=r.key,
                title=r.title,
                doi=r.doi or "",
                url="",
                hint=HINT_AUTHOR_REQUEST,
                attempts=[],
                request_url=r.request_url,
            )
            for r in rows
            if r.request_url
        ]
        if targets:
            result["opened"] = open_tabs(
                targets, confirm=lambda _n: True, scholar=False, cfg=cfg
            )
    _attach_result(cfg, cmd_id, result)
    return result


def _pending_dois(raw: list[str] | None) -> list[str]:
    from ..resolve import normalize_doi

    seen: set[str] = set()
    out: list[str] = []
    for entry in raw or []:
        doi = normalize_doi(str(entry or "").strip())
        if not doi or doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return out


def pending_add_preview(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    dois: list[str],
) -> str:
    """Dry-run: classify Waiting-from-Discover DOIs into the scoped collection."""
    from ..acronyms import load_acronym_allowlist
    from ..catalogue import open_library
    from ..identity import LibraryFingerprint
    from ..ingest_dois import classify_rows, default_resolver, write_summary

    coll = (collection or "").strip()
    if not coll:
        raise ValueError("Set the collection chip before adding Waiting rows.")
    clean = _pending_dois(dois)
    if not clean:
        raise ValueError("Select at least one Waiting row that has a DOI.")
    backend = open_library(cfg)
    all_items = (
        list(backend.items_in_scope(None))
        if hasattr(backend, "items_in_scope")
        else []
    )
    fingerprint = LibraryFingerprint.from_items(
        all_items,
        scope=cfg.ingest_dedupe_scope,
        collection=coll,
    )
    resolver = default_resolver(cfg.email)
    allowed = load_acronym_allowlist(cfg.state_dir)
    batch = classify_rows(clean, fingerprint, resolve=resolver, allowlist=allowed)
    summary_path = write_summary(cfg.state_dir, coll, batch)
    fingerprint_hex = hashlib.sha256(
        f"{coll}|pending_fill|{','.join(clean)}".encode("utf-8")
    ).hexdigest()
    token = commands.create_review_token(
        cfg,
        verb="pending_fill_add",
        collection=coll,
        preset="oa",
        keys=clean[:200],
        fingerprint=fingerprint_hex,
        command_id=cmd_id,
        flags={"dois": clean, "source_path": "pending_fill"},
    )
    _attach_result(
        cfg,
        cmd_id,
        {
            "counts": batch.counts(),
            "summary": str(summary_path),
            "source": "pending_fill",
        },
    )
    return token


def pending_add_apply(
    cfg: Config, *, token: str, collection: str
) -> tuple[bool, str]:
    """Create metadata parents for a reviewed Waiting-from-Discover selection."""
    from ..acronyms import load_acronym_allowlist
    from ..catalogue import open_library
    from ..identity import LibraryFingerprint
    from ..ingest_dois import (
        apply_creates,
        classify_rows,
        default_resolver,
        ingest_tags,
        write_summary,
    )

    review = commands.load_review(cfg, token)
    if review is None or review.get("verb") != "pending_fill_add":
        return False, "unknown token"
    flags = dict(review.get("flags") or {})
    dois = _pending_dois(list(flags.get("dois") or []))
    coll = str(review.get("collection") or collection or "").strip()
    if not coll or not dois:
        return False, "missing pending-add preview data"
    fingerprint_hex = hashlib.sha256(
        f"{coll}|pending_fill|{','.join(dois)}".encode("utf-8")
    ).hexdigest()
    ok, msg = commands.consume_review(cfg, token, fingerprint=fingerprint_hex, keys=None)
    if not ok:
        return False, msg
    backend = open_library(cfg)
    all_items = (
        list(backend.items_in_scope(None))
        if hasattr(backend, "items_in_scope")
        else []
    )
    fingerprint = LibraryFingerprint.from_items(
        all_items,
        scope=cfg.ingest_dedupe_scope,
        collection=coll,
    )
    resolver = default_resolver(cfg.email)
    allowed = load_acronym_allowlist(cfg.state_dir)
    works: dict[str, Any] = {}

    def resolve(doi: str):
        work = resolver(doi)
        if work is not None:
            works[doi] = work
        return work

    batch = classify_rows(dois, fingerprint, resolve=resolve, allowlist=allowed)
    tags = ingest_tags(
        cli_tags=[],
        default_tags=cfg.ingest_default_tags,
        from_file=None,
    )
    apply_creates(backend, batch, coll, works=works, tags=tags, allowlist=allowed)
    write_summary(cfg.state_dir, coll, batch)
    flush = getattr(backend, "flush", None)
    if callable(flush):
        flush()
    return True, ""
