"""Turn OpenAlex payloads into a deduped candidate list."""

from __future__ import annotations

from typing import Any

from .candidate import Candidate
from .expand import truncate
from .openalex import OpenAlexClient, referenced_ids, short_id, work_to_candidate


def _keep_year(row: Candidate, year_from: int | None, year_to: int | None) -> bool:
    year = row.biblio.get("year")
    if year is None:
        return True
    if year_from is not None and int(year) < year_from:
        return False
    if year_to is not None and int(year) > year_to:
        return False
    return True


def _dedupe(rows: list[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for row in rows:
        key = row.identity
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _wants_refs(direction: str) -> bool:
    return direction in {"refs", "both"}


def _wants_cites(direction: str) -> bool:
    return direction in {"cites", "both"}


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
) -> list[Candidate]:
    seed = {"type": "keyword", "value": query}
    works = client.search(query, limit=max_candidates, year_from=year_from, year_to=year_to)
    rows = [
        work_to_candidate(
            work,
            run_id=run_id,
            seed=seed,
            hop=0,
            direction="search",
            why="OpenAlex search",
            gate=gate,
        )
        for work in works
    ]
    rows = [row for row in rows if _keep_year(row, year_from, year_to)]
    if depth >= 1:
        rows.extend(
            _expand_hops(
                client,
                works,
                run_id=run_id,
                seed=seed,
                gate=gate,
                depth=depth,
                direction=direction if direction != "search" else "refs",
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix="search hit",
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
) -> tuple[list[Candidate], list[str]]:
    """Return neighbours of each DOI and DOIs that failed to resolve."""
    rows: list[Candidate] = []
    failed: list[str] = []
    for doi in dois:
        seed = {"type": "doi", "value": doi}
        try:
            work = client.work_by_doi(doi)
        except Exception as exc:
            failed.append(doi)
            rows.append(_error_row(run_id, seed, doi, str(exc), gate, direction))
            continue
        if not work:
            failed.append(doi)
            rows.append(_error_row(run_id, seed, doi, f"unresolved {doi}", gate, direction))
            continue
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
                )
            )
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
) -> tuple[list[Candidate], list[str]]:
    """Person's works (hop 0), then the same expander as DOI seeds."""
    seed = {"type": "orcid", "value": orcid}
    rows: list[Candidate] = []
    failed: list[str] = []
    seed_works: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for doi in dois:
        try:
            work = client.work_by_doi(doi)
        except Exception as exc:
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

    # OpenAlex author filter fills gaps the ORCID works list missed.
    for work in client.works_by_author_orcid(
        orcid, limit=max_candidates, year_from=year_from, year_to=year_to
    ):
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

    rows = [row for row in rows if row.status == "error" or _keep_year(row, year_from, year_to)]
    if depth >= 1 and seed_works:
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
) -> list[Candidate]:
    """BFS from seed works through refs and/or cites up to ``depth`` hops."""
    if depth < 1:
        return []
    want_refs = _wants_refs(direction)
    want_cites = _wants_cites(direction)
    if not want_refs and not want_cites:
        return []

    rows: list[Candidate] = []
    frontier = list(seeds)
    seen_oa: set[str] = {short_id(str(w.get("id") or "")) for w in seeds if w.get("id")}
    seen_oa.discard("")

    for hop in range(1, depth + 1):
        next_works: list[dict[str, Any]] = []
        ref_wanted: list[str] = []
        if want_refs:
            for work in frontier:
                for ref_id in referenced_ids(work, per_hop_limit):
                    if ref_id in seen_oa:
                        continue
                    seen_oa.add(ref_id)
                    ref_wanted.append(ref_id)
            if ref_wanted:
                for child in client.works_by_ids(ref_wanted):
                    row = work_to_candidate(
                        child,
                        run_id=run_id,
                        seed=seed,
                        hop=hop,
                        direction="refs",
                        why=f"ref of {why_prefix}",
                        gate=gate,
                    )
                    if _keep_year(row, year_from, year_to):
                        rows.append(row)
                        next_works.append(child)
        if want_cites:
            for work in frontier:
                oa = short_id(str(work.get("id") or ""))
                if not oa:
                    continue
                citing = client.works_citing(
                    oa,
                    limit=per_hop_limit,
                    year_from=year_from,
                    year_to=year_to,
                )
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
                    if _keep_year(row, year_from, year_to):
                        rows.append(row)
                        next_works.append(child)
                        kept += 1
                    if kept >= per_hop_limit:
                        break
        frontier = next_works
        if not frontier:
            break
    return rows
