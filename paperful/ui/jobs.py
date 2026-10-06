"""Workbench job runners (only module that invokes CLI-equivalent fetch/grow)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from ..config import Config
from ..store import Manifest
from . import commands
from .pages import scope_fingerprint, wanted_rows

# Test hooks
run_fetch_fn: Callable[..., None] | None = None
attach_fn: Callable[..., None] | None = None
snowball_search_fn: Callable[..., Any] | None = None
snowball_search_calls: list[dict[str, Any]] = []
snowball_apply_fn: Callable[..., Any] | None = None
authorwatch_run_fn: Callable[..., Any] | None = None
authorwatch_apply_fn: Callable[..., Any] | None = None
ask_turn_fn: Callable[..., dict[str, Any]] | None = None
noop_sleep: float = 0.05


def run_noop(cfg: Config, cmd_id: str) -> None:
    time.sleep(noop_sleep)


def _quiet_console() -> Console:
    return Console(quiet=True, file=None)


def _load_scope_items(cfg: Config, collection: str) -> tuple[list[Any], Manifest]:
    from ..catalogue import open_library
    from ..library import LibraryError
    from ..scope import ScopeError, load_scope

    manifest = Manifest(cfg.manifest_path)
    if not collection:
        return [], manifest
    try:
        backend = open_library(cfg)
        loaded = load_scope(backend, collections=[collection], library=False)
        return loaded.items, manifest
    except (LibraryError, ScopeError):
        return [], manifest


def preview_run(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    preset: str,
    keys: list[str] | None,
) -> None:
    items, manifest = _load_scope_items(cfg, collection)
    if keys:
        keyset = set(keys)
        items = [it for it in items if it.key in keyset]
    fp = scope_fingerprint(items, manifest)
    if run_fetch_fn is not None:
        run_fetch_fn(
            cfg,
            collection=[collection] if collection else [],
            library=not collection,
            dry_run=True,
            preset=preset,
            keys=keys,
        )
    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection=collection,
        preset=preset,
        keys=[it.key for it in items],
        fingerprint=fp,
        command_id=cmd_id,
    )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["review_token"] = token
    commands.write_command(cfg, rec)


def grab_run(
    cfg: Config,
    *,
    token: str,
    attach_verified: bool,
) -> tuple[bool, str]:
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    collection = str(review.get("collection") or "")
    preset = str(review.get("preset") or "oa")
    items, manifest = _load_scope_items(cfg, collection)
    keyset = set(review.get("keys") or [])
    items = [it for it in items if it.key in keyset]
    fp = scope_fingerprint(items, manifest)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg
    if run_fetch_fn is not None:
        run_fetch_fn(
            cfg,
            collection=[collection] if collection else [],
            library=not collection,
            dry_run=False,
            preset=preset,
            no_attach=True,
            keys=list(keyset),
        )
    else:
        from ..run_cmd import run_fetch

        run_fetch(
            _quiet_console(),
            cfg,
            collection=[collection] if collection else [],
            library=not collection,
            dry_run=False,
            year_from=None,
            year_to=None,
            item_type=[],
            limit=None,
            no_attach=True,
            retry_failed=None,
            try_all=None,
            sources=None,
            preset=preset,
            scihub=None,
            relogin=False,
            browser_agent=None,
            upgrade_linked=None,
            want_snapshot_upgrade=False,
            strict_pdf_doi=None,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            re_request=False,
            json_out=True,
        )
    if attach_verified:
        _attach_doi_match(cfg, manifest, items)
    return True, ""


def _attach_doi_match(cfg: Config, manifest: Manifest, items: list[Any]) -> None:
    from .verify import file_verification

    keys = []
    for item in items:
        rec = manifest.records.get(item.key)
        ver = file_verification(rec, item_doi=item.doi)
        if ver["state"] == "doi_match":
            keys.append(item.key)
    if not keys:
        return
    if attach_fn is not None:
        attach_fn(cfg, keys=keys)
        return
    from ..catalogue import open_library
    from ..pipeline import Pipeline

    m = Manifest(cfg.manifest_path)
    pending = [r for r in m.pending_attach() if r.itemKey in keys]
    if not pending:
        return
    backend = open_library(cfg)
    pipe = Pipeline(cfg, m, _quiet_console(), attacher=backend)
    for rec in pending:
        pipe.attach_record(rec)


def track_topic(
    cfg: Config,
    cmd_id: str,
    *,
    query: str,
    collection: str,
    direction: str | None = None,
) -> None:
    snowball_search_calls.append(
        {"query": query, "collection": collection, "direction": direction}
    )
    if snowball_search_fn is not None:
        snowball_search_fn(
            cfg, query=query, collection=collection, direction=direction
        )
        return
    from ..snowball.command import SnowballRequest, run_search

    req = SnowballRequest(gate="dry-run", collection=collection)
    if direction:
        req.direction = direction
    run_search(cfg, query.strip(), req, console=_quiet_console())


def repair_preview(cfg: Config, cmd_id: str, *, verb: str, collection: str) -> str:
    from .pages import queue_fingerprint

    fp = queue_fingerprint(cfg, verb)
    return commands.create_review_token(
        cfg,
        verb=verb,
        collection=collection,
        preset="oa",
        keys=[verb],
        fingerprint=fp,
        command_id=cmd_id,
    )


def repair_apply(cfg: Config, *, token: str, overwrite: bool = False) -> tuple[bool, str]:
    from .pages import queue_fingerprint

    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    verb = str(review.get("verb") or "")
    fp = queue_fingerprint(cfg, verb)
    return commands.consume_review(cfg, token, fingerprint=fp, keys=None)


def mirror_preview(cfg: Config, cmd_id: str, *, verb: str, collection: str) -> str:
    import hashlib

    fp = hashlib.sha256(f"{verb}|{collection}".encode("utf-8")).hexdigest()
    return commands.create_review_token(
        cfg,
        verb=verb,
        collection=collection,
        preset="oa",
        keys=[verb],
        fingerprint=fp,
        command_id=cmd_id,
    )


def mirror_apply(cfg: Config, *, token: str, collection: str) -> tuple[bool, str]:
    import hashlib

    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    verb = str(review.get("verb") or "")
    fp = hashlib.sha256(f"{verb}|{collection}".encode("utf-8")).hexdigest()
    return commands.consume_review(cfg, token, fingerprint=fp, keys=None)


def follow_person(
    cfg: Config,
    cmd_id: str,
    *,
    orcid: str,
    list_name: str,
    backfill_from: str | None,
) -> None:
    if authorwatch_run_fn is not None:
        authorwatch_run_fn(cfg, orcid=orcid, list_name=list_name, backfill_from=backfill_from)
        return
    from ..authorwatch import add_person, run_list

    add_person(cfg, list_name, orcid=orcid.strip())
    run_list(
        cfg,
        list_name,
        console=_quiet_console(),
        backfill_from=backfill_from or None,
    )


def discover_apply_snowball(cfg: Config, run_id: str, collection: str) -> None:
    if snowball_apply_fn is not None:
        snowball_apply_fn(cfg, run_id=run_id, collection=collection)
        return
    from ..snowball.command import SnowballRequest, run_apply

    req = SnowballRequest(gate="apply", collection=collection)
    run_apply(cfg, run_id, req, console=_quiet_console())


def discover_apply_authorwatch(cfg: Config, list_name: str, collection: str) -> None:
    if authorwatch_apply_fn is not None:
        authorwatch_apply_fn(cfg, list_name=list_name, collection=collection)
        return
    from ..authorwatch import apply_list

    apply_list(_quiet_console(), cfg, list_name, collection, apply=True)


def ask_turn(
    cfg: Config,
    cmd_id: str,
    *,
    question: str,
    thread_id: str | None,
    collection: str,
    year_from: int | None,
    year_to: int | None,
    focus: str | None,
) -> None:
    if ask_turn_fn is not None:
        result = ask_turn_fn(
            cfg,
            cmd_id,
            question=question,
            thread_id=thread_id,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            focus=focus,
        )
    else:
        from ..rag.ask_turn import run_ask_turn

        result = run_ask_turn(
            cfg,
            question=question,
            thread_id=thread_id,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            focus=focus,
        )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["result"] = result
    commands.write_command(cfg, rec)


def set_snowball_keep(cfg: Config, run_id: str, dois: list[str], keep: bool) -> None:
    import json

    from ..snowball.queue import load_queue

    dest, rows = load_queue(cfg.state_dir, run_id)
    doi_set = {d.strip().lower() for d in dois if d.strip()}
    path = dest / "candidates.jsonl"
    out_lines: list[str] = []
    for row in rows:
        if (row.doi or "").strip().lower() in doi_set:
            row.keep = keep
        out_lines.append(json.dumps(row.to_dict(), ensure_ascii=False))
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
