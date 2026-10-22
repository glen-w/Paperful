"""One snowball invocation. The CLI only parses flags and calls this."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from ..agent_json import EXIT_PARTIAL, batch_exit
from ..config import Config, parse_cap, parse_fetch_pdfs, parse_per_hop_rank
from ..dedupe import normalize_dedupe_title
from ..catalogue import open_library
from ..library import LibraryError
from ..identity import library_lookup, merge_tags
from ..resolve import doi_key, normalize_doi
from .candidate import Candidate
from .crawl import NoKeywordSeeds, doi_candidates, hybrid_candidates, orcid_candidates, search_candidates
from .expand import (
    DEFAULT_DIRECTION,
    apply_filters,
    clamp_depth,
    direction_sides,
    keyword_depth,
    normalize_direction,
    parse_keyword_hop_limit,
    parse_keyword_limit,
    parse_keyword_min_score,
    truncate,
)
from .fill import FillPaused, crossref_work, run_fill_pass, s2_api_key, s2_paper
from .ingest import create_new, fill_pdfs
from .local_cites import load_local_cites
from .local_openalex import store_from_config
from .openalex import OpenAlexClient, keyless_limit_message, normalize_orcid
from .orcid import OrcidError, orcid_dois
from .queue import load_queue, write_queue, write_report
from ..progress import item_progress
from ..runreport import low_download_advice
from .tally import Tally, paint
from .titles import repair_reference_titles
from .rank import FORMULA, apply_overlap
from .refine import llm_suggester, suggestions_for

Lookup = Callable[[str | None, str | None], str | None]
def get_backend(cfg: Config) -> Any:
    """The library as snowball reads it: the mirror, refreshed when the manager answers."""
    return open_library(cfg)


Decider = Callable[[Candidate], bool]
KNOWN_BACKENDS = ("openalex", "crossref", "semanticscholar", "orcid", "europepmc", "pdf")


def _openalex_client(cfg: Config, **kwargs: Any) -> OpenAlexClient:
    """Build an OpenAlex client; attach an opt-in snapshot store when configured."""
    return OpenAlexClient(email=cfg.email, store=store_from_config(cfg), **kwargs)


def _local_cites(cfg: Config, backend: Any, collection: str) -> Any:
    """In-collection cite index. A failure leaves creation to proceed without it."""
    if (cfg.remarks_surface or "note").strip().lower() == "off":
        return None
    if backend is None or not collection.strip():
        return None
    try:
        client = _openalex_client(cfg)
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


def _title_allowlist(cfg: Config) -> frozenset[str]:
    from ..acronyms import load_acronym_allowlist

    return load_acronym_allowlist(cfg.state_dir)


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
    direction: str = "refs+keywords"
    keyword_limit: int | str | None = None
    keyword_hop_limit: int | str | None = None
    keyword_min_score: float | None = None
    search_keywords: bool | None = None
    dedupe_scope: str | None = None
    tag_prefix: str | None = None
    tags: tuple[str, ...] = ()
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
    from_created_date: str | None = None
    cites_query: str = ""
    study_designs: tuple[str, ...] | None = None
    map_categories: tuple[str, ...] | None = None
    map_category_defs: tuple[dict[str, Any], ...] | None = None
    dedupe_after: str | None = None
    author_site_preflight: bool | None = None
    stop_rule: str | None = None
    stop_eps: float | None = None
    stop_k: int | None = None
    stop_tau: float | None = None
    stop_min_points: int | None = None
    stop_max_screened: int | None = None
    iterative: bool = False
    depth_ceiling: int | None = None


@dataclass
class PathResult:
    run_dir: Any
    exit_code: int
    summary: dict[str, Any] | None = None


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
    cites_query = _checked_cites_query(request, direction, expands=depth >= 1)
    hop_end = _arm_stop(cfg, request, depth)
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
        expand_neighbors=depth >= 1,
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
            search_keywords=_search_keywords_on(cfg, request),
            cites_query=cites_query,
            hop_end=hop_end,
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
    cites_query = _checked_cites_query(request, direction, expands=True)
    _arm_stop(cfg, request, 1)
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
            search_keywords=_search_keywords_on(cfg, request),
            cites_query=cites_query,
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
        expand_neighbors=True,
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
    cites_query = _checked_cites_query(request, direction, expands=depth >= 1)
    hop_end = _arm_stop(cfg, request, depth)
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
            cites_query=cites_query,
            hop_end=hop_end,
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
        expand_neighbors=depth >= 1,
    )


def run_orcid(
    cfg: Config,
    orcid: str | list[str],
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    orcid_getter: Any = None,
) -> PathResult:
    _guard(cfg, request)
    raw_list = [orcid] if isinstance(orcid, str) else list(orcid)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        value = normalize_orcid(str(raw).strip())
        if not value:
            raise SnowballError(f"Invalid ORCID iD: {raw!r}")
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    if not cleaned:
        raise SnowballError("Pass at least one ORCID iD.")
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    keywords = _keyword_caps(cfg, request)
    depth, warning = clamp_depth(_graph_depth(cfg, request))
    cites_query = _checked_cites_query(request, direction, expands=depth >= 1)
    hop_end = _arm_stop(cfg, request, depth)
    backends = _backends(cfg, request)
    dois_by_orcid: dict[str, list[str]] = {item: [] for item in cleaned}
    if "orcid" in backends:
        for item in cleaned:
            try:
                dois_by_orcid[item] = orcid_dois(item, getter=orcid_getter)
            except OrcidError as exc:
                raise SnowballError(str(exc)) from exc
    else:
        console.print("[yellow]orcid backend off; using OpenAlex author filter only[/]")

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int, str]) -> tuple[list[Candidate], list[str]]:
        return orcid_candidates(
            oa,
            cleaned,
            dois_by_orcid=dois_by_orcid,
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
            cites_query=cites_query,
            hop_end=hop_end,
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
        expand_neighbors=depth >= 1,
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
    cites_query = _checked_cites_query(request, direction, expands=depth >= 1)
    hop_end = _arm_stop(cfg, request, depth)
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
            cites_query=cites_query,
            include_seeds=False,
            hop_end=hop_end,
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
        expand_neighbors=depth >= 1,
    )


def _open_stop(
    cfg: Config,
    request: SnowballRequest,
    dest: Any,
    rows: list[Candidate],
    caps: tuple[int, int, str],
    console: Console,
    run_id: str,
) -> None:
    from .stop import SCHEMA, write_state

    params = _stop_params(cfg, request)
    keywords = _keyword_caps(cfg, request)
    seed: dict[str, str] = {}
    for row in rows:
        if row.seed:
            seed = dict(row.seed)
            break
    types = cfg.snowball_types if request.types is None else request.types
    study = cfg.snowball_study_designs if request.study_designs is None else request.study_designs
    state = {
        "schema": SCHEMA,
        "rule": params.rule,
        "eps": params.eps,
        "k": params.k,
        "tau": params.tau,
        "min_points": params.min_points,
        "max_screened": params.max_screened,
        "depth_ceiling": request.depth_ceiling if request.depth_ceiling is not None else 0,
        "iteration": 1,
        "awaiting_labels": True,
        "history": [],
        "stopped_by": None,
        "rationale": None,
        "paused": None,
        "crawl": {
            "direction": request.direction,
            "per_hop_limit": caps[1],
            "per_hop_rank": caps[2],
            "max_candidates": caps[0],
            "year_from": request.year_from,
            "year_to": request.year_to,
            "min_seed_citations": _min_cites(cfg, request),
            "keyword_limit": keywords[0],
            "keyword_hop_limit": keywords[1],
            "keyword_min_score": keywords[2],
            "cites_query": request.cites_query or "",
            "gate": request.gate,
            "seed": seed,
            "types": list(types or ()),
            "study_designs": list(study or ()),
            "oa_only": cfg.snowball_oa_only if request.oa_only is None else request.oa_only,
            "venue_include": list(
                cfg.snowball_venue_include if request.venue_include is None else request.venue_include
            ),
            "venue_exclude": list(
                cfg.snowball_venue_exclude if request.venue_exclude is None else request.venue_exclude
            ),
            "languages": list(cfg.snowball_languages if request.languages is None else request.languages),
        },
    }
    write_state(dest / "stop.json", state)
    _touch_stop_summary(dest, state)
    console.print(
        f"[dim]stop rule {params.rule} · depth ceiling "
        f"{state['depth_ceiling']} · hop caps still apply[/]"
    )


def _touch_stop_summary(dest: Any, state: dict[str, Any]) -> None:
    path = dest / "summary.json"
    if not path.is_file():
        return
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["stop_rule"] = state.get("rule")
    summary["stop_awaiting_labels"] = bool(state.get("awaiting_labels"))
    summary["stopped_by"] = state.get("stopped_by")
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


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
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
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
        raise SnowballError(f"Run {run_id} has no stopping rule. It was a one-shot crawl.")
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
    history.append(IterationStat(iteration=iteration, screened=len(batch), included=included))
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
        {"iteration": item.iteration, "screened": item.screened, "included": item.included}
        for item in history
    ]
    chosen = terminating(decisions, params.rule)
    if chosen is not None:
        state["stopped_by"] = chosen.rule
        state["rationale"] = chosen.rationale
        state["awaiting_labels"] = False
        write_state(dest / "stop.json", state)
        write_queue(cfg.state_dir, run_id, rows, client or _openalex_client(cfg), library_unread=False)
        _touch_stop_summary(dest, state)
        console.print(chosen.rationale)
        return PathResult(dest, 0, summary={"stopped_by": chosen.rule, "rationale": chosen.rationale})

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
        console.print(f"[yellow]Partial hop kept[/] · paperful snowball resume {run_id}")
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
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    import json
    from datetime import datetime, timezone

    from .crawl import _dedupe, continue_deferred

    dest = cfg.state_dir / "snowball" / run_id
    path = dest / "deferred.json"
    if not path.is_file():
        if not (dest / "candidates.jsonl").is_file():
            raise SnowballError(f"No snowball queue for run {run_id!r}.")
        return _resume_saved_queue(cfg, run_id, request, console=console, backend=backend)
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
            per_hop_limit=int(deferred.get("per_hop_limit") or cfg.snowball_per_hop_limit),
            direction=str(deferred.get("direction") or request.direction or DEFAULT_DIRECTION),
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
        raise SnowballError(f"Library was not read. Refusing to create items. {exc}") from exc
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
            finder = _library_lookup(
                lib, scope=_apply_fingerprint_scope(request), collection=collection
            )
        except Exception as exc:
            raise SnowballError(f"Library was not read. Refusing to create items. {exc}") from exc
    assert lib is not None and finder is not None
    _mark_exists(kept, finder, version_of=_version_of(cfg, request))
    creatable = [row for row in kept if row.status == "new"]
    if not creatable:
        console.print("nothing to create (all keep rows already in library)")
        write_report(dest, {"created": 0, "skipped_exists": len(kept), "attach_ok": 0, "attach_deferred": 0})
        return PathResult(
            dest,
            0,
            summary={"created": 0, "skipped_exists": len(kept), "attach_ok": 0, "attach_deferred": 0},
        )

    note = cfg.snowball_note_provenance if request.note_provenance is None else request.note_provenance
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


def _print_fetch_result(
    console: Console, report: dict[str, Any], *, sought: int, collection: str
) -> None:
    console.print(
        f"downloaded {report.get('downloaded', 0)} · attached {report['attach_ok']} · "
        f"deferred {report['attach_deferred']}"
    )
    advice = low_download_advice(
        downloaded=int(report.get("attach_ok") or 0),
        sought=sought,
        collection=collection,
    )
    if advice:
        console.print(f"[yellow]{advice}[/]")


def _extra_tags(cfg: Config, request: SnowballRequest) -> list[str]:
    return merge_tags(cfg.snowball_default_tags, request.tags)


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


def _search_keywords_on(cfg: Config, request: SnowballRequest) -> bool:
    if request.search_keywords is None:
        return bool(cfg.snowball_search_keywords)
    return bool(request.search_keywords)


def _checked_cites_query(request: SnowballRequest, direction: str, *, expands: bool) -> str:
    """OpenAlex text search for references and cited-by. Empty when unset."""
    query = (request.cites_query or "").strip()
    if not query:
        return ""
    from .expand import expand_search_term

    expanded, notices = expand_search_term(query)
    query = expanded or query
    for note in notices:
        Console(highlight=False).print(f"[yellow]{note}[/]")
    sides = direction_sides(direction)
    if "refs" not in sides and "cites" not in sides:
        raise SnowballError("--cites-query needs a direction that includes refs or cites.")
    if not expands:
        raise SnowballError("--cites-query needs depth of at least 1.")
    return query


def _rank(value: str | None, default: str) -> str:
    raw = default if value is None else value
    try:
        return parse_per_hop_rank(raw)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc


def _arm_stop(cfg: Config, request: SnowballRequest, depth: int) -> int | None:
    """Turn on one-hop iteration. Returns ``hop_end`` when the ceiling is deeper than 1."""
    params = _stop_params(cfg, request)
    request.iterative = params.rule != "off"
    if not request.iterative:
        request.depth_ceiling = None
        return None
    request.depth_ceiling = depth
    if depth > 1:
        return 1
    return None


def _stop_params(cfg: Config, request: SnowballRequest):
    from .stop import parse_stop_params

    try:
        return parse_stop_params(
            rule=cfg.snowball_stop_rule if request.stop_rule is None else request.stop_rule,
            eps=cfg.snowball_stop_eps if request.stop_eps is None else request.stop_eps,
            k=cfg.snowball_stop_k if request.stop_k is None else request.stop_k,
            tau=cfg.snowball_stop_tau if request.stop_tau is None else request.stop_tau,
            min_points=(
                cfg.snowball_stop_min_points
                if request.stop_min_points is None
                else request.stop_min_points
            ),
            max_screened=(
                cfg.snowball_stop_max_screened
                if request.stop_max_screened is None
                else request.stop_max_screened
            ),
        )
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
    after = request.dedupe_after
    if after is not None:
        from ..config import parse_dedupe_after

        try:
            parse_dedupe_after(after)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    _backends(cfg, request)
    if request.stop_rule is not None or request.stop_eps is not None or request.stop_k is not None:
        _stop_params(cfg, request)
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
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    types = cfg.snowball_types if request.types is None else request.types
    oa_only = cfg.snowball_oa_only if request.oa_only is None else request.oa_only
    venue_include = (
        cfg.snowball_venue_include if request.venue_include is None else request.venue_include
    )
    venue_exclude = (
        cfg.snowball_venue_exclude if request.venue_exclude is None else request.venue_exclude
    )
    languages = cfg.snowball_languages if request.languages is None else request.languages
    study_designs = (
        cfg.snowball_study_designs if request.study_designs is None else request.study_designs
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
        cfg.snowball_study_designs if request.study_designs is None else request.study_designs
    )
    oa.study_designs = tuple(designs or ())
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
        oa.epmc_getter = lambda doi, _cache=oa.epmc_cache_dir: europepmc_work(doi, cache_dir=_cache)
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
    want_preflight = (
        cfg.snowball_author_site_preflight
        if request.author_site_preflight is None
        else request.author_site_preflight
    )
    if want_preflight:
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
    _print_table(console, rows)
    crawl_fail_n = len(failed) if failed else 0
    if oa.deferred:
        exit_code = EXIT_PARTIAL
        console.print(f"[yellow]Partial queue kept[/] · paperful snowball resume {run_id}")
    else:
        exit_code = 0
    if request.iterative and not oa.deferred:
        _open_stop(cfg, request, dest, rows, caps, console, run_id)
    if gate in {"dry-run", "approve-batch"}:
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
    if library_unread or lib is None:
        detail = f" { _unread_error }" if _unread_error else ""
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
        exit_code = batch_exit(
            ok=created_n, failed=crawl_fail_n + create_fail_n
        )
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


def _library_lookup(backend: Any, *, scope: str, collection: str) -> Lookup:
    return library_lookup(backend, scope=scope, collection=collection)


def _apply_fingerprint_scope(request: SnowballRequest) -> str:
    """Delayed apply fingerprints the full library unless --dedupe-scope is set."""
    scope = (request.dedupe_scope or "library").strip()
    return scope if scope in {"library", "collection", "none"} else "library"


def _fingerprint_rows(
    cfg: Config,
    request: SnowballRequest,
    rows: list[Candidate],
    *,
    backend: Any,
    console: Console,
) -> tuple[Any, bool]:
    """Mark exists/version on ``rows``. Returns (backend, library_unread)."""
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    if scope not in {"library", "collection", "none"}:
        raise SnowballError("dedupe_scope must be library, collection, or none.")
    lib = backend
    unread = False
    if scope == "none":
        console.print("[yellow]dedupe_scope none: not checking the library[/]")
        return lib, False
    finder = None
    try:
        lib = lib or get_backend(cfg)
        finder = _library_lookup(lib, scope=scope, collection=request.collection)
    except Exception:
        return lib, True
    try:
        _mark_exists(rows, finder, version_of=_version_of(cfg, request))
    except Exception:
        unread = True
    return lib, unread


def _maybe_dedupe_after(
    cfg: Config,
    request: SnowballRequest,
    backend: Any,
    collection: str,
    console: Console,
) -> None:
    from ..config import parse_dedupe_after

    raw = cfg.snowball_dedupe_after if request.dedupe_after is None else request.dedupe_after
    try:
        mode = parse_dedupe_after(raw)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    if mode == "off" or backend is None or not (collection or "").strip():
        return
    from ..dedupe import apply_merge, attach_merge_previews, classify, write_pack

    try:
        col = backend.resolve_collection(collection.strip())
        items = backend.items_in_scope([col.key])
    except Exception as exc:
        console.print(f"[yellow]dedupe_after skipped: {exc}[/]")
        return
    groups = classify(items)
    attach_merge_previews(backend, groups)
    json_path, _md = write_pack(
        cfg.state_dir, collection, groups, phase="all", n_items=len(items)
    )
    console.print(f"dedupe classified {len(groups)} groups · {json_path}")
    if mode != "apply":
        return
    merged, errors = apply_merge(
        backend,
        groups,
        apply_medium=False,
        audit_path=cfg.state_dir / "dedupe-applied.jsonl",
        scope=collection,
        pack=json_path,
    )
    console.print(f"dedupe merged {merged}")
    for err in errors:
        console.print(f"[yellow]{err}[/]")


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
        url = row.biblio.get("url") or row.biblio.get("landing_page_url")
        isbn = row.ids.get("isbn") or row.biblio.get("isbn")
        report = row.ids.get("report") or row.biblio.get("report_number")
        found = _call_lookup(
            lookup,
            doi,
            title,
            year,
            url=url,
            isbn=isbn,
            report_number=report,
        )
        if found:
            _set_exists(
                row,
                found,
                doi=doi,
                title=title,
                year=year,
                isbn=isbn,
                report_number=report,
                url=url,
            )
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
    lookup: Lookup,
    doi: str | None,
    title: str | None,
    year: int | None,
    **extra: Any,
) -> Any:
    try:
        return lookup(doi, title, year, **extra)  # type: ignore[call-arg]
    except TypeError:
        pass
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
    isbn: str | None = None,
    report_number: str | None = None,
    url: str | None = None,
) -> None:
    from ..greyid import grey_token, normalize_isbn, normalize_report_number, registrable_host

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
    elif kind == "grey":
        host = registrable_host(url)
        row.exists_match = {
            "item_key": key,
            "grey": grey_token(title, year, host),
        }
    elif kind == "isbn":
        row.exists_match = {"item_key": key, "isbn": normalize_isbn(isbn)}
    elif kind == "report":
        row.exists_match = {
            "item_key": key,
            "report": normalize_report_number(report_number),
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


def _blocked_dois(paused: dict[str, list[str]]) -> set[str]:
    return {k for ids in paused.values() for doi in ids if (k := doi_key(doi))}


def _settled_rows(rows: list[Candidate], blocked: set[str]) -> list[Candidate]:
    return [row for row in rows if doi_key(row.ids.get("doi")) not in blocked]


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
    europepmc_getter: Any = None,
    europepmc_cache: Any = None,
    pdf_getter: Any = None,
    expand_neighbors: bool = True,
) -> tuple[list[Candidate], dict[str, list[str]]]:
    del console, request
    if crossref_getter is None and live and "crossref" in backends:

        def crossref_getter(doi: str, _email: str = cfg.email) -> dict | None:
            return crossref_work(doi, email=_email)

    if s2_getter is None and live and "semanticscholar" in backends:
        key = s2_api_key()
        cache = cfg.state_dir / "snowball" / "cache"

        def s2_getter(doi: str, _cache: Any = cache, _key: str = key) -> dict | None:
            return s2_paper(doi, cache_dir=_cache, api_key=_key)
    if live and "europepmc" in backends and europepmc_cache is None:
        europepmc_cache = cfg.state_dir / "snowball" / "cache" / "europepmc"
    if europepmc_getter is None and live and "europepmc" in backends:
        from .europepmc import europepmc_work

        cache = europepmc_cache

        def europepmc_getter(doi: str, _cache: Any = cache) -> dict | None:
            return europepmc_work(doi, cache_dir=_cache)
    if pdf_getter is None and live and "pdf" in backends:
        from .bibliography import pdf_payload_for_row

        def pdf_getter(doi: str, _rows: list[Candidate] = rows) -> dict | None:  # type: ignore[no-redef]
            match = next(
                (row for row in _rows if doi_key(row.ids.get("doi")) == doi_key(doi)),
                None,
            )
            return pdf_payload_for_row(match) if match is not None else None

    paused = run_fill_pass(
        rows,
        backends,
        crossref_getter=crossref_getter,
        s2_getter=s2_getter,
        europepmc_getter=europepmc_getter,
        pdf_getter=pdf_getter,
        per_hop_limit=per_hop_limit,
        direction=direction,
        tally=tally,
        europepmc_cache=europepmc_cache if live and "europepmc" in backends else None,
        expand_neighbors=expand_neighbors,
    )
    return rows, paused


def _write_cached_pdfs(cfg: Config, items: list[Any], rows: list[Candidate]) -> None:
    import hashlib

    from pathlib import Path

    from ..store import save_pdf

    by_doi = {(row.ids.get("doi") or "").lower(): row for row in rows}
    for item in items:
        row = by_doi.get((getattr(item, "doi", None) or "").lower())
        if row is None:
            continue
        raw = str(row.biblio.get("cached_pdf") or "")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        content = path.read_bytes()
        save_pdf(cfg.out_dir, item, content, hashlib.md5(content).hexdigest())


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
    if request.collection.strip():
        meta["target_collection"] = request.collection.strip()
    cites_query = (request.cites_query or "").strip()
    if cites_query:
        meta["cites_query"] = cites_query
    designs = (
        cfg.snowball_study_designs if request.study_designs is None else request.study_designs
    )
    if designs:
        meta["study_designs"] = list(designs)
    map_cats = (
        cfg.snowball_map_categories
        if request.map_categories is None
        else request.map_categories
    )
    meta["map_categories"] = list(map_cats or ())
    map_defs = (
        cfg.snowball_map_category_defs
        if request.map_category_defs is None
        else request.map_category_defs
    )
    if map_defs:
        meta["map_category_defs"] = [dict(item) for item in map_defs]
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
