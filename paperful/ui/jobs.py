"""Workbench job runners (only module that invokes CLI-equivalent fetch/grow)."""

from __future__ import annotations

import time
from typing import Any, Callable

from rich.console import Console

from ..config import Config
from ..store import Manifest
from . import commands
from .pages import scope_fingerprint

# Test hooks
run_fetch_fn: Callable[..., None] | None = None
attach_fn: Callable[..., None] | None = None
snowball_search_fn: Callable[..., Any] | None = None
snowball_search_calls: list[dict[str, Any]] = []
snowball_run_fn: Callable[..., Any] | None = None
snowball_run_calls: list[dict[str, Any]] = []
snowball_apply_fn: Callable[..., Any] | None = None
authorwatch_run_fn: Callable[..., Any] | None = None
authorwatch_apply_fn: Callable[..., Any] | None = None
authorwatch_import_fn: Callable[..., Any] | None = None
ask_turn_fn: Callable[..., dict[str, Any]] | None = None
rag_ingest_fn: Callable[..., dict[str, Any]] | None = None
ask_batch_fn: Callable[..., dict[str, Any]] | None = None
rag_questions_fn: Callable[..., dict[str, Any]] | None = None
rag_answered_fn: Callable[..., dict[str, Any]] | None = None
summarize_fn: Callable[..., dict[str, Any]] | None = None
synthesize_fn: Callable[..., dict[str, Any]] | None = None
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
    flags: dict[str, Any] | None = None,
) -> None:
    flags = dict(flags or {})
    items, manifest = _load_scope_items(cfg, collection)
    if keys:
        keyset = set(keys)
        items = [it for it in items if it.key in keyset]
    year_from = flags.get("year_from")
    year_to = flags.get("year_to")
    item_type = list(flags.get("item_type") or [])
    if year_from is not None or year_to is not None or item_type:
        items = [
            it
            for it in items
            if _item_in_filters(it, year_from=year_from, year_to=year_to, item_type=item_type)
        ]
    fp = scope_fingerprint(items, manifest)
    if run_fetch_fn is not None:
        run_fetch_fn(
            cfg,
            collection=[collection] if collection else [],
            library=not collection,
            dry_run=True,
            preset=preset,
            keys=keys,
            flags=flags,
        )
    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection=collection,
        preset=preset,
        keys=[it.key for it in items],
        fingerprint=fp,
        command_id=cmd_id,
        flags=flags,
    )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["review_token"] = token
    commands.write_command(cfg, rec)


def _item_in_filters(
    item: Any,
    *,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
) -> bool:
    year = getattr(item, "year", None)
    if year_from is not None and year is not None and int(year) < int(year_from):
        return False
    if year_to is not None and year is not None and int(year) > int(year_to):
        return False
    if item_type:
        itype = str(getattr(item, "item_type", None) or getattr(item, "type", "") or "")
        if itype and itype not in item_type:
            return False
    return True


def grab_run(
    cfg: Config,
    *,
    token: str,
) -> tuple[bool, str]:
    """Fetch to out/ only (never attaches to Zotero)."""
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    collection = str(review.get("collection") or "")
    preset = str(review.get("preset") or "oa")
    flags = dict(review.get("flags") or {})
    items, manifest = _load_scope_items(cfg, collection)
    keyset = set(review.get("keys") or [])
    items = [it for it in items if it.key in keyset]
    fp = scope_fingerprint(items, manifest)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg
    item_keys = list(keyset)
    year_from = flags.get("year_from")
    year_to = flags.get("year_to")
    item_type = list(flags.get("item_type") or [])
    limit = flags.get("limit")
    retry_failed = flags.get("retry_failed")
    try_all = flags.get("try_all")
    browser_agent = flags.get("browser_agent")
    upgrade_linked = flags.get("upgrade_linked")
    want_snapshot = bool(flags.get("upgrade_snapshot"))
    htmlpdf = flags.get("htmlpdf")
    if run_fetch_fn is not None:
        run_fetch_fn(
            cfg,
            collection=[collection] if collection else [],
            library=not collection,
            dry_run=False,
            preset=preset,
            no_attach=True,
            item_keys=item_keys,
            flags=flags,
        )
    else:
        from ..run_cmd import run_fetch

        sources = None
        if htmlpdf:
            sources = None  # preset + config; htmlpdf lane follows config/sources
        run_fetch(
            _quiet_console(),
            cfg,
            collection=[collection] if collection else [],
            library=not collection,
            dry_run=False,
            year_from=year_from,
            year_to=year_to,
            item_type=item_type,
            limit=limit,
            no_attach=True,
            retry_failed=True if retry_failed else None,
            try_all=True if try_all else None,
            sources=sources,
            preset=preset,
            scihub=None,
            relogin=False,
            browser_agent=True if browser_agent else None,
            upgrade_linked=True if upgrade_linked else None,
            want_snapshot_upgrade=want_snapshot,
            strict_pdf_doi=None,
            handoff=None,
            include_doi_tabs=False,
            downloads_dir=None,
            re_request=False,
            json_out=True,
            item_keys=item_keys,
        )
    return True, ""


def attach_run(
    cfg: Config,
    *,
    keys: list[str],
    collection: str,
) -> tuple[bool, str]:
    """Attach selected pending PDFs to Zotero (doi_match defaults + hand-ticks)."""
    selected = [k.strip() for k in keys if k and str(k).strip()]
    if not selected:
        return False, "no keys selected"
    items, _manifest = _load_scope_items(cfg, collection)
    keyset = set(selected)
    scoped_keys = [it.key for it in items if it.key in keyset]
    if not scoped_keys:
        return False, "no matching items"
    _attach_keys(cfg, scoped_keys)
    return True, ""


def _attach_keys(cfg: Config, keys: list[str]) -> None:
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
    from .snowball_form import DiscoverTopicPayload

    payload = DiscoverTopicPayload(
        kind="search",
        query=query,
        seeds=[],
        direction=direction,
        depth=None,
        year_from=None,
        year_to=None,
        max_candidates=None,
        per_hop_limit=None,
        or_mode=False,
        hybrid_seeds=None,
    )
    snowball_run(cfg, cmd_id, payload=payload, collection=collection)


def snowball_run(
    cfg: Config,
    cmd_id: str,
    *,
    payload: Any,
    collection: str,
) -> None:
    snowball_run_calls.append(
        {
            "kind": payload.kind,
            "query": payload.query,
            "seeds": list(payload.seeds),
            "collection": collection,
        }
    )
    if snowball_run_fn is not None:
        snowball_run_fn(cfg, cmd_id, payload=payload, collection=collection)
        return
    from ..snowball.command import (
        SnowballError,
        run_collection,
        run_doi,
        run_hybrid,
        run_orcid,
        run_search,
    )
    from .snowball_form import build_request, compose_query, doi_list, orcid_list

    req = build_request(cfg, payload, collection)
    if getattr(payload, "twenty_writeback", None):
        cfg.twenty_writeback_listings = True
    console = _quiet_console()
    kind = payload.kind
    try:
        if kind == "search":
            query = compose_query(payload)
            if not query.strip():
                raise SnowballError("Enter a keyword query.")
            run_search(cfg, query, req, console=console)
        elif kind == "hybrid":
            query = compose_query(payload)
            if not query.strip():
                raise SnowballError("Enter a keyword query for hybrid.")
            run_hybrid(cfg, query, req, console=console)
        elif kind == "doi":
            run_doi(cfg, doi_list(payload), req, console=console)
        elif kind == "orcid":
            run_orcid(cfg, orcid_list(payload), req, console=console)
        elif kind == "collection":
            seed = collection.strip() or (payload.seeds[0] if payload.seeds else "")
            if not seed:
                raise SnowballError("Set the collection chip or a seed collection path.")
            run_collection(cfg, seed, req, console=console)
        else:
            query = compose_query(payload) or payload.query
            run_search(cfg, query, req, console=console)
    except SnowballError as exc:
        rec = commands.read_command(cfg, cmd_id) or {}
        rec["status"] = "failed"
        rec["error"] = str(exc)
        commands.write_command(cfg, rec)
        raise


def repair_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    overwrite: bool = False,
    apply_medium: bool = False,
    surgery: dict[str, bool] | None = None,
) -> None:
    from .repair_mirror_jobs import run_repair_preview

    run_repair_preview(
        cfg,
        cmd_id,
        verb=verb,
        collection=collection,
        overwrite=overwrite,
        apply_medium=apply_medium,
        surgery=surgery,
    )


def repair_apply(
    cfg: Config,
    *,
    token: str,
    overwrite: bool = False,
    apply_medium: bool = False,
    surgery: dict[str, bool] | None = None,
) -> tuple[bool, str]:
    from .repair_mirror_jobs import run_repair_apply

    ok, msg, _summary = run_repair_apply(
        cfg,
        token=token,
        overwrite=overwrite,
        apply_medium=apply_medium,
        surgery=surgery,
    )
    return ok, msg


def mirror_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    pdfs: str = "lazy",
    accept_gone: bool = False,
) -> None:
    from .repair_mirror_jobs import run_mirror_preview

    run_mirror_preview(
        cfg,
        cmd_id,
        verb=verb,
        collection=collection,
        pdfs=pdfs,
        accept_gone=accept_gone,
    )


def mirror_apply(cfg: Config, *, token: str, collection: str) -> tuple[bool, str]:
    from .repair_mirror_jobs import run_mirror_apply

    ok, msg, _summary = run_mirror_apply(cfg, token=token, collection=collection)
    return ok, msg


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


def _snowball_apply_fingerprint(cfg: Config, run_id: str, collection: str) -> str:
    import hashlib
    import json

    keeps: list[str] = []
    path = cfg.state_dir / "snowball" / run_id / "candidates.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if data.get("keep") is False:
                continue
            doi = str(data.get("doi") or "")
            if doi:
                keeps.append(doi)
    keeps.sort()
    return hashlib.sha256(
        f"snowball|{run_id}|{collection}|{','.join(keeps)}".encode()
    ).hexdigest()


def _authorwatch_apply_fingerprint(cfg: Config, list_name: str, collection: str) -> str:
    import hashlib

    from ..authorwatch import inbox_count

    n = inbox_count(cfg, list_name)
    return hashlib.sha256(
        f"authorwatch|{list_name}|{collection}|{n}".encode()
    ).hexdigest()


def discover_apply_preview(
    cfg: Config,
    cmd_id: str,
    *,
    kind: str,
    run_id: str,
    list_name: str,
    collection: str,
) -> str:
    if kind == "authorwatch":
        fp = _authorwatch_apply_fingerprint(cfg, list_name, collection)
        keys = [list_name]
        verb = "authorwatch_apply"
    else:
        fp = _snowball_apply_fingerprint(cfg, run_id, collection)
        keys = [run_id]
        verb = "snowball_apply"
    token = commands.create_review_token(
        cfg,
        verb=verb,
        collection=collection,
        preset="oa",
        keys=keys,
        fingerprint=fp,
        command_id=cmd_id,
    )
    _attach_result(cfg, cmd_id, {"review_token": token, "kind": kind})
    return token


def discover_apply_consume(
    cfg: Config,
    *,
    token: str,
    kind: str,
    run_id: str,
    list_name: str,
    collection: str,
) -> tuple[bool, str]:
    if kind == "authorwatch":
        fp = _authorwatch_apply_fingerprint(cfg, list_name, collection)
        keys = [list_name]
    else:
        fp = _snowball_apply_fingerprint(cfg, run_id, collection)
        keys = [run_id]
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=keys)
    if not ok:
        return False, msg
    if kind == "authorwatch":
        discover_apply_authorwatch(cfg, list_name, collection)
    else:
        discover_apply_snowball(cfg, run_id, collection)
    return True, ""


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

    apply_list(cfg, list_name, collection, console=_quiet_console(), apply=True)


def authorwatch_suggest(
    cfg: Config,
    *,
    list_name: str,
    collection: str,
    method: str,
    limit: int,
) -> None:
    from ..authorwatch_suggest import suggest_people

    suggest_people(
        cfg,
        list_name,
        collection=collection,
        method=method,
        limit=limit,
    )


def authorwatch_accept(
    cfg: Config,
    *,
    list_name: str,
    suggestion_ids: list[str],
    seed_from: str | None,
) -> None:
    from ..authorwatch import accept_suggestions, run_list

    accept_suggestions(cfg, list_name, ids=set(suggestion_ids))
    if seed_from:
        run_list(
            cfg,
            list_name,
            console=_quiet_console(),
            backfill_from=seed_from,
        )


def authorwatch_import(
    cfg: Config,
    *,
    list_name: str,
    path: Any,
    source: str,
) -> None:
    if authorwatch_import_fn is not None:
        authorwatch_import_fn(cfg, list_name=list_name, path=path, source=source)
        return
    from ..authorwatch import import_file

    import_file(cfg, list_name, path=path, source=source, resolve=False)


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
    top_k: int | None = None,
    item_keys: list[str] | None = None,
    item_types: frozenset[str] | None = None,
    prompt_path: str | None = None,
    prompt_text: str | None = None,
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
            top_k=top_k,
            item_keys=item_keys,
            item_types=item_types,
            prompt_path=prompt_path,
            prompt_text=prompt_text,
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
            top_k=top_k,
            item_keys=item_keys,
            item_types=item_types,
            prompt_path=prompt_path,
            prompt_text=prompt_text,
        )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["result"] = result
    commands.write_command(cfg, rec)


def _attach_result(cfg: Config, cmd_id: str, result: dict[str, Any]) -> None:
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["result"] = result
    commands.write_command(cfg, rec)


def rag_ingest(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    year_from: int | None,
    year_to: int | None,
    limit: int | None,
    dry_run: bool,
) -> None:
    if rag_ingest_fn is not None:
        result = rag_ingest_fn(
            cfg,
            cmd_id,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            limit=limit,
            dry_run=dry_run,
        )
        _attach_result(cfg, cmd_id, result)
        return
    if not cfg.rag_enabled:
        raise ValueError("rag.enabled is false in config.toml")
    from ..rag.ingest import ingest_entries, select_entries

    collections = [collection] if collection.strip() else None
    entries = select_entries(
        cfg,
        collections=collections,
        year_from=year_from,
        year_to=year_to,
    )
    embedder = None
    if not dry_run:
        from ..llm.preflight import validate_embedder

        embedder = validate_embedder(cfg)
    whole_mirror = not (collection or "").strip() and year_from is None and year_to is None
    batch = ingest_entries(
        cfg,
        entries,
        dry_run=dry_run,
        prune=whole_mirror and limit is None,
        limit=limit,
        embedder=embedder,
    )
    _attach_result(
        cfg,
        cmd_id,
        {
            "dry_run": dry_run,
            "scope": collection or "library",
            "summary": batch.summary(),
        },
    )


def ask_batch(
    cfg: Config,
    cmd_id: str,
    *,
    questions: list[str],
    collection: str,
    year_from: int | None,
    year_to: int | None,
    focus: str | None,
    dest: str,
    apply: bool,
    top_k: int | None = None,
    item_keys: list[str] | None = None,
    item_types: frozenset[str] | None = None,
    prompt_path: str | None = None,
    prompt_text: str | None = None,
    force: bool = False,
) -> None:
    if ask_batch_fn is not None:
        result = ask_batch_fn(
            cfg,
            cmd_id,
            questions=questions,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            focus=focus,
            dest=dest,
            apply=apply,
            top_k=top_k,
            item_keys=item_keys,
            item_types=item_types,
            prompt_path=prompt_path,
            prompt_text=prompt_text,
            force=force,
        )
        _attach_result(cfg, cmd_id, result)
        return
    from ..config import wants_zotero
    from ..llm import get_client
    from ..llm.preflight import validate_embedder, validate_llm_for_ask
    from ..rag.batch import run_batch, write_pack
    from ..rag.index import Index, ledger_path
    from ..rag.ledger import Ledger
    from ..rag.prompt import parse_focus
    from ..rag.retrieve import scope_keys

    validate_llm_for_ask(cfg)
    focus_name = parse_focus(focus if focus is not None else cfg.rag_focus)
    index = Index.open(cfg)
    ledger = Ledger(ledger_path(cfg))
    coll = (collection or "").strip()
    keys = scope_keys(
        ledger,
        collections=[coll] if coll else None,
        item_keys=item_keys or (),
        year_from=year_from,
        year_to=year_to,
        item_types=item_types,
    )
    pack = run_batch(
        cfg,
        questions,
        keys=keys,
        focus=focus_name,
        prompt_path=prompt_path,
        prompt_text=prompt_text,
        k=top_k,
        force=force,
        scope={
            "collections": [coll] if coll else [],
            "item": list(item_keys or []),
            "year_from": year_from,
            "year_to": year_to,
        },
        client=get_client(cfg),
        embedder=validate_embedder(cfg),
        index=index,
        ledger=ledger,
    )
    folder = write_pack(cfg, pack)
    note = False
    if apply and wants_zotero(dest) and collection.strip():
        from ..library import get_backend
        from ..notehtml import wrap
        from ..summarize import to_note_html

        backend = get_backend(cfg)
        body = (folder / "answers.md").read_text(encoding="utf-8")
        html = wrap(
            to_note_html(body),
            note_type="review",
            verb="ask",
            model=pack.model,
        )
        target = backend.resolve_collection(collection)
        backend.create_or_update_collection_note(target.key, html, "paperful-ask-batch")
        note = True
    _attach_result(
        cfg,
        cmd_id,
        {
            "stamp": pack.stamp,
            "pack": str(folder),
            "questions": pack.questions,
            "answered": pack.answered,
            "skipped": pack.skipped,
            "failed": pack.failed,
            "focus": pack.focus,
            "note": note,
        },
    )


def rag_questions(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    whole_library: bool,
    year_from: int | None,
    year_to: int | None,
    item_keys: list[str] | None,
    item_types: frozenset[str] | None,
    use_llm: bool,
    limit: int | None,
    dry_run: bool,
) -> None:
    if rag_questions_fn is not None:
        result = rag_questions_fn(
            cfg,
            cmd_id,
            collection=collection,
            whole_library=whole_library,
            year_from=year_from,
            year_to=year_to,
            item_keys=item_keys,
            item_types=item_types,
            use_llm=use_llm,
            limit=limit,
            dry_run=dry_run,
        )
        _attach_result(cfg, cmd_id, result)
        return
    if not cfg.rag_enabled:
        raise ValueError("rag.enabled is false")
    from ..llm import get_client
    from ..llm.preflight import validate_llm_for_ask
    from ..rag.index import ledger_path
    from ..rag.ledger import Ledger
    from ..rag.questions import extract_scope, write_item

    coll = (collection or "").strip()
    keys = item_keys or []
    if not coll and not keys and not whole_library:
        raise ValueError("scope required")
    if whole_library and not coll:
        collections: list[str] | None = None
    elif coll:
        collections = [coll]
    else:
        collections = []
    client = None
    if use_llm:
        validate_llm_for_ask(cfg)
        client = get_client(cfg)
    ledger = Ledger(ledger_path(cfg))
    items = extract_scope(
        cfg,
        ledger=ledger,
        collections=collections,
        item_keys=keys,
        year_from=year_from,
        year_to=year_to,
        item_types=item_types,
        use_llm=use_llm,
        client=client,
        limit=limit,
    )
    total_q = sum(len(it.questions) for it in items)
    if not dry_run:
        for it in items:
            write_item(cfg, it)
    _attach_result(
        cfg,
        cmd_id,
        {
            "dry_run": dry_run,
            "items": len(items),
            "questions": total_q,
            "llm": use_llm,
        },
    )


def rag_answered(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    year_from: int | None,
    year_to: int | None,
    item_keys: list[str] | None,
    item_types: frozenset[str] | None,
    questions: list[tuple[str, str, int | None]],
    after_item: str | None,
    top_k: int | None,
    force: bool,
) -> None:
    if rag_answered_fn is not None:
        result = rag_answered_fn(
            cfg,
            cmd_id,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            item_keys=item_keys,
            item_types=item_types,
            questions=questions,
            after_item=after_item,
            top_k=top_k,
            force=force,
        )
        _attach_result(cfg, cmd_id, result)
        return
    from ..llm import get_client
    from ..llm.preflight import validate_embedder, validate_llm_for_ask
    from ..rag.answered import run_answered, write_pack
    from ..rag.index import Index, ledger_path
    from ..rag.ledger import Ledger
    from ..rag.retrieve import scope_keys

    validate_llm_for_ask(cfg)
    coll = (collection or "").strip()
    index = Index.open(cfg)
    ledger = Ledger(ledger_path(cfg))
    keys = scope_keys(
        ledger,
        collections=[coll] if coll else None,
        item_keys=item_keys or (),
        year_from=year_from,
        year_to=year_to,
        item_types=item_types,
    )
    pack = run_answered(
        cfg,
        questions,
        keys=keys,
        after_item=(after_item or "").strip() or None,
        k=top_k,
        force=force,
        scope={
            "collections": [coll] if coll else [],
            "item": list(item_keys or []),
            "year_from": year_from,
            "year_to": year_to,
            "after_item": after_item,
        },
        client=get_client(cfg),
        embedder=validate_embedder(cfg),
        index=index,
        ledger=ledger,
    )
    folder = write_pack(cfg, pack)
    _attach_result(
        cfg,
        cmd_id,
        {
            "stamp": pack.stamp,
            "pack": str(folder),
            "questions": pack.questions,
            "answered": pack.answered,
            "partial": pack.partial,
            "not_found": pack.not_found,
            "failed": pack.failed,
        },
    )


def summarize(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    year_from: int | None,
    year_to: int | None,
    limit: int | None,
    max_new: int | None,
    dest: str,
    order: str,
    force: bool,
    item_keys: list[str] | None = None,
) -> None:
    if summarize_fn is not None:
        result = summarize_fn(
            cfg,
            cmd_id,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            limit=limit,
            max_new=max_new,
            dest=dest,
            order=order,
            force=force,
            item_keys=item_keys,
        )
        if result is not None:
            _attach_result(cfg, cmd_id, result)
        return
    from ..catalogue import open_library
    from ..llm.preflight import validate_llm_for_verb
    from ..scope import load_scope
    from ..store import Manifest
    from ..summarize import order_items, summarize_items

    validate_llm_for_verb(cfg)
    backend = open_library(cfg)
    loaded = load_scope(
        backend,
        collections=[collection] if collection.strip() else [],
        library=not bool(collection.strip()),
        year_from=year_from,
        year_to=year_to,
        pdfs_only=True,
    )
    items = order_items(loaded.items, order)
    if item_keys:
        keyset = set(item_keys)
        items = [it for it in items if it.key in keyset]
    if limit:
        items = items[:limit]
    if not items:
        _attach_result(cfg, cmd_id, {"error": "no items", "queued": 0})
        rec = commands.read_command(cfg, cmd_id) or {}
        rec["status"] = "failed"
        rec["error"] = "no items in scope"
        commands.write_command(cfg, rec)
        return
    batch = summarize_items(
        cfg,
        items,
        Manifest(cfg.manifest_path),
        backend,
        dest=dest,
        force=force,
        max_new=max_new,
    )
    if batch.fatal:
        raise ValueError(batch.fatal)
    _attach_result(
        cfg,
        cmd_id,
        {
            "summarized": batch.summarized,
            "failed": batch.failed,
            "skipped": batch.skipped,
            "not_reached": batch.not_reached,
            "dest": dest,
            "scope": loaded.label,
            "queued": len(items),
        },
    )


def synthesize(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    year_from: int | None,
    year_to: int | None,
    limit: int | None,
    dest: str,
    dry_run: bool,
    force: bool,
) -> None:
    if synthesize_fn is not None:
        result = synthesize_fn(
            cfg,
            cmd_id,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            limit=limit,
            dest=dest,
            dry_run=dry_run,
            force=force,
        )
        _attach_result(cfg, cmd_id, result)
        return
    from ..catalogue import open_library
    from ..config import wants_disk, wants_zotero
    from ..llm import get_client
    from ..llm.preflight import validate_llm_for_verb
    from ..scope import load_scope
    from ..synthesize import (
        prepare_synthesis,
        report_is_current,
        write_synthesis,
    )

    validate_llm_for_verb(cfg)
    if wants_zotero(dest) and not collection.strip() and not dry_run:
        raise ValueError("Pass a collection to file the Zotero note, or dest=disk.")
    backend = open_library(cfg)
    loaded = load_scope(
        backend,
        collections=[collection] if collection.strip() else [],
        library=not bool(collection.strip()),
        year_from=year_from,
        year_to=year_to,
    )
    items = list(loaded.items)
    items.sort(
        key=lambda it: (it.year or 9999, (it.first_author or "").lower(), it.key)
    )
    if limit:
        items = items[:limit]
    targets = []
    if wants_zotero(dest) and collection.strip():
        targets = [backend.resolve_collection(collection)]
    slug_parts: list[str] = []
    if not collection.strip():
        slug_parts.append("library")
    else:
        slug_parts.append(collection)
    if year_from is not None or year_to is not None:
        slug_parts.append(f"{year_from or ''}-{year_to or ''}")
    prepared = prepare_synthesis(cfg, items, backend, slug_parts)
    on_disk = sum(1 for src in prepared.sources if src.origin == "disk")
    from_note = sum(1 for src in prepared.sources if src.origin == "note")
    if dry_run:
        _attach_result(
            cfg,
            cmd_id,
            {
                "dry_run": True,
                "slug": prepared.slug,
                "sources_disk": on_disk,
                "sources_note": from_note,
                "missing": len(prepared.missing),
                "chunks": len(prepared.chunks),
                "html_path": str(cfg.reports_dir / f"{prepared.slug}.html")
                if wants_disk(dest)
                else "",
            },
        )
        return
    if not prepared.sources:
        _attach_result(
            cfg,
            cmd_id,
            {
                "dry_run": False,
                "slug": prepared.slug,
                "sources_disk": 0,
                "sources_note": 0,
                "missing": len(prepared.missing),
                "skipped": "no_summaries",
            },
        )
        return
    if not force and report_is_current(cfg, prepared.slug, prepared.sources, dest=dest):
        _attach_result(
            cfg,
            cmd_id,
            {
                "dry_run": False,
                "slug": prepared.slug,
                "sources_disk": on_disk,
                "sources_note": from_note,
                "skipped": "current",
            },
        )
        return
    written = write_synthesis(
        cfg,
        sources=prepared.sources,
        missing=prepared.missing,
        scope=loaded.label,
        slug=prepared.slug,
        dest=dest,
        targets=targets,
        backend=backend,
        client=get_client(cfg),
    )
    _attach_result(
        cfg,
        cmd_id,
        {
            "dry_run": False,
            "slug": prepared.slug,
            "chunks": written.n_chunks,
            "sources_disk": on_disk,
            "sources_note": from_note,
            "missing": len(prepared.missing),
        },
    )


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
