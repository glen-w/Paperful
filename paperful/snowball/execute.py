"""Snowball crawl execute / gate / create-and-fill (command.py re-exports)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console

from ..agent_json import EXIT_PARTIAL, batch_exit
from ..config import Config
from ..library import LibraryError
from .candidate import Candidate
from .crawl import NoKeywordSeeds
from .expand import apply_filters, normalize_direction, truncate
from .fill import FillPaused, s2_api_key, s2_paper
from .openalex import OpenAlexClient
from .queue import write_queue, write_report
from .rank import apply_overlap
from .tally import Tally, paint
from .titles import repair_reference_titles

if TYPE_CHECKING:
    from .command import Decider, Lookup, PathResult, SnowballRequest

_FROM_COMMAND = (
    "SnowballError",
    "PathResult",
    "get_backend",
    "_openalex_client",
    "_local_cites",
    "_title_allowlist",
    "fill_pdfs",
    "create_new",
    "_library_lookup",
    "_mark_exists",
    "_version_of",
    "_fill_metadata",
    "_blocked_dois",
    "_settled_rows",
    "_approve_each",
    "_summary_meta",
    "_print_table",
    "_print_fetch_result",
    "_extra_tags",
    "_pdf_mode",
    "_cap",
    "_rank",
    "_backends",
    "_live_tally",
    "_write_cached_pdfs",
    "_maybe_dedupe_after",
    "_open_stop",
)


# Placeholders: rebound from command.py on each call (keeps monkeypatches).
SnowballError = None
PathResult = None
get_backend = None
_openalex_client = None
_local_cites = None
_title_allowlist = None
fill_pdfs = None
create_new = None
_library_lookup = None
_mark_exists = None
_version_of = None
_fill_metadata = None
_blocked_dois = None
_settled_rows = None
_approve_each = None
_summary_meta = None
_print_table = None
_print_fetch_result = None
_extra_tags = None
_pdf_mode = None
_cap = None
_rank = None
_backends = None
_live_tally = None
_write_cached_pdfs = None
_maybe_dedupe_after = None
_open_stop = None


def _bind_command() -> None:
    from . import command as _command

    g = globals()
    for name in _FROM_COMMAND:
        g[name] = getattr(_command, name)


def _snowball_crawl_rows(
    cfg: Config,
    request: SnowballRequest,
    *,
    oa: OpenAlexClient,
    run_id: str,
    gate: str,
    caps: tuple[int, int, str],
    crawl: Callable,
    expect_failures: bool,
    expand_neighbors: bool,
) -> tuple[list[Candidate], list[str]]:
    _bind_command()
    failed: list[str] = []
    saved: list[Candidate] = []
    seen: set[str] = set()

    def emit(batch: list[Candidate]) -> None:
        changed = False
        for row in batch:
            key = row.identity or f"row:{id(row)}"
            if key in seen:
                continue
            seen.add(key)
            saved.append(row)
            changed = True
        if changed:
            write_queue(cfg.state_dir, run_id, saved, oa, library_unread=True)

    oa.emit = emit
    try:
        produced = crawl(oa, run_id, gate, caps)
    except NoKeywordSeeds as exc:
        raise SnowballError(str(exc)) from exc
    except (Exception, KeyboardInterrupt) as exc:
        if oa.deferred is None:
            remaining = list(getattr(exc, "remaining", []) or [])
            oa.deferred = {
                "kind": "fill" if isinstance(exc, FillPaused) else "interrupted",
                "backend": getattr(exc, "backend", ""),
                "reset_at": getattr(exc, "reset_at", None),
                "reset_in_s": getattr(exc, "reset_in_s", None),
                "remaining_ids": remaining,
                "keyed": bool(oa._using_key and oa.api_key),
                "error": str(exc),
                "expand_neighbors": expand_neighbors,
            }
        produced = (list(saved), []) if expect_failures else list(saved)
        if isinstance(exc, KeyboardInterrupt) and not saved:
            raise
    if expect_failures:
        rows, failed = produced
    else:
        rows = produced
    return rows, failed


def _snowball_prepare_queue(
    cfg: Config,
    request: SnowballRequest,
    rows: list[Candidate],
    *,
    console: Console,
    oa: OpenAlexClient,
    run_id: str,
    gate: str,
    caps: tuple[int, int, str],
    client: OpenAlexClient | None,
    lookup: Lookup | None,
    backend: Any,
    backends: tuple[str, ...],
    crossref_getter: Any,
    s2_getter: Any,
    expand_neighbors: bool,
    decider: Decider | None,
    refine_query: str,
    suggester: Any,
) -> tuple[list[Candidate], Path, bool, Any, BaseException | None, dict[str, Any]]:
    _bind_command()
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    types = cfg.snowball_types if request.types is None else request.types
    oa_only = cfg.snowball_oa_only if request.oa_only is None else request.oa_only
    venue_include = (
        cfg.snowball_venue_include
        if request.venue_include is None
        else request.venue_include
    )
    venue_exclude = (
        cfg.snowball_venue_exclude
        if request.venue_exclude is None
        else request.venue_exclude
    )
    languages = (
        cfg.snowball_languages if request.languages is None else request.languages
    )
    study_designs = (
        cfg.snowball_study_designs
        if request.study_designs is None
        else request.study_designs
    )
    listed_in = (
        cfg.snowball_listed_in if request.listed_in is None else request.listed_in
    )
    try:
        direction = normalize_direction(request.direction)
    except ValueError:
        direction = "refs"
    apply_overlap(rows)
    rows, paused = _fill_metadata(
        cfg,
        request,
        rows,
        backends=backends,
        console=console,
        live=client is None,
        crossref_getter=crossref_getter,
        s2_getter=s2_getter,
        europepmc_getter=getattr(oa, "epmc_getter", None),
        europepmc_cache=getattr(oa, "epmc_cache_dir", None),
        pdf_getter=getattr(oa, "pdf_getter", None),
        per_hop_limit=caps[1],
        direction=direction,
        tally=oa.tally,
        expand_neighbors=expand_neighbors,
    )
    repair_reference_titles(rows, oa, tally=oa.tally)
    if paused and oa.deferred is None:
        remaining = _blocked_dois(paused)
        oa.deferred = {
            "kind": "fill",
            "backend": next(iter(paused)),
            "remaining_ids": sorted(remaining),
            "pauses": paused,
            "error": next(iter(paused)),
            "keyed": bool(oa._using_key and oa.api_key),
            "per_hop_limit": caps[1],
            "direction": direction,
            "expand_neighbors": expand_neighbors,
        }
    apply_overlap(rows)
    rows = apply_filters(
        rows,
        year_from=request.year_from,
        year_to=request.year_to,
        types=types,
        oa_only=oa_only,
        venue_include=venue_include,
        venue_exclude=venue_exclude,
        languages=languages,
        study_designs=tuple(study_designs or ()),
        listed_in=tuple(listed_in or ()),
    )
    rows = truncate(rows, caps[0])
    if gate == "approve-batch" and not request.iterative:
        for row in rows:
            if row.keep is None and row.status == "new":
                row.keep = False
    library_unread = False
    finder = lookup
    lib = backend
    unread_error: BaseException | None = None
    if scope == "none":
        console.print("[yellow]dedupe_scope none: not checking the library[/]")
        finder = None
        if gate in {"auto", "approve-each"} and lib is None:
            try:
                lib = get_backend(cfg)
            except Exception as exc:
                lib = None
                unread_error = exc
                library_unread = True
    elif finder is None:
        try:
            lib = lib or get_backend(cfg)
            finder = _library_lookup(lib, scope=scope, collection=request.collection)
        except Exception as exc:
            library_unread = True
            finder = None
            if gate in {"auto", "approve-each"}:
                lib = None
                unread_error = exc
    if scope != "none" and finder is not None:
        try:
            _mark_exists(rows, finder, version_of=_version_of(cfg, request))
        except Exception:
            library_unread = True
    elif scope != "none":
        library_unread = True
    if gate == "approve-each":
        _approve_each(rows, request, cfg, console, decider, run_id)
    filtered = sum(1 for row in rows if row.status == "filtered")
    dest = write_queue(
        cfg.state_dir,
        run_id,
        rows,
        oa,
        library_unread=library_unread,
        meta=_summary_meta(
            cfg,
            request,
            caps=caps,
            filtered=filtered,
            scope=scope,
            refine_query=refine_query,
            suggester=suggester,
            console=console,
        ),
    )
    return rows, dest, library_unread, lib, unread_error, paused


def _execute_preflight(
    cfg: Config,
    request: SnowballRequest,
    rows: list[Candidate],
    *,
    dest: Path,
    console: Console,
) -> None:
    _bind_command()
    want_preflight = (
        cfg.snowball_author_site_preflight
        if request.author_site_preflight is None
        else request.author_site_preflight
    )
    if not want_preflight:
        return
    from .preflight import run_author_site_preflight

    run_author_site_preflight(
        cfg,
        rows,
        dest=dest,
        collection=request.collection,
        console=console,
    )
    if cfg.twenty_enabled and cfg.twenty_lookup_on_preflight:
        from ..twenty import lookup_authors, twenty_ready
        from .authors import load_pack_file, pack_path, pack_slug

        if twenty_ready(cfg):
            slug = pack_slug(request.collection)
            pack = load_pack_file(pack_path(cfg, slug, promoted=False))
            people = list(pack.authors) if pack is not None else []
            if people:
                lookup_authors(
                    cfg,
                    people,
                    collection=request.collection,
                    apply=True,
                )
                console.print(
                    "twenty lookup on preflight · proposed pack/contacts updated "
                    "(promote before author_site fetch; no mail)"
                )
        else:
            console.print(
                "[yellow]twenty lookup_on_preflight skipped[/] "
                "(need TWENTY_API_KEY and [twenty].base_url)"
            )


def _execute_gate_exit(
    cfg: Config,
    request: SnowballRequest,
    *,
    console: Console,
    oa: OpenAlexClient,
    dest: Path,
    rows: list[Candidate],
    caps: tuple[int, int, str],
    run_id: str,
    gate: str,
    crawl_fail_n: int,
    tally: Tally,
) -> PathResult | None:
    _bind_command()
    _print_table(console, rows)
    if oa.deferred:
        exit_code = EXIT_PARTIAL
        console.print(
            f"[yellow]Partial queue kept[/] · paperful snowball resume {run_id}"
        )
    else:
        exit_code = 0
    if request.iterative and not oa.deferred:
        _open_stop(cfg, request, dest, rows, caps, console, run_id)
    if gate not in {"dry-run", "approve-batch"}:
        return None
    if request.iterative and not oa.deferred:
        console.print(
            f"one hop saved · Keep or Skip each new row · "
            f"paperful snowball continue {run_id}"
        )
    elif gate == "approve-batch":
        console.print(
            f"candidates ready · mark keep=true in {dest / 'candidates.jsonl'} · "
            f"then: paperful snowball apply {run_id}"
        )
    else:
        console.print("candidates ready")
    if not oa.deferred and crawl_fail_n:
        ok_n = max(0, len(rows) - crawl_fail_n)
        exit_code = batch_exit(ok=ok_n, failed=crawl_fail_n)
    tally.stop()
    return PathResult(dest, exit_code)


def _execute_create_and_fill(
    cfg: Config,
    request: SnowballRequest,
    *,
    console: Console,
    oa: OpenAlexClient,
    dest: Path,
    rows: list[Candidate],
    paused: dict[str, Any],
    lib: Any,
    library_unread: bool,
    unread_error: BaseException | None,
    tally: Tally,
    crawl_fail_n: int,
    tag_prefix: str,
    note_provenance: Any,
    mode: str,
) -> PathResult:
    _bind_command()
    if library_unread or lib is None:
        detail = f" {unread_error}" if unread_error else ""
        tally.stop()
        raise SnowballError(f"Library was not read. Refusing to create items.{detail}")
    try:
        creatable = _settled_rows(rows, _blocked_dois(paused))
        items, counts = create_new(
            lib,
            creatable,
            request.collection,
            tag_prefix=tag_prefix,
            extra_tags=_extra_tags(cfg, request),
            note_provenance=note_provenance,
            console=console,
            tally=tally,
            remarks_surface=cfg.remarks_surface,
            local_cites=_local_cites(cfg, lib, request.collection),
            allowlist=_title_allowlist(cfg),
        )
    except LibraryError as exc:
        tally.stop()
        raise SnowballError(str(exc)) from exc
    create_fail_n = int(counts.get("failed") or 0)
    created_n = int(counts.get("created") or 0)
    if oa.deferred:
        exit_code = EXIT_PARTIAL
    else:
        exit_code = batch_exit(ok=created_n, failed=crawl_fail_n + create_fail_n)
    report = {
        "created": counts["created"],
        "skipped_exists": counts["skipped_exists"],
        "attach_ok": 0,
        "attach_deferred": 0,
    }
    _write_cached_pdfs(cfg, items, rows)
    if mode != "off" and items:
        stats = fill_pdfs(cfg, lib, items, console, tally=tally, mode=mode)
        downloaded = int(getattr(stats, "ok", 0)) + int(getattr(stats, "attached", 0))
        report["downloaded"] = downloaded
        report["attach_ok"] = int(getattr(stats, "attached", 0))
        report["attach_deferred"] = int(getattr(stats, "attach_failed", 0))
    write_report(dest, report)
    if mode != "off":
        _print_fetch_result(
            console, report, sought=len(items), collection=request.collection
        )
    else:
        console.print(f"items created (metadata only): {counts['created']}")
    _maybe_dedupe_after(cfg, request, lib, request.collection, console)
    tally.stop()
    return PathResult(dest, exit_code)


def _execute(
    cfg: Config,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None,
    lookup: Lookup | None,
    backend: Any,
    warning: str | None,
    crawl: Callable,
    expect_failures: bool = False,
    decider: Decider | None = None,
    crossref_getter: Any = None,
    s2_getter: Any = None,
    suggester: Any = None,
    refine_query: str = "",
    expand_neighbors: bool = True,
) -> PathResult:
    _bind_command()
    if warning:
        console.print(f"[yellow]{warning}[/]")
    mode = _pdf_mode(request)
    if mode != "off" and request.gate in {"dry-run", "approve-batch"}:
        console.print("[yellow]fetch_pdfs ignored until create (auto / apply)[/]")
    oa = client or _openalex_client(cfg, sleep_s=0.0 if client else 0.15)
    tally = _live_tally(console)
    oa.tally = tally
    if request.from_created_date:
        oa.from_created_date = request.from_created_date.strip() or None
    designs = (
        cfg.snowball_study_designs
        if request.study_designs is None
        else request.study_designs
    )
    oa.study_designs = tuple(designs or ())
    lists = cfg.snowball_listed_in if request.listed_in is None else request.listed_in
    oa.listed_in = tuple(lists or ())
    if oa.progress is None:
        oa.progress = lambda message: console.print(paint(message))
    backends_early = _backends(cfg, request)
    if "semanticscholar" in backends_early:
        if s2_getter is not None:
            oa.s2_getter = s2_getter
        elif client is None:
            key = s2_api_key()
            oa.s2_cache_dir = cfg.state_dir / "snowball" / "cache"
            oa.s2_getter = lambda doi, _cache=oa.s2_cache_dir, _key=key: s2_paper(
                doi, cache_dir=_cache, api_key=_key
            )
    if "europepmc" in backends_early and client is None:
        from .europepmc import europepmc_work

        oa.epmc_cache_dir = cfg.state_dir / "snowball" / "cache" / "europepmc"
        oa.epmc_getter = lambda doi, _cache=oa.epmc_cache_dir: europepmc_work(
            doi, cache_dir=_cache
        )
    tally.start()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gate = request.gate
    caps = (
        _cap(request.max_candidates, cfg.snowball_max_candidates),
        _cap(request.per_hop_limit, cfg.snowball_per_hop_limit),
        _rank(request.per_hop_rank, cfg.snowball_per_hop_rank),
    )
    backends = _backends(cfg, request)
    rows, failed = _snowball_crawl_rows(
        cfg,
        request,
        oa=oa,
        run_id=run_id,
        gate=gate,
        caps=caps,
        crawl=crawl,
        expect_failures=expect_failures,
        expand_neighbors=expand_neighbors,
    )
    rows, dest, library_unread, lib, _unread_error, paused = _snowball_prepare_queue(
        cfg,
        request,
        rows,
        console=console,
        oa=oa,
        run_id=run_id,
        gate=gate,
        caps=caps,
        client=client,
        lookup=lookup,
        backend=backend,
        backends=backends,
        crossref_getter=crossref_getter,
        s2_getter=s2_getter,
        expand_neighbors=expand_neighbors,
        decider=decider,
        refine_query=refine_query,
        suggester=suggester,
    )
    tag_prefix = request.tag_prefix or cfg.snowball_tag_prefix
    note_provenance = (
        cfg.snowball_note_provenance
        if request.note_provenance is None
        else request.note_provenance
    )
    crawl_fail_n = len(failed) if failed else 0
    _execute_preflight(cfg, request, rows, dest=dest, console=console)
    gated = _execute_gate_exit(
        cfg,
        request,
        console=console,
        oa=oa,
        dest=dest,
        rows=rows,
        caps=caps,
        run_id=run_id,
        gate=gate,
        crawl_fail_n=crawl_fail_n,
        tally=tally,
    )
    if gated is not None:
        return gated
    return _execute_create_and_fill(
        cfg,
        request,
        console=console,
        oa=oa,
        dest=dest,
        rows=rows,
        paused=paused,
        lib=lib,
        library_unread=library_unread,
        unread_error=_unread_error,
        tally=tally,
        crawl_fail_n=crawl_fail_n,
        tag_prefix=tag_prefix,
        note_provenance=note_provenance,
        mode=mode,
    )
