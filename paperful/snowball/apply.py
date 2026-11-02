"""Snowball continue / resume / apply (command.py re-exports the public run_*)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from ..agent_json import EXIT_PARTIAL, batch_exit
from ..config import Config
from ..library import LibraryError
from .candidate import Candidate
from .expand import DEFAULT_DIRECTION, apply_filters, truncate
from .openalex import OpenAlexClient, keyless_limit_message
from .queue import load_queue, write_queue, write_report
from .tally import paint
from .titles import repair_reference_titles

if TYPE_CHECKING:
    from .command import Lookup, PathResult, SnowballRequest

_FROM_COMMAND = (
    "SnowballError",
    "PathResult",
    "Lookup",
    "get_backend",
    "_openalex_client",
    "_library_lookup",
    "_apply_fingerprint_scope",
    "_mark_exists",
    "_version_of",
    "_extra_tags",
    "_title_allowlist",
    "_local_cites",
    "_pdf_mode",
    "fill_pdfs",
    "create_new",
    "_print_fetch_result",
    "_maybe_dedupe_after",
    "_live_tally",
    "_fill_metadata",
    "_backends",
    "_blocked_dois",
    "_fingerprint_rows",
    "_settled_rows",
    "_write_cached_pdfs",
    "_print_table",
    "_open_stop",
    "_touch_stop_summary",
    "_min_cites",
    "_keyword_caps",
    "_stop_params",
)


# Placeholders: rebound from command.py on each call (keeps monkeypatches).
SnowballError = None
PathResult = None
Lookup = None
get_backend = None
_openalex_client = None
_library_lookup = None
_apply_fingerprint_scope = None
_mark_exists = None
_version_of = None
_extra_tags = None
_title_allowlist = None
_local_cites = None
_pdf_mode = None
fill_pdfs = None
create_new = None
_print_fetch_result = None
_maybe_dedupe_after = None
_live_tally = None
_fill_metadata = None
_backends = None
_blocked_dois = None
_fingerprint_rows = None
_settled_rows = None
_write_cached_pdfs = None
_print_table = None
_open_stop = None
_touch_stop_summary = None
_min_cites = None
_keyword_caps = None
_stop_params = None


def _bind_command() -> None:
    from . import command as _command

    g = globals()
    for name in _FROM_COMMAND:
        g[name] = getattr(_command, name)


def run_continue(
    cfg: Config,
    run_id: str,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    gate: str | None = None,
) -> PathResult:
    """Score Keep/Skip on the open hop, then expand one more hop unless a rule fires."""
    _bind_command()
    if not cfg.snowball_enabled:
        raise SnowballError(
            "Snowball is off. Set [snowball] enabled = true in config.toml."
        )
    from .crawl import _dedupe, _expand_hops, _remember_cites_query, _remember_keywords
    from .openalex import short_id
    from .stop import (
        IterationStat,
        append_decisions,
        evaluate,
        load_state,
        parse_stop_params,
        terminating,
        write_state,
    )

    dest = cfg.state_dir / "snowball" / run_id
    state = load_state(dest / "stop.json")
    if state is None:
        raise SnowballError(
            f"Run {run_id} has no stopping rule. It was a one-shot crawl."
        )
    if state.get("stopped_by"):
        console.print(str(state.get("rationale") or state["stopped_by"]))
        return PathResult(dest, 0, summary=state)
    if (dest / "deferred.json").is_file():
        raise SnowballError(
            f"OpenAlex paused this hop. paperful snowball resume {run_id} first, then continue."
        )
    try:
        _, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.") from exc
    hop = max((row.hop for row in rows), default=0)
    batch = [row for row in rows if row.hop == hop and row.status == "new"]
    crawl = dict(state.get("crawl") or {})
    effective_gate = (gate or str(crawl.get("gate") or "dry-run")).strip()
    pending = [row for row in batch if row.keep is None]
    if pending and effective_gate != "auto":
        count = len(pending)
        if count == 1:
            message = f"1 new row at hop {hop} still needs Keep or Skip."
        else:
            message = f"{count} new rows at hop {hop} still need Keep or Skip."
        raise SnowballError(message)
    if effective_gate == "auto":
        for row in pending:
            row.keep = True
    iteration = int(state.get("iteration") or 1)
    history = [
        IterationStat(
            iteration=int(item["iteration"]),
            screened=int(item["screened"]),
            included=int(item["included"]),
        )
        for item in (state.get("history") or [])
        if isinstance(item, dict)
    ]
    included = sum(1 for row in batch if row.keep is True)
    history.append(
        IterationStat(iteration=iteration, screened=len(batch), included=included)
    )
    kept = [
        row
        for row in batch
        if row.keep is True and (row.ids.get("openalex") or row.ids.get("doi"))
    ]
    ceiling = int(state.get("depth_ceiling") or 0)
    next_hop = hop + 1
    max_candidates = int(crawl.get("max_candidates") or 0)
    if max_candidates <= 0:
        room = -1
    else:
        used = sum(1 for row in rows if row.status in {"new", "exists"})
        room = max_candidates - used
    try:
        params = parse_stop_params(
            rule=state.get("rule") or "off",
            eps=state.get("eps", 0.01),
            k=state.get("k", 2),
            tau=state.get("tau", 0.95),
            min_points=state.get("min_points", 4),
            max_screened=state.get("max_screened", 0),
        )
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    decisions = evaluate(
        history,
        params,
        frontier_empty=not kept,
        next_hop=next_hop,
        depth_ceiling=ceiling,
        candidate_room=room,
    )
    append_decisions(dest / "stops.jsonl", iteration, decisions)
    state["history"] = [
        {
            "iteration": item.iteration,
            "screened": item.screened,
            "included": item.included,
        }
        for item in history
    ]
    chosen = terminating(decisions, params.rule)
    if chosen is not None:
        state["stopped_by"] = chosen.rule
        state["rationale"] = chosen.rationale
        state["awaiting_labels"] = False
        write_state(dest / "stop.json", state)
        write_queue(
            cfg.state_dir,
            run_id,
            rows,
            client or _openalex_client(cfg),
            library_unread=False,
        )
        _touch_stop_summary(dest, state)
        console.print(chosen.rationale)
        return PathResult(
            dest, 0, summary={"stopped_by": chosen.rule, "rationale": chosen.rationale}
        )

    oa = client or _openalex_client(cfg, sleep_s=0.0 if client else 0.15)
    _remember_keywords(
        oa,
        keyword_limit=int(crawl.get("keyword_limit") or 3),
        keyword_hop_limit=int(crawl.get("keyword_hop_limit") or 50),
        keyword_min_score=float(crawl.get("keyword_min_score") or 0.0),
    )
    _remember_cites_query(oa, str(crawl.get("cites_query") or ""))
    ids = [short_id(str(row.ids.get("openalex") or "")) for row in kept]
    ids = [item for item in ids if item]
    works = oa.works_by_ids(ids) if ids else []
    if not works:
        for row in kept:
            doi = (row.ids.get("doi") or "").strip()
            if not doi:
                continue
            try:
                work = oa.work_by_doi(doi)
            except Exception:
                work = None
            if work:
                works.append(work)
    seen = {short_id(str(row.ids.get("openalex") or "")) for row in rows}
    seen.discard("")
    seed = dict(crawl.get("seed") or {"type": "stop", "value": run_id})
    direction = str(crawl.get("direction") or DEFAULT_DIRECTION)
    new_rows = _expand_hops(
        oa,
        works,
        run_id=run_id,
        seed=seed,
        gate=effective_gate,
        depth=ceiling,
        direction=direction,
        per_hop_limit=int(crawl.get("per_hop_limit") or 50),
        year_from=crawl.get("year_from"),
        year_to=crawl.get("year_to"),
        why_prefix="kept",
        min_seed_citations=int(crawl.get("min_seed_citations") or 0),
        per_hop_rank=str(crawl.get("per_hop_rank") or "most-cited"),
        hop_start=next_hop,
        hop_end=next_hop,
        seen_oa=seen,
    )
    new_rows = apply_filters(
        new_rows,
        year_from=crawl.get("year_from"),
        year_to=crawl.get("year_to"),
        types=tuple(crawl.get("types") or ()),
        oa_only=bool(crawl.get("oa_only")),
        venue_include=tuple(crawl.get("venue_include") or ()),
        venue_exclude=tuple(crawl.get("venue_exclude") or ()),
        languages=tuple(crawl.get("languages") or ()),
        study_designs=tuple(crawl.get("study_designs") or ()),
        listed_in=tuple(crawl.get("listed_in") or ()),
    )
    if lookup is not None:
        _mark_exists(new_rows, lookup)
    elif backend is not None:
        try:
            finder = _library_lookup(backend, scope="library", collection="")
            _mark_exists(new_rows, finder)
        except Exception:
            pass
    if max_candidates > 0:
        new_rows = truncate(new_rows, max(0, room))
    merged = _dedupe(rows + new_rows)
    state["iteration"] = iteration + 1
    state["paused"] = "budget" if oa.deferred else None
    state["awaiting_labels"] = oa.deferred is None and bool(new_rows)
    if oa.deferred is None and not new_rows:
        state["stopped_by"] = "exhaustion"
        state["rationale"] = (
            f"Citation searching stopped after iteration {iteration}: "
            "the next hop returned no new works."
        )
        state["awaiting_labels"] = False
    write_state(dest / "stop.json", state)
    write_queue(cfg.state_dir, run_id, merged, oa, library_unread=False)
    _touch_stop_summary(dest, state)
    if oa.deferred:
        console.print(
            f"[yellow]Partial hop kept[/] · paperful snowball resume {run_id}"
        )
        return PathResult(dest, EXIT_PARTIAL, summary=state)
    if state.get("stopped_by"):
        console.print(str(state["rationale"]))
        return PathResult(dest, 0, summary=state)
    console.print(
        f"hop {next_hop} · {len(new_rows)} new rows · "
        f"Keep or Skip, then: paperful snowball continue {run_id}"
    )
    return PathResult(dest, 0, summary=state)


def run_resume(
    cfg: Config,
    run_id: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    backend: Any = None,
) -> PathResult:
    """Continue a crawl that stopped because the OpenAlex daily budget was spent."""
    _bind_command()
    if not cfg.snowball_enabled:
        raise SnowballError(
            "Snowball is off. Set [snowball] enabled = true in config.toml."
        )
    import json
    from datetime import datetime, timezone

    from .crawl import _dedupe, continue_deferred

    dest = cfg.state_dir / "snowball" / run_id
    path = dest / "deferred.json"
    if not path.is_file():
        if not (dest / "candidates.jsonl").is_file():
            raise SnowballError(f"No snowball queue for run {run_id!r}.")
        return _resume_saved_queue(
            cfg, run_id, request, console=console, backend=backend
        )
    deferred = json.loads(path.read_text(encoding="utf-8"))
    reset_at = deferred.get("reset_at")
    if isinstance(reset_at, str) and reset_at:
        when = datetime.fromisoformat(reset_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        key_ready = bool(
            (client.api_key if client is not None else "")
            or os.environ.get("OPENALEX_API_KEY")
        )
        if when > datetime.now(timezone.utc) and (
            deferred.get("keyed") or not key_ready
        ):
            if deferred.get("keyed"):
                console.print(
                    f"[yellow]OpenAlex budget still spent[/] · resume after {reset_at}"
                )
            else:
                console.print(
                    "[yellow]"
                    + keyless_limit_message(has_key=False, reset_at=reset_at)
                    + "[/]"
                )
            return PathResult(dest, 1)
    try:
        _, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.") from exc
    oa = client or _openalex_client(cfg, sleep_s=0.15)
    tally = _live_tally(console)
    oa.tally = tally
    oa.progress = lambda message: console.print(paint(message))
    tally.start()
    paused: dict[str, list[str]] = {}
    if deferred.get("kind") == "fill":
        known = {row.identity for row in rows}
        rows, paused = _fill_metadata(
            cfg,
            request,
            rows,
            backends=_backends(cfg, request),
            console=console,
            live=client is None,
            crossref_getter=None,
            s2_getter=None,
            per_hop_limit=int(
                deferred.get("per_hop_limit") or cfg.snowball_per_hop_limit
            ),
            direction=str(
                deferred.get("direction") or request.direction or DEFAULT_DIRECTION
            ),
            tally=tally,
            expand_neighbors=bool(deferred.get("expand_neighbors", True)),
        )
        repair_reference_titles(rows, oa, tally=tally)
        if paused:
            oa.deferred = {
                **deferred,
                "backend": next(iter(paused)),
                "remaining_ids": sorted(_blocked_dois(paused)),
                "pauses": paused,
                "error": next(iter(paused)),
            }
        added = [row for row in rows if row.identity not in known]
        merged = rows
    else:
        added = continue_deferred(oa, deferred)
        merged = _dedupe(list(rows) + added)
    lib_fp = backend
    unread = False
    try:
        lib_fp, unread = _fingerprint_rows(
            cfg, request, merged, backend=backend, console=console
        )
    except SnowballError:
        raise
    write_queue(
        cfg.state_dir,
        run_id,
        merged,
        oa,
        library_unread=unread,
        meta={"resumed": True, "resume_added": len(added)},
    )
    if oa.deferred is None and path.is_file():
        path.unlink()
    _print_table(console, added)
    if oa.deferred:
        when = oa.deferred.get("reset_at") or "the daily reset"
        console.print(
            f"[yellow]OpenAlex budget spent[/] · resume after {when}: "
            f"paperful snowball resume {run_id}"
        )
        tally.stop()
        return PathResult(dest, 1)
    console.print(f"resumed · {len(added)} rows added")
    tally.stop()
    if request.gate == "auto" and request.collection.strip() and added:
        lib = backend or lib_fp
        try:
            lib = lib or get_backend(cfg)
            by_id = {row.identity: row for row in merged if row.identity}
            settled = [
                by_id[row.identity]
                for row in added
                if row.identity in by_id
                and by_id[row.identity].status == "new"
                and by_id[row.identity].keep is not False
            ]
            settled = _settled_rows(settled, _blocked_dois(paused))
            items, _counts = create_new(
                lib,
                settled,
                request.collection,
                tag_prefix=request.tag_prefix or cfg.snowball_tag_prefix,
                extra_tags=_extra_tags(cfg, request),
                note_provenance=cfg.snowball_note_provenance
                if request.note_provenance is None
                else request.note_provenance,
                remarks_surface=cfg.remarks_surface,
                local_cites=_local_cites(cfg, lib, request.collection),
                console=console,
                allowlist=_title_allowlist(cfg),
            )
            _write_cached_pdfs(cfg, items, settled)
            if _pdf_mode(request) != "off" and items:
                fill_pdfs(cfg, lib, items, console, mode=_pdf_mode(request))
            _maybe_dedupe_after(cfg, request, lib, request.collection, console)
        except (LibraryError, SnowballError) as exc:
            raise SnowballError(str(exc)) from exc
    return PathResult(dest, 0)


def _resume_saved_queue(
    cfg: Config,
    run_id: str,
    request: SnowballRequest,
    *,
    console: Console,
    backend: Any = None,
) -> PathResult:
    """Continue create and PDF fetch from a finished queue. Does not search again."""
    _bind_command()
    from ..store import Manifest

    from .ingest import create_new, fill_pdfs, pending_pdf_items

    dest, rows = load_queue(cfg.state_dir, run_id)
    console.print(
        f"queue on disk · {len(rows)} rows · continuing without another OpenAlex search"
    )
    mode = _pdf_mode(request)
    if request.gate != "auto" or not request.collection.strip():
        if mode != "off":
            console.print("[yellow]fetch_pdfs needs --gate auto and -C to continue[/]")
        return PathResult(dest, 0)
    lib = backend
    try:
        lib = lib or get_backend(cfg)
    except Exception as exc:
        raise SnowballError(
            f"Library was not read. Refusing to create items. {exc}"
        ) from exc
    lookup = _library_lookup(
        lib, scope=_apply_fingerprint_scope(request), collection=request.collection
    )
    _mark_exists(rows, lookup)
    creatable = [row for row in rows if row.status == "new" and row.keep is not False]
    items: list[Any] = []
    failed = 0
    if creatable:
        items, counts = create_new(
            lib,
            creatable,
            request.collection,
            tag_prefix=request.tag_prefix or cfg.snowball_tag_prefix,
            extra_tags=_extra_tags(cfg, request),
            note_provenance=cfg.snowball_note_provenance
            if request.note_provenance is None
            else request.note_provenance,
            remarks_surface=cfg.remarks_surface,
            console=console,
            allowlist=_title_allowlist(cfg),
        )
        failed = int(counts.get("failed") or 0)
    if mode != "off":
        manifest = Manifest(cfg.manifest_path)
        pending = pending_pdf_items(rows, items, manifest)
        if pending:
            fill_pdfs(cfg, lib, pending, console, mode=mode)
    _maybe_dedupe_after(cfg, request, lib, request.collection, console)
    return PathResult(dest, 1 if failed else 0)


def run_apply(
    cfg: Config,
    run_id: str,
    request: SnowballRequest,
    *,
    console: Console,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> PathResult:
    """Create ``keep=true`` rows from a prior approve-batch (or edited) queue."""
    _bind_command()
    if not cfg.snowball_enabled:
        raise SnowballError(
            "Snowball is off. Set [snowball] enabled = true in config.toml."
        )
    collection = request.collection.strip()
    if not collection:
        raise SnowballError(
            "snowball apply needs a target collection (-C / target_collection)."
        )
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.") from exc

    kept = [row for row in rows if row.keep is True]
    if not kept:
        raise SnowballError(
            f"No keep=true rows in {run_id}. Edit candidates.jsonl, then apply again."
        )

    lib = backend
    finder = lookup
    if finder is None:
        try:
            lib = lib or get_backend(cfg)
            finder = _library_lookup(
                lib, scope=_apply_fingerprint_scope(request), collection=collection
            )
        except Exception as exc:
            raise SnowballError(
                f"Library was not read. Refusing to create items. {exc}"
            ) from exc
    assert lib is not None and finder is not None
    _mark_exists(kept, finder, version_of=_version_of(cfg, request))
    creatable = [row for row in kept if row.status == "new"]
    if not creatable:
        console.print("nothing to create (all keep rows already in library)")
        from .prisma import prisma_counts

        report = {
            "created": 0,
            "skipped_exists": len(kept),
            "attach_ok": 0,
            "attach_deferred": 0,
            "prisma": prisma_counts(rows, added=0),
        }
        write_report(dest, report)
        return PathResult(dest, 0, summary=report)

    note = (
        cfg.snowball_note_provenance
        if request.note_provenance is None
        else request.note_provenance
    )
    items, counts = create_new(
        lib,
        creatable,
        collection,
        tag_prefix=request.tag_prefix or cfg.snowball_tag_prefix,
        extra_tags=_extra_tags(cfg, request),
        note_provenance=note,
        console=console,
        remarks_surface=cfg.remarks_surface,
        allowlist=_title_allowlist(cfg),
        local_cites=_local_cites(cfg, lib, collection),
    )
    if counts.get("failed"):
        console.print(
            f"[yellow]{counts['failed']} create(s) failed; other rows continued[/]"
        )
    report = {
        "created": counts["created"],
        "skipped_exists": counts["skipped_exists"] + (len(kept) - len(creatable)),
        "attach_ok": 0,
        "attach_deferred": 0,
    }
    from .prisma import prisma_counts

    report["prisma"] = prisma_counts(rows, added=int(counts["created"]))
    mode = _pdf_mode(request)
    if mode != "off" and items:
        stats = fill_pdfs(cfg, lib, items, console, mode=mode)
        downloaded = int(getattr(stats, "ok", 0)) + int(getattr(stats, "attached", 0))
        report["downloaded"] = downloaded
        report["attach_ok"] = int(getattr(stats, "attached", 0))
        report["attach_deferred"] = int(getattr(stats, "attach_failed", 0))
        _print_fetch_result(console, report, sought=len(items), collection=collection)
    else:
        console.print(f"items created (metadata only): {counts['created']}")
    _maybe_dedupe_after(cfg, request, lib, collection, console)
    write_report(dest, report)
    failed = int(counts.get("failed") or 0)
    created = int(counts.get("created") or 0)
    from ..agent_json import batch_exit

    return PathResult(
        dest,
        batch_exit(ok=created, failed=failed) if failed or created else 0,
        summary=report,
    )
