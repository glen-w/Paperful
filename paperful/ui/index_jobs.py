"""Index / ask / RAG long jobs for the workbench GUI."""

from __future__ import annotations

from typing import Any

from ..config import Config
from . import commands, jobs

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
    if jobs.ask_turn_fn is not None:
        result = jobs.ask_turn_fn(
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
    if jobs.rag_ingest_fn is not None:
        result = jobs.rag_ingest_fn(
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
    if jobs.ask_batch_fn is not None:
        result = jobs.ask_batch_fn(
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
    if jobs.rag_questions_fn is not None:
        result = jobs.rag_questions_fn(
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
    if jobs.rag_answered_fn is not None:
        result = jobs.rag_answered_fn(
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
    if jobs.summarize_fn is not None:
        result = jobs.summarize_fn(
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
    if jobs.synthesize_fn is not None:
        result = jobs.synthesize_fn(
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


