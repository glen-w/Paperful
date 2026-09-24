"""Turn OpenAlex payloads into a deduped candidate list."""

from __future__ import annotations

from .candidate import Candidate
from .expand import truncate
from .openalex import OpenAlexClient, referenced_ids, work_to_candidate


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


def search_candidates(
    client: OpenAlexClient,
    query: str,
    *,
    run_id: str,
    gate: str,
    depth: int,
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
            _expand_refs(
                client,
                works,
                run_id=run_id,
                seed=seed,
                gate=gate,
                per_hop_limit=per_hop_limit,
                year_from=year_from,
                year_to=year_to,
                why_prefix="ref of search hit",
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
    max_candidates: int,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
) -> tuple[list[Candidate], list[str]]:
    """Return candidates and DOIs that failed to resolve. Other seeds continue."""
    rows: list[Candidate] = []
    failed: list[str] = []
    for doi in dois:
        seed = {"type": "doi", "value": doi}
        try:
            work = client.work_by_doi(doi)
        except Exception as exc:
            failed.append(doi)
            rows.append(
                Candidate(
                    run_id=run_id,
                    seed=seed,
                    hop=0,
                    direction="refs",
                    ids={"doi": doi},
                    biblio={"title": "", "year": None, "authors": [], "venue": "", "type": ""},
                    why=str(exc),
                    status="error",
                    provenance={"backend": "openalex", "endpoint": "/works", "retrieved_at": ""},
                    gate=gate,
                )
            )
            continue
        if not work:
            failed.append(doi)
            rows.append(
                Candidate(
                    run_id=run_id,
                    seed=seed,
                    hop=0,
                    direction="refs",
                    ids={"doi": doi},
                    biblio={"title": "", "year": None, "authors": [], "venue": "", "type": ""},
                    why=f"unresolved {doi}",
                    status="error",
                    provenance={"backend": "openalex", "endpoint": "/works", "retrieved_at": ""},
                    gate=gate,
                )
            )
            continue
        if depth >= 1:
            rows.extend(
                _expand_refs(
                    client,
                    [work],
                    run_id=run_id,
                    seed=seed,
                    gate=gate,
                    per_hop_limit=per_hop_limit,
                    year_from=year_from,
                    year_to=year_to,
                    why_prefix=f"ref of {doi}",
                )
            )
    return truncate(_dedupe(rows), max_candidates), failed


def _expand_refs(
    client: OpenAlexClient,
    seeds: list[dict],
    *,
    run_id: str,
    seed: dict[str, str],
    gate: str,
    per_hop_limit: int,
    year_from: int | None,
    year_to: int | None,
    why_prefix: str,
) -> list[Candidate]:
    wanted: list[str] = []
    seen: set[str] = set()
    for work in seeds:
        for oa_id in referenced_ids(work, per_hop_limit):
            if oa_id not in seen:
                seen.add(oa_id)
                wanted.append(oa_id)
    if not wanted:
        return []
    rows = [
        work_to_candidate(
            work,
            run_id=run_id,
            seed=seed,
            hop=1,
            direction="refs",
            why=why_prefix,
            gate=gate,
        )
        for work in client.works_by_ids(wanted)
    ]
    return [row for row in rows if _keep_year(row, year_from, year_to)]
