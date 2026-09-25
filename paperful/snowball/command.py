"""One snowball invocation. The CLI only parses flags and calls this."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from ..config import Config, parse_cap, parse_fetch_pdfs, parse_per_hop_rank
from ..dedupe import normalize_dedupe_title
from ..library import LibraryError, get_backend
from ..resolve import normalize_doi
from .candidate import Candidate
from .crawl import NoKeywordSeeds, doi_candidates, hybrid_candidates, orcid_candidates, search_candidates
from .expand import (
    apply_filters,
    clamp_depth,
    keyword_depth,
    normalize_direction,
    parse_keyword_hop_limit,
    parse_keyword_limit,
    parse_keyword_min_score,
    truncate,
)
from .fill import FillPaused, crossref_work, fill_crossref, fill_semanticscholar, s2_api_key, s2_paper
from .ingest import create_new, fill_pdfs
from .local_cites import load_local_cites
from .openalex import OpenAlexBudgetExceeded, OpenAlexClient, keyless_limit_message, normalize_orcid
from .orcid import OrcidError, orcid_dois
from .queue import load_queue, write_queue, write_report
from ..progress import item_progress
from .tally import Tally, paint
from .rank import FORMULA, apply_overlap
from .refine import llm_suggester, suggestions_for

Lookup = Callable[[str | None, str | None], str | None]
_PREPRINT_DOI_LINE = re.compile(r"(?im)^Preprint DOI:\s*(\S+)")
Decider = Callable[[Candidate], bool]
KNOWN_BACKENDS = ("openalex", "crossref", "semanticscholar", "orcid")


def _local_cites(cfg: Config, backend: Any, collection: str) -> Any:
    """In-collection cite index. A failure leaves creation to proceed without it."""
    if (cfg.remarks_surface or "note").strip().lower() == "off":
        return None
    if backend is None or not collection.strip():
        return None
    try:
        client = OpenAlexClient(email=cfg.email)
        return load_local_cites(
            backend,
            collection,
            state_dir=cfg.state_dir,
            client=client,
        )
    except Exception:
        return None


class SnowballError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


@dataclass
class SnowballRequest:
    gate: str = "dry-run"
    collection: str = ""
    fetch_pdfs: bool | str = False
    depth: int | None = None
    max_candidates: int | str | None = None
    per_hop_limit: int | str | None = None
    per_hop_rank: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    direction: str = "refs"
    keyword_limit: int | str | None = None
    keyword_hop_limit: int | str | None = None
    keyword_min_score: float | None = None
    dedupe_scope: str | None = None
    tag_prefix: str | None = None
    types: tuple[str, ...] | None = None
    oa_only: bool | None = None
    venue_include: tuple[str, ...] | None = None
    venue_exclude: tuple[str, ...] | None = None
    languages: tuple[str, ...] | None = None
    min_seed_citations: int | None = None
    note_provenance: bool | None = None
    backends: tuple[str, ...] | None = None
    hybrid_seeds: int | None = None
    approve_each_max: int | None = None
    refine: bool | None = None
    link_versions: bool = False


@dataclass
class PathResult:
    run_dir: Any
    exit_code: int


def run_search(
    cfg: Config,
    query: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    decider: Decider | None = None,
    crossref_getter: Any = None,
    s2_getter: Any = None,
    suggester: Any = None,
) -> PathResult:
    _guard(cfg, request)
    depth = keyword_depth(request.depth)
    warning = None
    if request.depth is not None and request.depth > depth:
        warning = f"depth clamped to {depth}"
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    keywords = _keyword_caps(cfg, request)
    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
        warning=warning,
        decider=decider,
        crossref_getter=crossref_getter,
        s2_getter=s2_getter,
        suggester=suggester,
        refine_query=query,
        crawl=lambda oa, run_id, gate, caps: search_candidates(
            oa,
            query,
            run_id=run_id,
            gate=gate,
            depth=depth,
            direction=direction,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            per_hop_rank=caps[2],
            year_from=request.year_from,
            year_to=request.year_to,
            min_seed_citations=_min_cites(cfg, request),
            keyword_limit=keywords[0],
            keyword_hop_limit=keywords[1],
            keyword_min_score=keywords[2],
        ),
    )


def run_hybrid(
    cfg: Config,
    query: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    decider: Decider | None = None,
    crossref_getter: Any = None,
    s2_getter: Any = None,
    suggester: Any = None,
) -> PathResult:
    """Keyword hits, then one hop from the top DOI hits."""
    _guard(cfg, request)
    text = query.strip()
    if not text:
        raise SnowballError("Pass a keyword query.")
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    keywords = _keyword_caps(cfg, request)
    seeds = request.hybrid_seeds if request.hybrid_seeds is not None else cfg.snowball_hybrid_seeds

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int, str]) -> tuple[list[Candidate], list[str]]:
        return hybrid_candidates(
            oa,
            text,
            run_id=run_id,
            gate=gate,
            direction=direction,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            per_hop_rank=caps[2],
            year_from=request.year_from,
            year_to=request.year_to,
            hybrid_seeds=seeds,
            min_seed_citations=_min_cites(cfg, request),
            keyword_limit=keywords[0],
            keyword_hop_limit=keywords[1],
            keyword_min_score=keywords[2],
        )

    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
        warning=None,
        crawl=crawl,
        expect_failures=True,
        decider=decider,
        crossref_getter=crossref_getter,
        s2_getter=s2_getter,
        suggester=suggester,
        refine_query=text,
    )


def run_doi(
    cfg: Config,
    dois: list[str],
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    decider: Decider | None = None,
    crossref_getter: Any = None,
    s2_getter: Any = None,
    suggester: Any = None,
) -> PathResult:
    _guard(cfg, request)
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    keywords = _keyword_caps(cfg, request)
    depth, warning = clamp_depth(_graph_depth(cfg, request))
    cleaned = [d.strip() for d in dois if d.strip()]
    if not cleaned:
        raise SnowballError("Pass at least one DOI.")

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int, str]) -> tuple[list[Candidate], list[str]]:
        return doi_candidates(
            oa,
            cleaned,
            run_id=run_id,
            gate=gate,
            depth=depth,
            direction=direction,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            per_hop_rank=caps[2],
            year_from=request.year_from,
            year_to=request.year_to,
            min_seed_citations=_min_cites(cfg, request),
            keyword_limit=keywords[0],
            keyword_hop_limit=keywords[1],
            keyword_min_score=keywords[2],
        )

    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
        warning=warning,
        crawl=crawl,
        expect_failures=True,
        decider=decider,
        crossref_getter=crossref_getter,
        s2_getter=s2_getter,
        suggester=suggester,
    )


def run_orcid(
    cfg: Config,
    orcid: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    orcid_getter: Any = None,
) -> PathResult:
    _guard(cfg, request)
    cleaned = normalize_orcid(orcid)
    if not cleaned:
        raise SnowballError(f"Invalid ORCID iD: {orcid!r}")
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    keywords = _keyword_caps(cfg, request)
    depth, warning = clamp_depth(_graph_depth(cfg, request))
    backends = _backends(cfg, request)
    if "orcid" in backends:
        try:
            dois = orcid_dois(cleaned, getter=orcid_getter)
        except OrcidError as exc:
            raise SnowballError(str(exc)) from exc
    else:
        dois = []
        console.print("[yellow]orcid backend off; using OpenAlex author filter only[/]")

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int, str]) -> tuple[list[Candidate], list[str]]:
        return orcid_candidates(
            oa,
            cleaned,
            dois,
            run_id=run_id,
            gate=gate,
            depth=depth,
            direction=direction,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            per_hop_rank=caps[2],
            year_from=request.year_from,
            year_to=request.year_to,
            min_seed_citations=_min_cites(cfg, request),
            keyword_limit=keywords[0],
            keyword_hop_limit=keywords[1],
            keyword_min_score=keywords[2],
        )

    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
        warning=warning,
        crawl=crawl,
        expect_failures=True,
    )


def run_collection(
    cfg: Config,
    seed_collection: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> PathResult:
    """DOIs already in ``seed_collection``, then the same expander as ``run_doi``."""
    _guard(cfg, request)
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    keywords = _keyword_caps(cfg, request)
    depth, warning = clamp_depth(_graph_depth(cfg, request))
    lib = backend
    try:
        lib = lib or get_backend(cfg)
        root = lib.resolve_collection(seed_collection)
        keys = lib.subtree_keys(root)
        items = lib.items_in_scope(keys)
    except Exception as exc:
        raise SnowballError(f"Could not read collection {seed_collection!r}: {exc}") from exc
    dois = sorted({item.doi for item in items if item.doi})
    if not dois:
        raise SnowballError(f"No DOIs in collection {seed_collection!r}.")

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int, str]) -> tuple[list[Candidate], list[str]]:
        return doi_candidates(
            oa,
            dois,
            run_id=run_id,
            gate=gate,
            depth=depth,
            direction=direction,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            per_hop_rank=caps[2],
            year_from=request.year_from,
            year_to=request.year_to,
            min_seed_citations=_min_cites(cfg, request),
            keyword_limit=keywords[0],
            keyword_hop_limit=keywords[1],
            keyword_min_score=keywords[2],
        )

    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=lib,
        warning=warning,
        crawl=crawl,
        expect_failures=True,
    )


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
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    import json
    from datetime import datetime, timezone

    from .crawl import _dedupe, continue_deferred

    dest = cfg.state_dir / "snowball" / run_id
    path = dest / "deferred.json"
    if not path.is_file():
        raise SnowballError(f"No deferred OpenAlex work for run {run_id!r}.")
    deferred = json.loads(path.read_text(encoding="utf-8"))
    reset_at = deferred.get("reset_at")
    if isinstance(reset_at, str) and reset_at:
        when = datetime.fromisoformat(reset_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        key_ready = bool((client.api_key if client is not None else "") or os.environ.get("OPENALEX_API_KEY"))
        if when > datetime.now(timezone.utc) and (deferred.get("keyed") or not key_ready):
            if deferred.get("keyed"):
                console.print(f"[yellow]OpenAlex budget still spent[/] · resume after {reset_at}")
            else:
                console.print("[yellow]" + keyless_limit_message(has_key=False, reset_at=reset_at) + "[/]")
            return PathResult(dest, 1)
    try:
        _, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.") from exc
    oa = client or OpenAlexClient(email=cfg.email, sleep_s=0.15)
    tally = _live_tally(console)
    oa.tally = tally
    oa.progress = lambda message: console.print(paint(message))
    tally.start()
    if deferred.get("kind") == "fill":
        added = []
        try:
            rows = _fill_metadata(
                cfg,
                request,
                rows,
                backends=_backends(cfg, request),
                console=console,
                live=client is None,
                crossref_getter=None,
                s2_getter=None,
                per_hop_limit=int(deferred.get("per_hop_limit") or cfg.snowball_per_hop_limit),
                direction=str(deferred.get("direction") or request.direction or "refs"),
                tally=tally,
            )
        except FillPaused as exc:
            oa.deferred = {
                **deferred,
                "backend": exc.backend,
                "remaining_ids": list(exc.remaining),
                "error": str(exc),
            }
        merged = rows
    else:
        added = continue_deferred(oa, deferred)
        merged = _dedupe(list(rows) + added)
    write_queue(
        cfg.state_dir,
        run_id,
        merged,
        oa,
        library_unread=False,
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
        lib = backend
        try:
            lib = lib or get_backend(cfg)
            create_new(
                lib,
                added,
                request.collection,
                tag_prefix=request.tag_prefix or cfg.snowball_tag_prefix,
                note_provenance=cfg.snowball_note_provenance
                if request.note_provenance is None
                else request.note_provenance,
                remarks_surface=cfg.remarks_surface,
                local_cites=_local_cites(cfg, lib, request.collection),
                console=console,
            )
        except (LibraryError, SnowballError) as exc:
            raise SnowballError(str(exc)) from exc
    return PathResult(dest, 0)


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
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    collection = request.collection.strip()
    if not collection:
        raise SnowballError("snowball apply needs a target collection (-C / target_collection).")
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
            finder = _library_lookup(lib, scope="library", collection=collection)
        except Exception as exc:
            raise SnowballError(f"Library was not read. Refusing to create items. {exc}") from exc
    assert lib is not None and finder is not None
    _mark_exists(kept, finder, version_of=_version_of(cfg, request))
    creatable = [row for row in kept if row.status == "new"]
    if not creatable:
        console.print("nothing to create (all keep rows already in library)")
        write_report(dest, {"created": 0, "skipped_exists": len(kept), "attach_ok": 0, "attach_deferred": 0})
        return PathResult(dest, 0)

    note = cfg.snowball_note_provenance if request.note_provenance is None else request.note_provenance
    items, counts = create_new(
        lib,
        creatable,
        collection,
        tag_prefix=request.tag_prefix or cfg.snowball_tag_prefix,
        note_provenance=note,
        console=console,
        remarks_surface=cfg.remarks_surface,
        local_cites=_local_cites(cfg, lib, collection),
    )
    if counts.get("failed"):
        console.print(f"[yellow]{counts['failed']} create(s) failed; other rows continued[/]")
    report = {
        "created": counts["created"],
        "skipped_exists": counts["skipped_exists"] + (len(kept) - len(creatable)),
        "attach_ok": 0,
        "attach_deferred": 0,
    }
    mode = _pdf_mode(request)
    if mode != "off" and items:
        stats = fill_pdfs(cfg, lib, items, console, mode=mode)
        downloaded = int(getattr(stats, "ok", 0)) + int(getattr(stats, "attached", 0))
        report["downloaded"] = downloaded
        report["attach_ok"] = int(getattr(stats, "attached", 0))
        report["attach_deferred"] = int(getattr(stats, "attach_failed", 0))
        console.print(
            f"downloaded {report.get('downloaded', 0)} · attached {report['attach_ok']} · "
            f"deferred {report['attach_deferred']}"
        )
    else:
        console.print(f"items created (metadata only): {counts['created']}")
    write_report(dest, report)
    return PathResult(dest, 1 if counts.get("failed") else 0)


def _pdf_mode(request: SnowballRequest) -> str:
    try:
        return parse_fetch_pdfs(request.fetch_pdfs)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def _cap(value: int | str | None, default: int) -> int:
    raw = default if value is None else value
    try:
        return parse_cap(raw)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def _keyword_caps(cfg: Config, request: SnowballRequest) -> tuple[int, int, float]:
    try:
        limit = (
            cfg.snowball_keyword_limit
            if request.keyword_limit is None
            else parse_keyword_limit(request.keyword_limit)
        )
        hop = (
            cfg.snowball_keyword_hop_limit
            if request.keyword_hop_limit is None
            else parse_keyword_hop_limit(request.keyword_hop_limit)
        )
        score = (
            cfg.snowball_keyword_min_score
            if request.keyword_min_score is None
            else parse_keyword_min_score(request.keyword_min_score)
        )
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    return limit, hop, score


def _rank(value: str | None, default: str) -> str:
    raw = default if value is None else value
    try:
        return parse_per_hop_rank(raw)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def _guard(cfg: Config, request: SnowballRequest) -> None:
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    if request.gate not in {"dry-run", "auto", "approve-batch", "approve-each"}:
        raise SnowballError("gate must be dry-run, approve-each, approve-batch, or auto.")
    _pdf_mode(request)
    if request.max_candidates is not None:
        _cap(request.max_candidates, 0)
    if request.per_hop_limit is not None:
        _cap(request.per_hop_limit, 0)
    if request.per_hop_rank is not None:
        _rank(request.per_hop_rank, "most-cited")
    _keyword_caps(cfg, request)
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    if scope not in {"library", "collection", "none"}:
        raise SnowballError("dedupe_scope must be library, collection, or none.")
    _backends(cfg, request)
    if request.gate in {"auto", "approve-batch", "approve-each"} and not request.collection.strip():
        raise SnowballError(
            f"gate {request.gate} needs a target collection (-C / target_collection)."
        )


def _graph_depth(cfg: Config, request: SnowballRequest) -> int:
    """DOI, ORCID, and collection hops. Omitted depth uses [snowball] depth."""
    if request.depth is None:
        return cfg.snowball_depth
    return request.depth


def _live_tally(console: Console) -> Tally:
    """Minute log on a captured console. A live bar when the user is at a terminal."""
    tally = Tally(lambda message: console.print(message))
    file = getattr(console, "file", None)
    if bool(getattr(file, "isatty", lambda: False)()):
        bar = item_progress(console)
        bar.start()
        tally.bind_bar(bar, bar.add_task("snowball", total=None))
    return tally


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
) -> PathResult:
    if warning:
        console.print(f"[yellow]{warning}[/]")
    mode = _pdf_mode(request)
    if mode != "off" and request.gate in {"dry-run", "approve-batch"}:
        console.print("[yellow]fetch_pdfs ignored until create (auto / apply)[/]")
    oa = client or OpenAlexClient(email=cfg.email, sleep_s=0.0 if client else 0.15)
    tally = _live_tally(console)
    oa.tally = tally
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
    tally.start()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gate = request.gate
    caps = (
        _cap(request.max_candidates, cfg.snowball_max_candidates),
        _cap(request.per_hop_limit, cfg.snowball_per_hop_limit),
        _rank(request.per_hop_rank, cfg.snowball_per_hop_rank),
    )
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
            }
        produced = (list(saved), []) if expect_failures else list(saved)
        if isinstance(exc, KeyboardInterrupt) and not saved:
            raise
    if expect_failures:
        rows, failed = produced
    else:
        rows = produced
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    types = cfg.snowball_types if request.types is None else request.types
    oa_only = cfg.snowball_oa_only if request.oa_only is None else request.oa_only
    venue_include = cfg.snowball_venue_include if request.venue_include is None else request.venue_include
    venue_exclude = cfg.snowball_venue_exclude if request.venue_exclude is None else request.venue_exclude
    languages = cfg.snowball_languages if request.languages is None else request.languages
    tag_prefix = request.tag_prefix or cfg.snowball_tag_prefix
    note_provenance = cfg.snowball_note_provenance if request.note_provenance is None else request.note_provenance
    backends = _backends(cfg, request)
    try:
        direction = normalize_direction(request.direction)
    except ValueError:
        direction = "refs"
    apply_overlap(rows)
    try:
        rows = _fill_metadata(
            cfg,
            request,
            rows,
            backends=backends,
            console=console,
            live=client is None,
            crossref_getter=crossref_getter,
            s2_getter=s2_getter,
            per_hop_limit=caps[1],
            direction=direction,
            tally=tally,
        )
    except FillPaused as exc:
        if oa.deferred is None:
            oa.deferred = {
                "kind": "fill",
                "backend": exc.backend,
                "remaining_ids": list(exc.remaining),
                "error": str(exc),
                "keyed": bool(oa._using_key and oa.api_key),
            }
        rows = list(saved) or rows
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
    )
    rows = truncate(rows, caps[0])
    if gate == "approve-batch":
        for row in rows:
            if row.keep is None and row.status == "new":
                row.keep = False
    library_unread = False
    finder = lookup
    lib = backend
    _unread_error: BaseException | None = None
    if scope == "none":
        console.print("[yellow]dedupe_scope none: not checking the library[/]")
        finder = None
        if gate in {"auto", "approve-each"} and lib is None:
            try:
                lib = get_backend(cfg)
            except Exception as exc:
                lib = None
                _unread_error = exc
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
                _unread_error = exc
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
    _print_table(console, rows)
    exit_code = 1 if failed or oa.deferred else 0
    if oa.deferred:
        when = oa.deferred.get("reset_at") or "the daily reset"
        console.print(f"[yellow]Partial queue kept[/] · paperful snowball resume {run_id}")
    if gate in {"dry-run", "approve-batch"}:
        if gate == "approve-batch":
            console.print(
                f"candidates ready · mark keep=true in {dest / 'candidates.jsonl'} · "
                f"then: paperful snowball apply {run_id}"
            )
        else:
            console.print("candidates ready")
        tally.stop()
        return PathResult(dest, exit_code)
    if library_unread or lib is None:
        detail = f" { _unread_error }" if _unread_error else ""
        tally.stop()
        raise SnowballError(f"Library was not read. Refusing to create items.{detail}")
    try:
        items, counts = create_new(
            lib,
            rows,
            request.collection,
            tag_prefix=tag_prefix,
            note_provenance=note_provenance,
            console=console,
            tally=tally,
            remarks_surface=cfg.remarks_surface,
            local_cites=_local_cites(cfg, lib, request.collection),
        )
    except LibraryError as exc:
        tally.stop()
        raise SnowballError(str(exc)) from exc
    exit_code = 1 if failed or counts.get("failed") else exit_code
    report = {
        "created": counts["created"],
        "skipped_exists": counts["skipped_exists"],
        "attach_ok": 0,
        "attach_deferred": 0,
    }
    if mode != "off" and items:
        stats = fill_pdfs(cfg, lib, items, console, tally=tally, mode=mode)
        downloaded = int(getattr(stats, "ok", 0)) + int(getattr(stats, "attached", 0))
        report["downloaded"] = downloaded
        report["attach_ok"] = int(getattr(stats, "attached", 0))
        report["attach_deferred"] = int(getattr(stats, "attach_failed", 0))
    write_report(dest, report)
    if mode != "off":
        console.print(
            f"downloaded {report.get('downloaded', 0)} · attached {report['attach_ok']} · "
            f"deferred {report['attach_deferred']}"
        )
    else:
        console.print(f"items created (metadata only): {counts['created']}")
    tally.stop()
    return PathResult(dest, exit_code)


def _library_lookup(backend: Any, *, scope: str, collection: str) -> Lookup:
    items = None
    if hasattr(backend, "items_in_scope"):
        try:
            items = list(backend.items_in_scope(None))
        except Exception:
            items = None
    if items is not None:
        if scope == "collection":
            want = collection.strip()
            items = [item for item in items if want and want in (item.collection_paths or [])]
        by_doi: dict[str, str] = {}
        by_title_year: dict[tuple[str, int], str] = {}
        for item in items:
            doi = normalize_doi(item.doi) if getattr(item, "doi", None) else None
            if doi:
                by_doi.setdefault(doi, item.key)
            arxiv_id = getattr(item, "arxiv_id", None)
            if arxiv_id:
                arxiv_doi = normalize_doi(f"10.48550/arxiv.{arxiv_id}")
                if arxiv_doi:
                    by_doi.setdefault(arxiv_doi, item.key)
            extra = getattr(item, "extra", "") or ""
            preprint_line = _PREPRINT_DOI_LINE.search(extra)
            if preprint_line:
                preprint = normalize_doi(preprint_line.group(1))
                if preprint:
                    by_doi.setdefault(preprint, item.key)
            title = normalize_dedupe_title(getattr(item, "title", None))
            year = getattr(item, "year", None)
            if title and year is not None:
                by_title_year.setdefault((title, int(year)), item.key)

        def indexed(doi: str | None, title: str | None, year: int | None = None) -> Any:
            found = normalize_doi(doi) if doi else None
            if found and found in by_doi:
                return by_doi[found], "doi"
            key = normalize_dedupe_title(title)
            if key and year is not None and (key, int(year)) in by_title_year:
                return by_title_year[(key, int(year))], "title_year"
            return None

        return indexed

    zl = getattr(backend, "zl", None)

    def lookup(doi: str | None, title: str | None, year: int | None = None) -> str | None:
        del year
        if zl is None:
            return None
        return zl.find_top_item_key(doi=doi, title=title)

    return lookup


def _mark_exists(
    rows: list[Candidate],
    lookup: Lookup,
    version_of: Callable[[str], Any] | None = None,
) -> None:
    for row in rows:
        if row.status in {"error", "filtered"}:
            continue
        doi = row.ids.get("doi") or None
        title = row.biblio.get("title") or None
        year = row.biblio.get("year")
        found = _call_lookup(lookup, doi, title, year)
        if found:
            _set_exists(row, found, doi=doi, title=title, year=year)
            continue
        if not version_of or not doi:
            continue
        try:
            link = version_of(doi)
        except Exception:
            link = None
        if link is None:
            continue
        other = _other_version_doi(doi, link)
        hit = _call_lookup(lookup, other, None, None) if other else None
        if not hit and getattr(link, "arxiv_id", None):
            hit = _call_lookup(
                lookup, f"10.48550/arxiv.{link.arxiv_id}", None, None
            )
        if not hit:
            continue
        key = hit[0] if isinstance(hit, tuple) else hit
        row.status = "version"
        row.exists_match = {
            "item_key": key,
            "version_of": normalize_doi(getattr(link, "published_doi", "") or "")
            or str(getattr(link, "published_doi", "") or ""),
        }


def _version_of(cfg: Config, request: SnowballRequest) -> Callable[[str], Any] | None:
    if not request.link_versions:
        return None
    import httpx

    from ..versions import resolver_for

    client = httpx.Client(follow_redirects=True, timeout=30)
    return resolver_for(client, cfg.email)


def _call_lookup(
    lookup: Lookup, doi: str | None, title: str | None, year: int | None
) -> Any:
    try:
        return lookup(doi, title, year)  # type: ignore[call-arg]
    except TypeError:
        return lookup(doi, title)


def _set_exists(
    row: Candidate,
    found: Any,
    *,
    doi: str | None,
    title: str | None,
    year: int | None,
) -> None:
    if isinstance(found, tuple):
        key, kind = found
    else:
        key, kind = found, ("doi" if doi else "title_year")
    row.status = "exists"
    if kind == "title_year":
        row.exists_match = {
            "item_key": key,
            "title_year": f"{normalize_dedupe_title(title)}|{year}",
        }
    else:
        row.exists_match = {"item_key": key, "doi": normalize_doi(doi) or (doi or "")}


def _other_version_doi(doi: str, link: Any) -> str | None:
    query = normalize_doi(doi)
    published = normalize_doi(getattr(link, "published_doi", None))
    preprint = normalize_doi(getattr(link, "preprint_doi", None))
    if query and published and query != published:
        return published
    if query and preprint and query != preprint:
        return preprint
    return published or preprint


def _print_table(console: Console, rows: list[Candidate]) -> None:
    ordered = sorted(rows, key=lambda row: (row.status != "new", -row.score))
    table = Table(title="Snowball", expand=True)
    for name in ("Title", "Year", "DOI", "Why", "In library", "Hop", "Backend"):
        table.add_column(name, overflow="ellipsis")
    for row in ordered:
        table.add_row(
            str(row.biblio.get("title") or ""),
            str(row.biblio.get("year") or ""),
            row.ids.get("doi") or "",
            row.why,
            row.status,
            f"{row.hop} {row.direction}",
            row.provenance.get("backend") or "",
        )
    console.print(table)


def _min_cites(cfg: Config, request: SnowballRequest) -> int:
    if request.min_seed_citations is None:
        return cfg.snowball_min_seed_citations
    return request.min_seed_citations


def _backends(cfg: Config, request: SnowballRequest) -> tuple[str, ...]:
    names = cfg.snowball_backends if request.backends is None else request.backends
    cleaned = tuple(part.strip().lower() for part in names if str(part).strip())
    if not cleaned:
        cleaned = KNOWN_BACKENDS
    unknown = [name for name in cleaned if name not in KNOWN_BACKENDS]
    if unknown:
        raise SnowballError(f"Unknown snowball backend {unknown[0]!r}.")
    if "openalex" not in cleaned:
        raise SnowballError("snowball backends must include openalex.")
    return cleaned


def _approve_each(
    rows: list[Candidate],
    request: SnowballRequest,
    cfg: Config,
    console: Console,
    decider: Decider | None,
    run_id: str,
) -> None:
    pending = [row for row in rows if row.status == "new"]
    limit = request.approve_each_max if request.approve_each_max is not None else cfg.snowball_approve_each_max
    if len(pending) > limit:
        raise SnowballError(
            f"{len(pending)} new rows exceeds approve_each_max ({limit}). Use --gate approve-batch."
        )
    if decider is None and not sys.stdin.isatty():
        raise SnowballError(
            f"approve-each needs a terminal. Queue {run_id} is on disk. Use --gate approve-batch."
        )
    for row in pending:
        if decider is not None:
            yes = bool(decider(row))
        else:
            title = row.biblio.get("title") or row.ids.get("doi") or "untitled"
            answer = console.input(f"Keep {title}? [y/N] ").strip().lower()
            yes = answer in {"y", "yes"}
        row.keep = yes


def _fill_metadata(
    cfg: Config,
    request: SnowballRequest,
    rows: list[Candidate],
    *,
    backends: tuple[str, ...],
    console: Console,
    live: bool,
    crossref_getter: Any,
    s2_getter: Any,
    per_hop_limit: int,
    direction: str,
    tally: Tally | None = None,
) -> list[Candidate]:
    if "crossref" in backends:
        getter = crossref_getter
        if getter is None and live:
            getter = lambda doi: crossref_work(doi, email=cfg.email)
        if getter is not None:
            fill_crossref(rows, getter, tally=tally)
    if "semanticscholar" in backends:
        getter = s2_getter
        if getter is None and live:
            key = s2_api_key()
            cache = cfg.state_dir / "snowball" / "cache"
            getter = lambda doi: s2_paper(doi, cache_dir=cache, api_key=key)
        if getter is not None:
            rows = list(rows) + fill_semanticscholar(
                rows, getter, per_hop_limit=per_hop_limit, direction=direction, tally=tally
            )
    return rows


def _summary_meta(
    cfg: Config,
    request: SnowballRequest,
    *,
    caps: tuple[int, int, str],
    filtered: int,
    scope: str,
    refine_query: str,
    suggester: Any,
    console: Console,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "score": FORMULA,
        "max_candidates": caps[0],
        "per_hop_limit": caps[1],
        "per_hop_rank": caps[2],
        "keyword_limit": _keyword_caps(cfg, request)[0],
        "keyword_hop_limit": _keyword_caps(cfg, request)[1],
        "keyword_min_score": _keyword_caps(cfg, request)[2],
        "filtered": filtered,
        "dedupe_scope": scope,
    }
    refine = cfg.snowball_refine if request.refine is None else request.refine
    if not refine:
        return meta
    if suggester is None and not cfg.llm_enabled:
        meta["suggestions_error"] = "llm disabled"
        console.print("[yellow]refine ignored: llm disabled[/]")
        return meta
    if suggester is None:
        try:
            suggester = llm_suggester(cfg)
        except Exception as exc:
            meta["suggestions_error"] = str(exc)
            return meta
    found, error = suggestions_for(refine_query, suggester)
    if error:
        meta["suggestions_error"] = error
    else:
        meta["suggestions"] = found
        if found:
            console.print("suggestions: " + "; ".join(found))
    return meta
