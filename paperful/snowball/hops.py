"""Hop expansion steps for snowball crawl."""
from __future__ import annotations

from typing import Any

from .candidate import Candidate
from .openalex import OpenAlexClient


def hop_refs(
    client: OpenAlexClient,
    frontier: list[dict[str, Any]],
    rows: list[Candidate],
    next_works: list[dict[str, Any]],
    seen_oa: set[str],
    *,
    hop: int,
    depth: int,
    direction: str,
    run_id: str,
    seed: dict[str, str],
    gate: str,
    per_hop_limit: int,
    rank: str,
    year_from: int | None,
    year_to: int | None,
    why_prefix: str,
    min_seed_citations: int,
) -> bool:
    """Expand one hop of references. True when the crawl must stop."""
    from . import crawl as c

    unique_ids = c.unique_ids
    referenced_ids = c.referenced_ids
    recover_referenced_works = c.recover_referenced_works
    FillPaused = c.FillPaused
    _defer = c._defer
    _emit = c._emit
    _cites_query = c._cites_query
    _refs_matching_search = c._refs_matching_search
    _mark_year = c._mark_year
    _with_query = c._with_query
    _cites_why = c._cites_why
    _cite_fetch_limit = c._cite_fetch_limit
    _cite_sort = c._cite_sort
    work_to_candidate = c.work_to_candidate
    short_id = c.short_id
    sample_ids = c.sample_ids
    select_works_by_citations = c.select_works_by_citations


    query = _cites_query(client)
    per_work_ids: list[list[str]] = []
    fetch_ids: list[str] = []
    fetch_set: set[str] = set()
    recovered_by_index: dict[int, list[dict[str, Any]]] = {}
    for index, work in enumerate(frontier):
        unseen = unique_ids(
            [item for item in referenced_ids(work, 0) if item not in seen_oa]
        )
        if not unseen:
            client.stage = f"hop {hop}/{depth} references recover"
            try:
                recovered = recover_referenced_works(client, work)
            except FillPaused as exc:
                _defer(
                    client,
                    exc,
                    kind="fill",
                    backend=str(getattr(exc, "backend", "") or "semanticscholar"),
                    remaining_ids=[],
                    hop=hop,
                    depth=depth,
                    direction=direction,
                    run_id=run_id,
                    seed=seed,
                    gate=gate,
                    per_hop_limit=per_hop_limit,
                    per_hop_rank=rank,
                    year_from=year_from,
                    year_to=year_to,
                    why_prefix=why_prefix,
                    min_seed_citations=min_seed_citations,
                )
                _emit(client, rows)
                return True
            if recovered:
                recovered_by_index[index] = _refs_matching_search(client, recovered, query)
            per_work_ids.append([])
            continue
        if rank == "random" and per_hop_limit > 0:
            unseen = sample_ids(unseen, per_hop_limit)
        per_work_ids.append(unseen)
        for ref_id in unseen:
            if ref_id not in fetch_set:
                fetch_set.add(ref_id)
                fetch_ids.append(ref_id)
    by_id: dict[str, dict[str, Any]] = {}
    if fetch_ids:
        client.stage = f"hop {hop}/{depth} references"
        label = f"hop {hop}/{depth} references · {len(fetch_ids)} ids"
        if query:
            label = f"{label} · {query}"
        client.note(label)
        try:
            children = client.works_by_ids(fetch_ids, search=query or None)
        except Exception as exc:
            children = list(getattr(exc, "partial", []) or [])
            _defer(
                client,
                exc,
                kind="refs",
                remaining_ids=list(getattr(exc, "pending_ids", []) or []),
                hop=hop,
                depth=depth,
                direction=direction,
                run_id=run_id,
                seed=seed,
                gate=gate,
                per_hop_limit=per_hop_limit,
                per_hop_rank=rank,
                year_from=year_from,
                year_to=year_to,
                why_prefix=why_prefix,
                min_seed_citations=min_seed_citations,
            )
        by_id = {
            short_id(str(child.get("id") or "")): child
            for child in children
            if child.get("id")
        }
    if fetch_ids or recovered_by_index:
        for index, ids in enumerate(per_work_ids):
            if index in recovered_by_index:
                resolved = list(recovered_by_index[index])
                if rank == "random":
                    resolved = select_works_by_citations(resolved, per_hop_limit, "random")
                else:
                    resolved = select_works_by_citations(
                        resolved,
                        per_hop_limit,
                        rank,
                        id_of=lambda work: short_id(str(work.get("id") or "")),
                    )
                source_why = {
                    "semanticscholar": _with_query(f"s2 ref of {why_prefix}", query),
                    "pdf": _with_query(f"pdf ref of {why_prefix}", query),
                }
                for child in resolved:
                    child_id = short_id(str(child.get("id") or ""))
                    if not child_id or child_id in seen_oa:
                        continue
                    seen_oa.add(child_id)
                    recovery = str(child.get("_recovery") or "pdf")
                    row = work_to_candidate(
                        child,
                        run_id=run_id,
                        seed=seed,
                        hop=hop,
                        direction="refs",
                        why=source_why.get(recovery, _with_query(f"ref of {why_prefix}", query)),
                        gate=gate,
                    )
                    row.provenance["backend"] = recovery
                    if _mark_year(row, year_from, year_to):
                        next_works.append(child)
                    rows.append(row)
                continue
            resolved = [by_id[item] for item in ids if item in by_id]
            if rank != "random":
                resolved = select_works_by_citations(
                    resolved,
                    per_hop_limit,
                    rank,
                    id_of=lambda work: short_id(str(work.get("id") or "")),
                )
            for child in resolved:
                child_id = short_id(str(child.get("id") or ""))
                if not child_id or child_id in seen_oa:
                    continue
                seen_oa.add(child_id)
                row = work_to_candidate(
                    child,
                    run_id=run_id,
                    seed=seed,
                    hop=hop,
                    direction="refs",
                    why=_with_query(f"ref of {why_prefix}", query),
                    gate=gate,
                )
                if _mark_year(row, year_from, year_to):
                    next_works.append(child)
                rows.append(row)
        _emit(client, rows)
        if client.deferred:
            return True
    return False


def hop_cites(
    client: OpenAlexClient,
    frontier: list[dict[str, Any]],
    rows: list[Candidate],
    next_works: list[dict[str, Any]],
    seen_oa: set[str],
    *,
    hop: int,
    depth: int,
    direction: str,
    run_id: str,
    seed: dict[str, str],
    gate: str,
    per_hop_limit: int,
    rank: str,
    year_from: int | None,
    year_to: int | None,
    why_prefix: str,
    min_seed_citations: int,
) -> bool:
    """Expand one hop of citing works. True when the crawl must stop."""
    from . import crawl as c

    unique_ids = c.unique_ids
    referenced_ids = c.referenced_ids
    recover_referenced_works = c.recover_referenced_works
    FillPaused = c.FillPaused
    _defer = c._defer
    _emit = c._emit
    _cites_query = c._cites_query
    _refs_matching_search = c._refs_matching_search
    _mark_year = c._mark_year
    _with_query = c._with_query
    _cites_why = c._cites_why
    _cite_fetch_limit = c._cite_fetch_limit
    _cite_sort = c._cite_sort
    work_to_candidate = c.work_to_candidate
    short_id = c.short_id
    sample_ids = c.sample_ids
    select_works_by_citations = c.select_works_by_citations


    citing_seeds = [
        work
        for work in frontier
        if short_id(str(work.get("id") or ""))
        and not (
            min_seed_citations
            and int(work.get("cited_by_count") or 0) < min_seed_citations
        )
    ]
    if citing_seeds:
        query = _cites_query(client)
        client.stage = f"hop {hop}/{depth} cited-by"
        label = f"hop {hop}/{depth} cited-by · {len(citing_seeds)} seeds"
        if query:
            label = f"{label} · {query}"
        client.note(label)
        if client.tally is not None:
            client.tally.track(len(citing_seeds))
        cite_limit = _cite_fetch_limit(per_hop_limit, rank)
        cite_sort = _cite_sort(rank)
        for index, work in enumerate(citing_seeds, start=1):
            oa = short_id(str(work.get("id") or ""))
            client.stage = f"hop {hop}/{depth} cited-by {index}/{len(citing_seeds)} {oa}"
            client.touch()
            try:
                citing = client.works_citing(
                    oa,
                    limit=cite_limit,
                    year_from=year_from,
                    year_to=year_to,
                    sort=cite_sort,
                    search=query or None,
                )
            except Exception as exc:
                remaining = [
                    short_id(str(item.get("id") or ""))
                    for item in citing_seeds[index - 1 :]
                ]
                _defer(
                    client,
                    exc,
                    kind="cites",
                    remaining_ids=[item for item in remaining if item],
                    hop=hop,
                    depth=depth,
                    direction=direction,
                    run_id=run_id,
                    seed=seed,
                    gate=gate,
                    per_hop_limit=per_hop_limit,
                    per_hop_rank=rank,
                    year_from=year_from,
                    year_to=year_to,
                    why_prefix=why_prefix,
                    min_seed_citations=min_seed_citations,
                )
                _emit(client, rows)
                return True
            if rank == "random":
                citing = select_works_by_citations(citing, per_hop_limit, "random")
            kept = 0
            for child in citing:
                child_id = short_id(str(child.get("id") or ""))
                if not child_id or child_id in seen_oa:
                    continue
                seen_oa.add(child_id)
                row = work_to_candidate(
                    child,
                    run_id=run_id,
                    seed=seed,
                    hop=hop,
                    direction="cites",
                    why=_cites_why(why_prefix, query),
                    gate=gate,
                )
                if _mark_year(row, year_from, year_to):
                    next_works.append(child)
                    kept += 1
                rows.append(row)
                if per_hop_limit > 0 and kept >= per_hop_limit:
                    break
            if client.tally is not None:
                client.tally.advance(1)
            _emit(client, rows)
    return False


def hop_keywords(
    client: OpenAlexClient,
    frontier: list[dict[str, Any]],
    rows: list[Candidate],
    next_works: list[dict[str, Any]],
    seen_oa: set[str],
    **kwargs: Any,
) -> bool:
    from . import crawl as c

    return c._keyword_neighbours(client, frontier, rows, next_works, seen_oa, **kwargs)


def hop_similar(
    client: OpenAlexClient,
    frontier: list[dict[str, Any]],
    rows: list[Candidate],
    seen_oa: set[str],
    **kwargs: Any,
) -> bool:
    from . import crawl as c

    return c._similar_neighbours(client, frontier, rows, seen_oa, **kwargs)

