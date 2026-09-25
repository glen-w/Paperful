"""Turn OpenAlex payloads into a deduped candidate list."""

from __future__ import annotations

from typing import Any

from ..resolve import normalize_doi
from .candidate import Candidate
from .expand import direction_sides, sample_ids, select_works_by_citations, truncate, unique_ids
from .openalex import (
    OpenAlexBudgetExceeded,
    OpenAlexClient,
    OpenAlexError,
    chosen_keywords,
    keyless_limit_message,
    referenced_ids,
    short_id,
    work_to_candidate,
)


class NoKeywordSeeds(Exception):
    """Keyword expansion was requested and every seed lacks keywords."""


def _mark_year(row: Candidate, year_from: int | None, year_to: int | None) -> bool:
    """True when the row stays expandable. Out-of-window rows are kept as filtered."""
    if _keep_year(row, year_from, year_to):
        return True
    row.status = "filtered"
    if "(year)" not in row.why:
        row.why = f"{row.why} (year)"
    return False


def _seed_doi(doi: str) -> str | None:
    return normalize_doi(doi)


def _keep_year(row: Candidate, year_from: int | None, year_to: int | None) -> bool:
    year = row.biblio.get("year")
    if year is None:
        return True
    if year_from is not None and int(year) < year_from:
        return False
    if year_to is not None and int(year) > year_to:
        return False
    return True


def _seed_key(row: Candidate) -> str:
    return f"{row.seed.get('type')}:{row.seed.get('value')}"


def _dedupe(rows: list[Candidate]) -> list[Candidate]:
    """One row per work. Neighbours remember every seed that pointed at them."""
    first: dict[str, Candidate] = {}
    out: list[Candidate] = []
    for row in rows:
        key = row.identity
        if not key:
            continue
        if key not in first:
            if row.hop >= 1 and not row.biblio.get("seed_keys"):
                row.biblio["seed_keys"] = [_seed_key(row)]
            first[key] = row
            out.append(row)
            continue
        if row.hop < 1:
            continue
        existing = first[key]
        keys = existing.biblio.setdefault("seed_keys", [])
        incoming = list(row.biblio.get("seed_keys") or [_seed_key(row)])
        for token in incoming:
            if token not in keys:
                keys.append(token)
        incoming_overlap = int(row.biblio.get("keyword_overlap") or 0)
        kept_overlap = int(existing.biblio.get("keyword_overlap") or 0)
        if incoming_overlap > kept_overlap:
            existing.biblio["keyword_overlap"] = incoming_overlap
    return out


def _wants_refs(direction: str) -> bool:
    return "refs" in direction_sides(direction)


def _wants_cites(direction: str) -> bool:
    return "cites" in direction_sides(direction)


def _wants_keywords(direction: str) -> bool:
    return "keywords" in direction_sides(direction)


def _cite_sort(rank: str) -> str | None:
    mode = (rank or "most-cited").strip().lower()
    if mode == "least-cited":
        return "cited_by_count:asc"
    if mode == "most-cited":
        return "cited_by_count:desc"
    return None


def _cite_fetch_limit(per_hop_limit: int, rank: str) -> int:
    """How many citing works to request before local selection."""
    if per_hop_limit <= 0:
        return 0
    if (rank or "").strip().lower() == "random":
        return 0
    return per_hop_limit


def search_candidates(
    client: OpenAlexClient,
    query: str,
    *,
    run_id: str,
    gate: str,
    depth: int,
    direction: str,
    max_candidates: int,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
    min_seed_citations: int = 0,
    per_hop_rank: str = "most-cited",
    keyword_limit: int = 3,
    keyword_hop_limit: int = 50,
    keyword_min_score: float = 0.0,
) -> list[Candidate]:
    _remember_keywords(
        client,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
    )
    seed = {"type": "keyword", "value": query}
    client.stage = "OpenAlex search"
    client.note(client.stage)
    try:
        works = client.search(query, limit=max_candidates, year_from=year_from, year_to=year_to)
    except OpenAlexBudgetExceeded as exc:
        _defer(
            client,
            exc,
            kind="search",
            remaining_ids=[query],
            hop=0,
            depth=depth,
            direction=direction,
            run_id=run_id,
            seed=seed,
            gate=gate,
            per_hop_limit=per_hop_limit,
            year_from=year_from,
            year_to=year_to,
            why_prefix="search hit",
        )
        return []
    rows: list[Candidate] = []
    expandable: list[dict[str, Any]] = []
    for work in works:
        row = work_to_candidate(
            work,
            run_id=run_id,
            seed=seed,
            hop=0,
            direction="search",
            why="OpenAlex search",
            gate=gate,
        )
        if _mark_year(row, year_from, year_to):
            expandable.append(work)
        rows.append(row)
    if depth >= 1:
        rows.extend(
            _expand_hops(
                client,
                expandable,
                run_id=run_id,
                seed=seed,
                gate=gate,
                depth=depth,
                direction=direction if direction != "search" else "refs",
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix="search hit",
                min_seed_citations=min_seed_citations,
                per_hop_rank=per_hop_rank,
            )
        )
    return truncate(_dedupe(rows), max_candidates)


def doi_candidates(
    client: OpenAlexClient,
    dois: list[str],
    *,
    run_id: str,
    gate: str,
    depth: int,
    direction: str,
    max_candidates: int,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
    min_seed_citations: int = 0,
    per_hop_rank: str = "most-cited",
    keyword_limit: int = 3,
    keyword_hop_limit: int = 50,
    keyword_min_score: float = 0.0,
) -> tuple[list[Candidate], list[str]]:
    """Return neighbours of each DOI and DOIs that failed to resolve."""
    _remember_keywords(
        client,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
    )
    client.keyword_defer_empty_raise = True
    rows: list[Candidate] = []
    failed: list[str] = []
    for raw in dois:
        doi = _seed_doi(raw) or ""
        seed = {"type": "doi", "value": doi or raw}
        if not doi:
            failed.append(raw)
            rows.append(_error_row(run_id, seed, raw, f"invalid DOI {raw}", gate, direction))
            continue
        client.stage = f"seed {doi}"
        client.note(client.stage)
        try:
            work = client.work_by_doi(doi)
        except OpenAlexBudgetExceeded as exc:
            _defer(
                client,
                exc,
                kind="seeds",
                remaining_ids=dois[dois.index(raw) :],
                hop=0,
                depth=depth,
                direction=direction,
                run_id=run_id,
                seed=seed,
                gate=gate,
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix=doi or raw,
            )
            break
        except Exception as exc:
            if isinstance(exc, OpenAlexError):
                _defer(
                    client,
                    exc,
                    kind="seeds",
                    remaining_ids=dois[dois.index(raw) :],
                    hop=0,
                    depth=depth,
                    direction=direction,
                    run_id=run_id,
                    seed=seed,
                    gate=gate,
                    per_hop_limit=per_hop_limit,
                    year_from=year_from,
                    year_to=year_to,
                    why_prefix=doi or raw,
                )
                break
            failed.append(doi)
            rows.append(_error_row(run_id, seed, doi, str(exc), gate, direction))
            continue
        if not work:
            failed.append(doi)
            rows.append(_error_row(run_id, seed, doi, f"unresolved {doi}", gate, direction))
            continue
        _emit(client, rows)
        if depth >= 1:
            rows.extend(
                _expand_hops(
                    client,
                    [work],
                    run_id=run_id,
                    seed=seed,
                    gate=gate,
                    depth=depth,
                    direction=direction,
                    per_hop_limit=per_hop_limit,
                    year_from=year_from,
                    year_to=year_to,
                    why_prefix=doi,
                    min_seed_citations=min_seed_citations,
                    per_hop_rank=per_hop_rank,
                )
            )
        _emit(client, rows)
        if client.deferred:
            break
    if not client.deferred:
        _keyword_finish(client, direction)
    return truncate(_dedupe(rows), max_candidates), failed


def orcid_candidates(
    client: OpenAlexClient,
    orcid: str,
    dois: list[str],
    *,
    run_id: str,
    gate: str,
    depth: int,
    direction: str,
    max_candidates: int,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
    min_seed_citations: int = 0,
    per_hop_rank: str = "most-cited",
    keyword_limit: int = 3,
    keyword_hop_limit: int = 50,
    keyword_min_score: float = 0.0,
) -> tuple[list[Candidate], list[str]]:
    """Person's works (hop 0), then the same expander as DOI seeds."""
    _remember_keywords(
        client,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
    )
    seed = {"type": "orcid", "value": orcid}
    rows: list[Candidate] = []
    failed: list[str] = []
    seed_works: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for raw in dois:
        doi = _seed_doi(raw) or ""
        if not doi:
            failed.append(raw)
            rows.append(_error_row(run_id, seed, raw, f"invalid DOI {raw}", gate, direction))
            continue
        client.stage = f"ORCID work {doi}"
        client.note(client.stage)
        try:
            work = client.work_by_doi(doi)
        except OpenAlexBudgetExceeded as exc:
            _defer(
                client,
                exc,
                kind="seeds",
                remaining_ids=dois[dois.index(raw) :],
                hop=0,
                depth=depth,
                direction=direction,
                run_id=run_id,
                seed=seed,
                gate=gate,
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix=f"ORCID {orcid}",
            )
            break
        except Exception as exc:
            if isinstance(exc, OpenAlexError):
                _defer(
                    client,
                    exc,
                    kind="seeds",
                    remaining_ids=dois[dois.index(raw) :],
                    hop=0,
                    depth=depth,
                    direction=direction,
                    run_id=run_id,
                    seed=seed,
                    gate=gate,
                    per_hop_limit=per_hop_limit,
                    year_from=year_from,
                    year_to=year_to,
                    why_prefix=f"ORCID {orcid}",
                )
                break
            failed.append(doi)
            rows.append(_error_row(run_id, seed, doi, str(exc), gate, direction))
            continue
        if not work:
            failed.append(doi)
            rows.append(_error_row(run_id, seed, doi, f"unresolved {doi}", gate, direction))
            continue
        oa = short_id(str(work.get("id") or ""))
        if oa and oa in seen_ids:
            continue
        if oa:
            seen_ids.add(oa)
        seed_works.append(work)
        rows.append(
            work_to_candidate(
                work,
                run_id=run_id,
                seed=seed,
                hop=0,
                direction="orcid",
                why=f"ORCID {orcid}",
                gate=gate,
            )
        )
        _emit(client, rows)
        if client.deferred:
            break

    # OpenAlex author filter fills gaps the ORCID works list missed.
    author_works: list[dict[str, Any]] = []
    if not client.deferred:
        client.stage = f"OpenAlex author {orcid}"
        client.note(client.stage)
        try:
            author_works = client.works_by_author_orcid(
                orcid, limit=max_candidates, year_from=year_from, year_to=year_to
            )
        except OpenAlexBudgetExceeded as exc:
            _defer(
                client,
                exc,
                kind="author",
                remaining_ids=[orcid],
                hop=0,
                depth=depth,
                direction=direction,
                run_id=run_id,
                seed=seed,
                gate=gate,
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix=f"ORCID {orcid}",
            )
    for work in author_works:
        oa = short_id(str(work.get("id") or ""))
        if oa and oa in seen_ids:
            continue
        if oa:
            seen_ids.add(oa)
        seed_works.append(work)
        rows.append(
            work_to_candidate(
                work,
                run_id=run_id,
                seed=seed,
                hop=0,
                direction="orcid",
                why=f"OpenAlex author {orcid}",
                gate=gate,
            )
        )

    for row in rows:
        if row.status != "error":
            _mark_year(row, year_from, year_to)
    if depth >= 1 and seed_works and not client.deferred:
        rows.extend(
            _expand_hops(
                client,
                seed_works,
                run_id=run_id,
                seed=seed,
                gate=gate,
                depth=depth,
                direction=direction,
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix=f"ORCID {orcid}",
                min_seed_citations=min_seed_citations,
                per_hop_rank=per_hop_rank,
            )
        )
    return truncate(_dedupe(rows), max_candidates), failed


def _error_row(
    run_id: str,
    seed: dict[str, str],
    doi: str,
    why: str,
    gate: str,
    direction: str,
) -> Candidate:
    return Candidate(
        run_id=run_id,
        seed=seed,
        hop=0,
        direction=direction,
        ids={"doi": doi},
        biblio={"title": "", "year": None, "authors": [], "venue": "", "type": ""},
        why=why,
        status="error",
        provenance={"backend": "openalex", "endpoint": "/works", "retrieved_at": ""},
        gate=gate,
    )


def _emit(client: OpenAlexClient, rows: list[Candidate]) -> None:
    emit = client.emit
    if emit is not None and rows:
        emit(rows)


def _remember_keywords(
    client: OpenAlexClient,
    *,
    keyword_limit: int,
    keyword_hop_limit: int,
    keyword_min_score: float,
) -> None:
    client.keyword_limit = keyword_limit
    client.keyword_hop_limit = keyword_hop_limit
    client.keyword_min_score = keyword_min_score


def _keyword_settings(client: OpenAlexClient) -> tuple[int, int, float]:
    return (
        int(getattr(client, "keyword_limit", 3) or 3),
        int(getattr(client, "keyword_hop_limit", 50) or 50),
        float(getattr(client, "keyword_min_score", 0.0) or 0.0),
    )


def _defer(client: OpenAlexClient, exc: BaseException, **fields: Any) -> None:
    if client.deferred is not None:
        return
    limit, hop_limit, min_score = _keyword_settings(client)
    fields.setdefault("keyword_limit", limit)
    fields.setdefault("keyword_hop_limit", hop_limit)
    fields.setdefault("keyword_min_score", min_score)
    client.deferred = {
        "reset_at": getattr(exc, "reset_at", None),
        "reset_in_s": getattr(exc, "reset_in_s", None),
        "error": str(exc),
        "keyed": bool(client._using_key and client.api_key),
        **fields,
    }
    reset_at = getattr(exc, "reset_at", None)
    if isinstance(exc, OpenAlexBudgetExceeded):
        if client._using_key and client.api_key:
            when = f" Resume after {reset_at}." if reset_at else ""
            client.note(f"OpenAlex daily allowance for your API key is used up.{when}")
        else:
            client.note(keyless_limit_message(has_key=bool(client.api_key), reset_at=reset_at))
    else:
        client.note(f"Crawl paused ({exc}). Partial queue kept. paperful snowball resume")


def _keyword_sentence(empty: int, total: int) -> str:
    return f"{empty} of {total} seeds have no OpenAlex keywords and will not expand on that side."


def _keyword_prelude(client: OpenAlexClient, seeds: list[dict[str, Any]], direction: str) -> None:
    """Count seeds with no usable keywords. Raise when this batch is the whole run."""
    limit, _hop_limit, min_score = _keyword_settings(client)
    empty = sum(
        1 for work in seeds if not chosen_keywords(work, limit=limit, min_score=min_score)
    )
    total = len(seeds)
    client.keyword_seed_total = int(getattr(client, "keyword_seed_total", 0) or 0) + total
    client.keyword_seed_empty = int(getattr(client, "keyword_seed_empty", 0) or 0) + empty
    keywords_only = not _wants_refs(direction) and not _wants_cites(direction)
    held = bool(getattr(client, "keyword_defer_empty_raise", False))
    if keywords_only and total and empty == total and not held:
        raise NoKeywordSeeds(_keyword_sentence(empty, total))
    if empty and not held and not (keywords_only and empty == total):
        client.note(_keyword_sentence(empty, total))


def _keyword_finish(client: OpenAlexClient, direction: str) -> None:
    """One exit for a DOI list whose seeds were expanded one at a time."""
    if not getattr(client, "keyword_defer_empty_raise", False):
        return
    if not _wants_keywords(direction):
        return
    total = int(getattr(client, "keyword_seed_total", 0) or 0)
    empty = int(getattr(client, "keyword_seed_empty", 0) or 0)
    if not total or not empty:
        return
    sentence = _keyword_sentence(empty, total)
    if not _wants_refs(direction) and not _wants_cites(direction) and empty == total:
        raise NoKeywordSeeds(sentence)
    client.note(sentence)


def _keyword_fetch_limit(hop_limit: int, rank: str) -> int:
    """Finite page size. Random draws from a bounded window, never an open crawl."""
    if hop_limit <= 0:
        raise OpenAlexError(
            "keyword_hop_limit must be a positive integer. "
            "all is not allowed; a keyword filter is an open query."
        )
    if (rank or "").strip().lower() == "random":
        return min(200, hop_limit * 4)
    return hop_limit


def _keyword_neighbours(
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
    """One OR query per seed. Returns True when the crawl must stop and resume."""
    keyword_limit, hop_limit, min_score = _keyword_settings(client)
    tagged = []
    for work in frontier:
        slugs = chosen_keywords(work, limit=keyword_limit, min_score=min_score)
        oa = short_id(str(work.get("id") or ""))
        if slugs and oa:
            tagged.append((work, oa, slugs))
    if not tagged:
        return False
    client.stage = f"hop {hop}/{depth} keywords"
    client.note(f"hop {hop}/{depth} keywords · {len(tagged)} seeds")
    if client.tally is not None:
        client.tally.track(len(tagged))
    fetch_limit = _keyword_fetch_limit(hop_limit, rank)
    sort = _cite_sort(rank)
    for index, (work, oa, slugs) in enumerate(tagged, start=1):
        client.stage = f"hop {hop}/{depth} keywords {index}/{len(tagged)} {oa}"
        client.touch()
        try:
            hits = client.works_by_keywords(
                slugs,
                limit=fetch_limit,
                year_from=year_from,
                year_to=year_to,
                sort=sort,
            )
        except Exception as exc:
            remaining = [item[1] for item in tagged[index - 1 :]]
            _defer(
                client,
                exc,
                kind="keywords",
                remaining_ids=remaining,
                keyword_slugs=slugs,
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
            hits = select_works_by_citations(hits, hop_limit, "random")
        else:
            hits = hits[:hop_limit]
        label = normalize_doi(str(work.get("doi") or "")) or why_prefix
        kept = 0
        for child in hits:
            child_id = short_id(str(child.get("id") or ""))
            if not child_id or child_id in seen_oa:
                continue
            seen_oa.add(child_id)
            child_slugs = set(chosen_keywords(child, limit=0, min_score=0.0))
            shared = [slug for slug in slugs if slug in child_slugs] or list(slugs)
            row = work_to_candidate(
                child,
                run_id=run_id,
                seed=seed,
                hop=hop,
                direction="keywords",
                why=f"keywords {', '.join(shared)} of {label}",
                gate=gate,
            )
            row.biblio["keyword_overlap"] = len(shared)
            if _mark_year(row, year_from, year_to):
                next_works.append(child)
                kept += 1
            rows.append(row)
            if kept >= hop_limit:
                break
        if client.tally is not None:
            client.tally.advance(1)
        _emit(client, rows)
    return False


def _expand_hops(
    client: OpenAlexClient,
    seeds: list[dict[str, Any]],
    *,
    run_id: str,
    seed: dict[str, str],
    gate: str,
    depth: int,
    direction: str,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
    why_prefix: str,
    min_seed_citations: int = 0,
    per_hop_rank: str = "most-cited",
) -> list[Candidate]:
    """BFS from seed works through refs, cites, and/or keywords up to ``depth`` hops."""
    if depth < 1:
        return []
    want_refs = _wants_refs(direction)
    want_cites = _wants_cites(direction)
    want_keywords = _wants_keywords(direction)
    if not want_refs and not want_cites and not want_keywords:
        return []
    rank = (per_hop_rank or "most-cited").strip().lower()
    if want_keywords:
        _keyword_prelude(client, seeds, direction)

    rows: list[Candidate] = []
    frontier = list(seeds)
    seen_oa: set[str] = {short_id(str(w.get("id") or "")) for w in seeds if w.get("id")}
    seen_oa.discard("")

    for hop in range(1, depth + 1):
        client.stage = f"hop {hop}/{depth}"
        client.note(f"hop {hop}/{depth} · {len(frontier)} seeds · {direction}")
        next_works: list[dict[str, Any]] = []
        if want_refs:
            per_work_ids: list[list[str]] = []
            fetch_ids: list[str] = []
            fetch_set: set[str] = set()
            for work in frontier:
                unseen = unique_ids(
                    [item for item in referenced_ids(work, 0) if item not in seen_oa]
                )
                if rank == "random" and per_hop_limit > 0:
                    unseen = sample_ids(unseen, per_hop_limit)
                per_work_ids.append(unseen)
                for ref_id in unseen:
                    if ref_id not in fetch_set:
                        fetch_set.add(ref_id)
                        fetch_ids.append(ref_id)
            if fetch_ids:
                client.stage = f"hop {hop}/{depth} references · {len(fetch_ids)} ids"
                client.note(client.stage)
                try:
                    children = client.works_by_ids(fetch_ids)
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
                for ids in per_work_ids:
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
                            why=f"ref of {why_prefix}",
                            gate=gate,
                        )
                        if _mark_year(row, year_from, year_to):
                            next_works.append(child)
                        rows.append(row)
                _emit(client, rows)
                if client.deferred:
                    return rows
        if want_cites:
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
                client.stage = f"hop {hop}/{depth} cited-by"
                client.note(f"hop {hop}/{depth} cited-by · {len(citing_seeds)} seeds")
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
                        return rows
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
                            why=f"cites {why_prefix}",
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
        if want_keywords:
            if _keyword_neighbours(
                client,
                frontier,
                rows,
                next_works,
                seen_oa,
                hop=hop,
                depth=depth,
                direction=direction,
                run_id=run_id,
                seed=seed,
                gate=gate,
                per_hop_limit=per_hop_limit,
                rank=rank,
                year_from=year_from,
                year_to=year_to,
                why_prefix=why_prefix,
                min_seed_citations=min_seed_citations,
            ):
                return rows
        frontier = next_works
        if not frontier:
            break
    return rows


def hybrid_candidates(
    client: OpenAlexClient,
    query: str,
    *,
    run_id: str,
    gate: str,
    direction: str,
    max_candidates: int,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
    hybrid_seeds: int,
    min_seed_citations: int = 0,
    per_hop_rank: str = "most-cited",
    keyword_limit: int = 3,
    keyword_hop_limit: int = 50,
    keyword_min_score: float = 0.0,
) -> tuple[list[Candidate], list[str]]:
    """Keyword hits, then one hop from the top DOI hits."""
    hits = search_candidates(
        client,
        query,
        run_id=run_id,
        gate=gate,
        depth=0,
        direction=direction,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        year_from=year_from,
        year_to=year_to,
        min_seed_citations=min_seed_citations,
        per_hop_rank=per_hop_rank,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
    )
    ranked = sorted(
        [row for row in hits if row.ids.get("doi") and row.status != "error"],
        key=lambda row: (-row.score, row.ids.get("doi") or ""),
    )
    limit = hybrid_seeds if max_candidates <= 0 else max(0, min(hybrid_seeds, max_candidates))
    seeds = [row.ids["doi"] for row in ranked[:limit]]
    if not seeds:
        return hits, []
    neighbours, failed = doi_candidates(
        client,
        seeds,
        run_id=run_id,
        gate=gate,
        depth=1,
        direction=direction,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        year_from=year_from,
        year_to=year_to,
        min_seed_citations=min_seed_citations,
        per_hop_rank=per_hop_rank,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
    )
    return truncate(_dedupe(hits + neighbours), max_candidates), failed


def continue_deferred(client: OpenAlexClient, deferred: dict[str, Any]) -> list[Candidate]:
    """Finish the OpenAlex calls a budget stop left in ``deferred``."""
    kind = str(deferred.get("kind") or "")
    run_id = str(deferred.get("run_id") or "")
    seed = dict(deferred.get("seed") or {"type": "openalex", "value": ""})
    gate = str(deferred.get("gate") or "dry-run")
    hop = int(deferred.get("hop") or 0)
    per_hop = int(deferred.get("per_hop_limit") or 50)
    rank = str(deferred.get("per_hop_rank") or "most-cited")
    year_from = deferred.get("year_from")
    year_to = deferred.get("year_to")
    why = str(deferred.get("why_prefix") or "resume")
    remaining = [str(item) for item in (deferred.get("remaining_ids") or []) if item]
    rows: list[Candidate] = []

    def _row(work: dict[str, Any], direction: str, reason: str) -> Candidate:
        return work_to_candidate(
            work,
            run_id=run_id,
            seed=seed,
            hop=hop,
            direction=direction,
            why=reason,
            gate=gate,
        )

    _remember_keywords(
        client,
        keyword_limit=int(deferred.get("keyword_limit") or 3),
        keyword_hop_limit=int(deferred.get("keyword_hop_limit") or 50),
        keyword_min_score=float(deferred.get("keyword_min_score") or 0.0),
    )
    if kind == "keywords":
        client.stage = "resume keywords"
        client.note(f"resume keywords · {len(remaining)} seeds")
        hop_limit = int(deferred.get("keyword_hop_limit") or 50)
        keyword_limit = int(deferred.get("keyword_limit") or 3)
        min_score = float(deferred.get("keyword_min_score") or 0.0)
        fetch_limit = _keyword_fetch_limit(hop_limit, rank)
        sort = _cite_sort(rank)
        if client.tally is not None and remaining:
            client.tally.track(len(remaining))
        for index, oa in enumerate(remaining, start=1):
            client.stage = f"resume keywords {index}/{len(remaining)} {oa}"
            client.touch()
            try:
                found = client.works_by_ids([oa])
                slugs = chosen_keywords(found[0], limit=keyword_limit, min_score=min_score) if found else []
                hits = (
                    client.works_by_keywords(
                        slugs,
                        limit=fetch_limit,
                        year_from=year_from,
                        year_to=year_to,
                        sort=sort,
                    )
                    if slugs
                    else []
                )
            except OpenAlexBudgetExceeded as exc:
                _defer(client, exc, **{**deferred, "remaining_ids": remaining[index - 1 :]})
                return rows
            if rank == "random":
                hits = select_works_by_citations(hits, hop_limit, "random")
            else:
                hits = hits[:hop_limit]
            for child in hits:
                child_slugs = set(chosen_keywords(child, limit=0, min_score=0.0))
                shared = [slug for slug in slugs if slug in child_slugs] or list(slugs)
                row = _row(child, "keywords", f"keywords {', '.join(shared)} of {why}")
                row.biblio["keyword_overlap"] = len(shared)
                rows.append(row)
            if client.tally is not None:
                client.tally.advance(1)
        return rows
    if kind == "cites":
        client.stage = "resume cited-by"
        client.note(f"resume cited-by · {len(remaining)} seeds")
        if client.tally is not None:
            client.tally.track(len(remaining))
        cite_limit = _cite_fetch_limit(per_hop, rank)
        cite_sort = _cite_sort(rank)
        for index, oa in enumerate(remaining, start=1):
            client.stage = f"resume cited-by {index}/{len(remaining)} {oa}"
            client.touch()
            try:
                citing = client.works_citing(
                    oa,
                    limit=cite_limit,
                    year_from=year_from,
                    year_to=year_to,
                    sort=cite_sort,
                )
            except OpenAlexBudgetExceeded as exc:
                _defer(client, exc, **{**deferred, "remaining_ids": remaining[index - 1 :]})
                return rows
            if rank == "random":
                citing = select_works_by_citations(citing, per_hop, "random")
            elif per_hop > 0:
                citing = citing[:per_hop]
            rows.extend(_row(child, "cites", f"cites {why}") for child in citing)
            if client.tally is not None:
                client.tally.advance(1)
        return rows
    if kind == "refs":
        client.stage = f"resume references · {len(remaining)} ids"
        client.note(client.stage)
        try:
            children = client.works_by_ids(remaining)
        except OpenAlexBudgetExceeded as exc:
            rows.extend(_row(child, "refs", f"ref of {why}") for child in exc.partial)
            _defer(client, exc, **{**deferred, "remaining_ids": list(exc.pending_ids)})
            return rows
        return [_row(child, "refs", f"ref of {why}") for child in children]
    if kind == "author" and remaining:
        try:
            found = client.works_by_author_orcid(
                remaining[0], limit=per_hop, year_from=year_from, year_to=year_to
            )
        except OpenAlexBudgetExceeded as exc:
            _defer(client, exc, **deferred)
            return rows
        return [_row(child, "orcid", f"OpenAlex author {remaining[0]}") for child in found]
    if kind == "search" and remaining:
        try:
            found = client.search(remaining[0], limit=per_hop, year_from=year_from, year_to=year_to)
        except OpenAlexBudgetExceeded as exc:
            _defer(client, exc, **deferred)
            return rows
        return [_row(child, "search", "OpenAlex search") for child in found]
    if kind == "seeds":
        for index, doi in enumerate(remaining):
            try:
                work = client.work_by_doi(doi)
            except OpenAlexBudgetExceeded as exc:
                _defer(client, exc, **{**deferred, "remaining_ids": remaining[index:]})
                return rows
            if work:
                rows.append(_row(work, "refs", doi))
        return rows
    return rows
