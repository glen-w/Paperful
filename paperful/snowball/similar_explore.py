"""Build a Similar map queue: gather a pool, score it, and write the run.

The pool comes from the live OpenAlex API, a self-hosted snapshot store
(``[openalex_store]``), or both, depending on ``[similar_map].source``. Each
gathering step can fail on its own; the map is built from whatever arrived, and
the reasons go into ``warnings`` on the graph and the run summary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from ..config import Config
from ..resolve import normalize_doi
from .candidate import Candidate
from .citation_graph import CitationGraphError, build_graph, work_node_id, write_graph_file
from .openalex import (
    OpenAlexBudgetExceeded,
    OpenAlexClient,
    OpenAlexError,
    referenced_ids,
    short_id,
    work_to_candidate,
)
from .similar_settings import SimilarSettings, for_config
from .similarity_map import (
    citer_index,
    connect_to_seed,
    derivative_works,
    pairwise_links,
    prior_works,
    ref_set,
    score_to_seed,
)

NO_CITES_INDEX = (
    "Your OpenAlex store has no cites index, so citing papers were skipped and "
    "co-citation is weak. Build one with `paperful openalex-store build-cites`."
)


def similar_client(
    cfg: Config,
    settings: SimilarSettings,
    *,
    client: OpenAlexClient | None = None,
) -> tuple[OpenAlexClient, list[str]]:
    """OpenAlex client for ``settings.source``, plus warnings about the source."""
    from .local_openalex import OpenAlexStoreError, store_from_config

    warnings: list[str] = []
    if client is not None:
        if settings.source == "store":
            if client.store is None:
                raise CitationGraphError(
                    "Similar map source is set to store, but [openalex_store] is not configured."
                )
            client.use_store_only()
        elif settings.source == "api":
            client.store = None
        return client, warnings
    store = None
    if settings.source != "api":
        try:
            store = store_from_config(cfg)
        except OpenAlexStoreError as exc:
            if settings.source == "store":
                raise CitationGraphError(f"OpenAlex store is misconfigured: {exc}") from exc
            warnings.append(f"OpenAlex store skipped ({exc}); using the live API.")
    if settings.source == "store" and store is None:
        raise CitationGraphError(
            "Similar map source is set to store, but [openalex_store] is not configured."
        )
    built = OpenAlexClient(email=cfg.email, store=store)
    if settings.source == "store":
        built.use_store_only()
    return built, warnings


def _store_can_cite(client: OpenAlexClient) -> bool:
    return client.store is not None and bool(getattr(client.store, "has_cites_index", False))


class _Pool:
    """Pool works by OpenAlex short id, plus what went wrong while gathering."""

    def __init__(self, seed_oa: str) -> None:
        self.seed_oa = seed_oa
        self.works: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.budget_hit = False
        self.steps: dict[str, int] = {}

    def add(self, step: str, rows: list[dict[str, Any]] | None) -> None:
        added = 0
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            oa = short_id(str(row.get("id") or ""))
            if oa and oa != self.seed_oa and oa not in self.works:
                self.works[oa] = row
                added += 1
        self.steps[step] = self.steps.get(step, 0) + added

    def run(self, step: str, label: str, fn: Callable[[], list[dict[str, Any]]]) -> None:
        """Run one gathering step. Failures become warnings; partial rows are kept."""
        try:
            self.add(step, fn())
        except OpenAlexBudgetExceeded as exc:
            self.budget_hit = True
            self.add(step, list(getattr(exc, "partial", None) or []))
            partners = getattr(exc, "coupling_works", None)
            if isinstance(partners, dict):
                self.add(step, list(partners.values()))
            self.warnings.append(f"{label}: stopped early ({exc}).")
        except (OpenAlexError, httpx.HTTPError) as exc:
            self.warnings.append(f"{label}: failed ({exc}).")


def similar_pool(
    client: OpenAlexClient,
    work: dict[str, Any],
    settings: SimilarSettings,
) -> _Pool:
    """Seed refs, its citers, coupling partners, and co-citation partners."""
    from .similar import collect_partners, reference_sample

    seed_oa = short_id(str(work.get("id") or ""))
    pool = _Pool(seed_oa)
    can_cite = not client.store_only or _store_can_cite(client)
    if not can_cite:
        pool.warnings.append(NO_CITES_INDEX)

    ids = referenced_ids(work, settings.ref_cap) if settings.ref_cap else []
    if ids:
        pool.run("references", "References", lambda: client.works_by_ids(ids))
    if can_cite and seed_oa and settings.citer_cap:
        pool.run(
            "citers",
            "Citing papers",
            lambda: client.works_citing(
                seed_oa, limit=settings.citer_cap, sort="cited_by_count:desc"
            ),
        )
    if can_cite and settings.partner_refs:
        sample = reference_sample([work], limit=settings.partner_refs)

        def partners() -> list[dict[str, Any]]:
            ranked, _ = collect_partners(
                client,
                sample,
                per_ref=settings.partners_per_ref,
                year_from=None,
                year_to=None,
            )
            return [row for _, row in ranked]

        if sample:
            pool.run("coupling", "Papers sharing references", partners)
    if seed_oa and settings.cocited_cap:
        own = set(referenced_ids(work))
        counts: dict[str, int] = {}
        for row in list(pool.works.values()):
            cited = referenced_ids(row)
            if seed_oa not in cited:
                continue
            for sid in cited:
                if sid != seed_oa and sid not in pool.works and sid not in own:
                    counts[sid] = counts.get(sid, 0) + 1
        top = sorted(counts, key=lambda sid: (-counts[sid], sid))[: settings.cocited_cap]
        if top:
            pool.run("cocited", "Co-cited papers", lambda: client.works_by_ids(top))
    return pool


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"similar-{stamp}"


def _in_years(work: dict[str, Any], settings: SimilarSettings) -> bool:
    year = work.get("publication_year")
    if year is None:
        return settings.year_from is None and settings.year_to is None
    try:
        value = int(year)
    except (TypeError, ValueError):
        return False
    if settings.year_from is not None and value < settings.year_from:
        return False
    if settings.year_to is not None and value > settings.year_to:
        return False
    return True


def _extra(work: dict[str, Any] | None, oa: str, count: int) -> dict[str, Any]:
    work = work or {}
    doi = normalize_doi(str(work.get("doi") or "")) or ""
    year = work.get("publication_year")
    return {
        "id": f"doi:{doi.lower()}" if doi else f"openalex:{oa}",
        "openalex": oa,
        "doi": doi,
        "title": str(work.get("display_name") or ""),
        "year": int(year) if isinstance(year, int) else None,
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "count": count,
    }


def start_similar_explore(
    cfg: Config,
    client: OpenAlexClient | None = None,
    *,
    query: str = "",
    node_id: str = "",
    settings: SimilarSettings | None = None,
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Seed a similarity map: co-citation plus shared references."""
    from .command import _library_lookup, _mark_exists, get_backend
    from .explore import resolve_work
    from .queue import write_queue

    opts = settings or for_config(cfg)
    client, warnings = similar_client(cfg, opts, client=client)
    if client.store_only and not node_id.strip() and not normalize_doi(query or ""):
        raise CitationGraphError(
            "With the Similar map source set to store, paste a DOI. Title search needs the live OpenAlex API."
        )
    try:
        work = resolve_work(client, query=query, node_id=node_id)
    except OpenAlexBudgetExceeded as exc:
        raise CitationGraphError(f"OpenAlex could not look up this paper ({exc}).") from exc
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not look up this paper.") from exc
    seed_oa = short_id(str(work.get("id") or ""))
    if not seed_oa:
        raise CitationGraphError("OpenAlex has no id for this paper.")
    api_before = client.requests
    pool = similar_pool(client, work, opts)
    warnings.extend(pool.warnings)

    refs = {oa: ref_set(row) for oa, row in pool.works.items()}
    refs[seed_oa] = ref_set(work)
    citers = citer_index(refs)
    eligible = [oa for oa, row in pool.works.items() if _in_years(row, opts)]
    scores = score_to_seed(
        seed_oa, refs, citers, eligible, coupling_weight=opts.coupling_weight
    )
    scores = {oa: hit for oa, hit in scores.items() if hit[0] >= opts.min_similarity}
    cited_by = {oa: int(row.get("cited_by_count") or 0) for oa, row in pool.works.items()}
    ranked = sorted(scores, key=lambda oa: (-scores[oa][0], -cited_by.get(oa, 0), oa))
    if not ranked:
        hint = " " + " ".join(warnings) if warnings else ""
        raise CitationGraphError(
            "Not enough shared citations to build a similarity map for this paper." + hint
        )

    run_id = _new_run_id()
    seed_label = (query or node_id or work_node_id(work)).strip()
    seed = {"type": "explore", "value": seed_label[:200]}
    title = str(work.get("display_name") or seed_label)
    seed_row = work_to_candidate(
        work, run_id=run_id, seed=seed, hop=0, direction="explore",
        why="Similar map origin", gate="dry-run",
    )
    seed_row.biblio["similarity"] = 1.0

    # Build rows for more than we need, so dropping library papers or duplicate
    # DOIs still leaves a full map.
    window = ranked[: max(opts.nodes * 3, opts.nodes + 20)]
    candidates: list[tuple[str, Candidate]] = []
    for oa in window:
        score, shared_refs, co_citing = scores[oa]
        row = work_to_candidate(
            pool.works[oa], run_id=run_id, seed=seed, hop=1, direction="similar",
            why=f"similar to {title[:80]}: {co_citing} co-citing, {shared_refs} shared refs",
            gate="dry-run",
        )
        row.biblio["similarity"] = round(score, 4)
        candidates.append((oa, row))
    try:
        backend = get_backend(cfg)
        finder = _library_lookup(backend, scope="library", collection="")
        _mark_exists([seed_row] + [row for _, row in candidates], finder)
    except Exception:
        if opts.hide_in_library:
            warnings.append("Could not read the library, so library papers were not hidden.")
    seen = {seed_row.identity}
    picked: list[tuple[str, Candidate]] = []
    hidden = 0
    for oa, row in candidates:
        if not row.identity or row.identity in seen:
            continue
        if opts.hide_in_library and (row.status == "exists" or row.exists_match):
            hidden += 1
            continue
        seen.add(row.identity)
        picked.append((oa, row))
        if len(picked) >= opts.nodes:
            break
    if not picked:
        raise CitationGraphError(
            "Every similar paper is already in your library. Turn off Hide library papers to see them."
        )

    ids = [seed_oa] + [oa for oa, _ in picked]
    links = pairwise_links(
        ids, refs, citers,
        k=opts.peers, floor=opts.min_similarity, coupling_weight=opts.coupling_weight,
    )
    connect_to_seed(seed_oa, ids, links, scores)
    by_oa: dict[str, Candidate] = {seed_oa: seed_row, **dict(picked)}
    for row in by_oa.values():
        row.biblio["sim_links"] = []
    for (a, b), (score, shared_refs, co_citing) in links.items():
        for here, there in ((a, b), (b, a)):
            by_oa[here].biblio["sim_links"].append(
                {
                    "peer": by_oa[there].identity,
                    "score": round(score, 4),
                    "shared_refs": shared_refs,
                    "co_citing": co_citing,
                }
            )

    prior = prior_works(ids, refs, limit=opts.prior_works)
    missing = [oa for oa, _ in prior if oa not in pool.works]
    fetched: dict[str, dict[str, Any]] = {}
    if missing:
        extra_pool = _Pool(seed_oa)
        extra_pool.run("prior", "Prior works", lambda: client.works_by_ids(missing))
        fetched = extra_pool.works
        warnings.extend(extra_pool.warnings)
    derivative = derivative_works(ids, refs, limit=opts.derivative_works)
    report = {
        "settings": opts.to_dict(),
        "source": "store" if client.store_only else ("store+api" if client.store else "api"),
        "api_calls": client.requests - api_before,
        "pool_size": len(pool.works),
        "pool_steps": dict(pool.steps),
        "scored": len(ranked),
        "hidden_in_library": hidden,
        "budget_hit": pool.budget_hit,
        "warnings": warnings,
        "color": opts.color,
        "prior": [
            _extra(pool.works.get(oa) or fetched.get(oa), oa, n)
            for oa, n in prior
            if pool.works.get(oa) or fetched.get(oa)
        ],
        "derivative": [_extra(pool.works.get(oa), oa, n) for oa, n in derivative],
    }
    seed_row.biblio["similar_report"] = report
    rows = list(by_oa.values())
    write_queue(
        cfg.state_dir,
        run_id,
        rows,
        client,
        library_unread=False,
        meta={
            "mode": "similar",
            "pool_size": report["pool_size"],
            "budget_hit": report["budget_hit"],
            "similar": {k: v for k, v in report.items() if k not in ("prior", "derivative")},
            "map_categories": list(map_categories or ()),
            "map_category_defs": list(map_category_defs or ()),
        },
    )
    graph = build_graph(
        rows,
        run_id=run_id,
        map_categories=map_categories,
        map_category_defs=map_category_defs,
    )
    write_graph_file(cfg.state_dir / "snowball" / run_id, graph)
    return run_id, graph
