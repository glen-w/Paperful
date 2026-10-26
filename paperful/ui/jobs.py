"""Workbench job runners (only module that invokes CLI-equivalent fetch/grow)."""

from __future__ import annotations

import time
from typing import Any, Callable

from rich.console import Console

from ..config import Config
from ..store import Manifest
from . import commands
from .pages import scope_fingerprint

# Test hooks (index_jobs reads these names from this module)
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
extract_sections_fn: Callable[..., dict[str, Any]] | None = None
summarize_fn: Callable[..., dict[str, Any]] | None = None
synthesize_fn: Callable[..., dict[str, Any]] | None = None
critique_fn: Callable[..., dict[str, Any]] | None = None
noop_sleep: float = 0.05

from .index_jobs import (
    ask_batch,
    ask_turn,
    rag_answered,
    rag_ingest,
    rag_questions,
    extract_sections,
    summarize,
    synthesize,
    _attach_result,
)


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


def missing_items(cfg: Config, items: list[Any], manifest: Manifest) -> list[Any]:
    """Items on the Wanted Missing tab (the list Preview/Grab mean by "all")."""
    from .pages import wanted_rows

    missing_keys = {row["key"] for row in wanted_rows(cfg, items, manifest)["missing"]}
    return [it for it in items if it.key in missing_keys]


def scope_for_fetch(
    cfg: Config,
    collection: str,
    keys: list[str] | None,
    flags: dict[str, Any] | None,
) -> tuple[list[Any], Manifest]:
    """Rows a Preview or Grab should consider.

    Ticked keys win. With no ticks, the scope is the Missing list, then any
    year/type flags. Have and Held rows are not fetched unless ticked.
    """
    flags = dict(flags or {})
    items, manifest = _load_scope_items(cfg, collection)
    if keys:
        keyset = {k for k in keys if k}
        items = [it for it in items if it.key in keyset]
    else:
        items = missing_items(cfg, items, manifest)
    year_from = flags.get("year_from")
    year_to = flags.get("year_to")
    item_type = list(flags.get("item_type") or [])
    if year_from is not None or year_to is not None or item_type:
        items = [
            it
            for it in items
            if _item_in_filters(it, year_from=year_from, year_to=year_to, item_type=item_type)
        ]
    return items, manifest


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
    items, manifest = scope_for_fetch(cfg, collection, keys, flags)
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


def _flags_match(stored: dict[str, Any], current: dict[str, Any]) -> bool:
    return dict(stored or {}) == dict(current or {})


def matching_preview(
    cfg: Config,
    *,
    collection: str,
    preset: str,
    posted_keys: list[str],
    flags: dict[str, Any] | None,
    explicit_token: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Find an unconsumed Preview token for this Grab.

    Grab never borrows an Attach, Recover, or other review token. The token's
    keys must be the ticked rows, or the current Missing list when nothing
    is ticked.
    """
    flags = dict(flags or {})
    posted = [k for k in posted_keys if str(k).strip()]

    def _usable(token: str) -> dict[str, Any] | None:
        review = commands.load_review(cfg, token)
        if review is None or review.get("consumed"):
            return None
        if str(review.get("verb") or "") != "preview_run":
            return None
        if str(review.get("collection") or "") != collection:
            return None
        if str(review.get("preset") or "oa") != (preset or "oa"):
            return None
        if not _flags_match(dict(review.get("flags") or {}), flags):
            return None
        return review

    review: dict[str, Any] | None = None
    if explicit_token:
        review = _usable(explicit_token)
    if review is None:
        for rec in commands.list_commands(cfg, limit=30):
            token = str(rec.get("review_token") or "")
            if not token:
                continue
            review = _usable(token)
            if review is not None:
                break
    if review is None:
        return None, "Preview the missing list, or the rows you ticked, before Grab."
    items, _manifest = scope_for_fetch(cfg, collection, posted or None, flags)
    intended = sorted(it.key for it in items)
    if intended != sorted(review.get("keys") or []):
        if posted:
            return None, "Preview the ticked rows before Grab."
        return None, "Preview the missing list before Grab."
    return review, ""


def grab_attaches(cfg: Config) -> bool:
    """True when Settings says Grab should write the library after download."""
    return cfg.ui_attach_mode == "auto"


def grab_run(
    cfg: Config,
    *,
    token: str,
) -> tuple[bool, str]:
    """Fetch into out/. Attach during Grab only when Settings is automatic."""
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    if str(review.get("verb") or "") != "preview_run":
        return False, "preview first"
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
    auto_attach = grab_attaches(cfg)
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
            no_attach=not auto_attach,
            force_attach=auto_attach,
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
            no_attach=not auto_attach,
            force_attach=auto_attach,
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
) -> tuple[bool, str, int]:
    """Attach selected pending PDFs to Zotero (doi_match defaults + hand-ticks)."""
    posted = [k.strip() for k in keys if k and str(k).strip()]
    items, manifest = _load_scope_items(cfg, collection)
    if posted:
        pending = [
            r
            for r in manifest.pending_attach()
            if r.itemKey in set(posted)
        ]
        if not pending:
            return False, "no attachable PDFs for that selection", 0
        scoped_keys = [r.itemKey for r in pending]
    else:
        item_keys = {it.key for it in items}
        pending = [
            r for r in manifest.pending_attach() if r.itemKey in item_keys
        ]
        if not pending:
            return False, "no attachable PDFs", 0
        scoped_keys = [r.itemKey for r in pending]
    n = _attach_keys(cfg, scoped_keys)
    if n == 0:
        return False, "no attachable PDFs", 0
    return True, "", n


def _attach_keys(cfg: Config, keys: list[str]) -> int:
    if not keys:
        return 0
    m = Manifest(cfg.manifest_path)
    pending = [r for r in m.pending_attach() if r.itemKey in keys]
    if not pending:
        return 0
    if attach_fn is not None:
        attach_fn(cfg, keys=[r.itemKey for r in pending])
        return len(pending)
    from ..catalogue import open_library
    from ..pipeline import Pipeline

    backend = open_library(cfg)
    pipe = Pipeline(cfg, m, _quiet_console(), attacher=backend)
    for rec in pending:
        pipe.attach_record(rec)
    return len(pending)


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


def critique(
    cfg: Config,
    cmd_id: str,
    *,
    item_key: str = "",
    staged_path: Any | None = None,
    collection: str = "",
    apply: bool = False,
    llm: bool = False,
    ai_model: bool = False,
    force: bool = False,
    show_dismissed: bool = False,
) -> None:
    if critique_fn is not None:
        result = critique_fn(
            cfg,
            cmd_id,
            item_key=item_key,
            staged_path=staged_path,
            collection=collection,
            apply=apply,
            llm=llm,
            ai_model=ai_model,
            force=force,
            show_dismissed=show_dismissed,
        )
        if result is not None:
            _attach_result(cfg, cmd_id, result)
        return
    import os

    from ..critique import build_critique, note_html
    from ..critique_extract import ExtractError
    from ..llm import get_client
    from ..llm.preflight import validate_llm_for_verb
    from ..llm.validate import LlmConfigError
    from ..pipeline import make_client

    offline = os.environ.get("PAPERFUL_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    backend = None
    target = None
    scope_items: list[Any] = []
    coll = (collection or "").strip()
    key = (item_key or "").strip()
    if key or coll:
        items, _manifest = _load_scope_items(cfg, coll)
        scope_items = items
        if key:
            target = next((it for it in items if it.key == key), None)
            if target is None:
                from ..catalogue import open_library
                from ..scope import load_scope

                try:
                    backend = open_library(cfg)
                    loaded = load_scope(
                        backend, collections=[], library=True, item_keys=[key]
                    )
                    items = loaded.items
                    target = items[0] if items else None
                    if not scope_items:
                        scope_items = items
                except Exception:
                    target = None
        if backend is None and (apply or key):
            try:
                from ..catalogue import open_library

                backend = open_library(cfg)
            except Exception:
                backend = None
    if key and target is None:
        rec = commands.read_command(cfg, cmd_id) or {}
        rec["status"] = "failed"
        rec["error"] = "item not in the mirror / scope"
        commands.write_command(cfg, rec)
        return
    llm_client = None
    use_llm = bool(llm)
    if use_llm:
        try:
            validate_llm_for_verb(cfg)
            llm_client = get_client(cfg)
        except LlmConfigError as exc:
            rec = commands.read_command(cfg, cmd_id) or {}
            rec["status"] = "failed"
            rec["error"] = str(exc)
            commands.write_command(cfg, rec)
            return
    http = None if offline else make_client(cfg)
    try:
        pack = build_critique(
            cfg,
            item=target,
            file_path=staged_path,
            collections=[coll] if coll else None,
            library=not bool(coll),
            dry_run=False,
            use_llm=use_llm,
            use_ai_model=bool(ai_model),
            force=force,
            show_dismissed=show_dismissed,
            offline=offline,
            client=http,
            llm_client=llm_client,
            backend=backend,
            scope_items=scope_items,
            stage_uploads=staged_path is None,
        )
    except (ExtractError, ValueError) as exc:
        rec = commands.read_command(cfg, cmd_id) or {}
        rec["status"] = "failed"
        rec["error"] = str(exc)
        commands.write_command(cfg, rec)
        return
    finally:
        if http is not None:
            http.close()
    applied = 0
    if apply and target is not None and backend is not None and backend.supports_write():
        html = note_html(pack)
        tag = (cfg.critique_tag or "paperful-critique").strip()
        backend.create_or_update_note(target.key, html, tag)
        applied = 1
    counts = pack.get("counts") or {}
    _attach_result(
        cfg,
        cmd_id,
        {
            "pack_dir": pack.get("pack_dir") or "",
            "critique_id": pack.get("critique_id") or "",
            "counts": counts,
            "applied": applied,
            "findings": counts.get("findings", 0),
        },
    )


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

    from .pages import candidate_title_doi

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
            _title, doi = candidate_title_doi(data)
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


def _watch_apply_fingerprint(cfg: Config, watch_name: str, collection: str) -> str:
    import hashlib

    from ..snowball.watch import inbox_count

    n = inbox_count(cfg, watch_name)
    return hashlib.sha256(
        f"watch|{watch_name}|{collection}|{n}".encode()
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
    elif kind in {"watch", "topic"}:
        name = list_name or run_id
        fp = _watch_apply_fingerprint(cfg, name, collection)
        keys = [name]
        verb = "watch_apply"
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
    elif kind in {"watch", "topic"}:
        name = list_name or run_id
        fp = _watch_apply_fingerprint(cfg, name, collection)
        keys = [name]
    else:
        fp = _snowball_apply_fingerprint(cfg, run_id, collection)
        keys = [run_id]
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=keys)
    if not ok:
        return False, msg
    if kind == "authorwatch":
        discover_apply_authorwatch(cfg, list_name, collection)
    elif kind in {"watch", "topic"}:
        discover_apply_watch(cfg, list_name or run_id, collection)
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


def discover_apply_watch(cfg: Config, watch_name: str, collection: str) -> None:
    """Create parents from a topic watch inbox (``snowball watch apply``)."""
    from ..snowball.watch import apply_watch

    apply_watch(
        cfg,
        watch_name,
        collection,
        console=_quiet_console(),
        apply=True,
    )


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


def set_snowball_keep(cfg: Config, run_id: str, dois: list[str], keep: bool) -> None:
    import json

    from ..snowball.queue import load_queue

    dest, rows = load_queue(cfg.state_dir, run_id)
    from ..resolve import doi_key

    doi_set = {k for d in dois if (k := doi_key(d))}
    path = dest / "candidates.jsonl"
    out_lines: list[str] = []
    for row in rows:
        if doi_key(row.ids.get("doi")) in doi_set:
            row.keep = keep
        out_lines.append(json.dumps(row.to_dict(), ensure_ascii=False))
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
