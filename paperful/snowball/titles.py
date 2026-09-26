"""Replace citation stubs with the work record before a row can be created."""

from __future__ import annotations

from typing import Any

from ..lint import usable_work_title
from ..resolve import normalize_doi
from .candidate import Candidate
from .expand import publication_year
from .openalex import SELECT, OpenAlexBudgetExceeded, short_id, work_to_candidate


def repair_reference_titles(rows: list[Candidate], client: Any, *, tally: Any = None) -> None:
    """Fill hop neighbours whose title or year is missing from the OpenAlex work.

    A Crossref or Semantic Scholar reference is often only a DOI, or the whole
    citation string. That string is not stored as the title. Rows that still
    have no usable title after this pass are marked filtered.
    """
    need: list[Candidate] = []
    for row in rows:
        if row.hop < 1 or row.status != "new":
            continue
        if (row.provenance.get("backend") or "") == "openalex":
            continue
        if _needs_work(row):
            need.append(row)
            continue
        if not (row.ids.get("doi") or "").strip() and not usable_work_title(row.biblio.get("title")):
            _reject_title(row)
    if not need:
        return
    by_doi = _works_by_doi(client, [str(row.ids.get("doi") or "") for row in need], tally=tally)
    for row in need:
        doi = normalize_doi(str(row.ids.get("doi") or "")) or ""
        work = by_doi.get(doi)
        if work is not None:
            _merge_work(row, work)
        if not usable_work_title(row.biblio.get("title")):
            _reject_title(row)


def _needs_work(row: Candidate) -> bool:
    if row.hop < 1 or row.status != "new":
        return False
    if (row.provenance.get("backend") or "") == "openalex":
        return False
    doi = str(row.ids.get("doi") or "").strip()
    if not doi:
        return False
    if not usable_work_title(row.biblio.get("title")):
        return True
    return publication_year(row.biblio.get("year")) is None


def _works_by_doi(client: Any, dois: list[str], *, tally: Any) -> dict[str, dict[str, Any]]:
    if client is None or not hasattr(client, "works_by_dois"):
        return {}
    previous = getattr(client, "stage", None)
    client.stage = "reference titles"
    try:
        if tally is not None:
            tally.stage = "reference titles"
        try:
            found = client.works_by_dois(dois, select=SELECT)
        except OpenAlexBudgetExceeded as exc:
            found = list(exc.partial or [])
    finally:
        client.stage = previous
    out: dict[str, dict[str, Any]] = {}
    for work in found:
        if not isinstance(work, dict):
            continue
        doi = normalize_doi(str(work.get("doi") or "")) or ""
        if doi:
            out[doi] = work
    return out


def _merge_work(row: Candidate, work: dict[str, Any]) -> None:
    incoming = work_to_candidate(
        work,
        run_id=row.run_id,
        seed=dict(row.seed),
        hop=row.hop,
        direction=row.direction,
        why=row.why,
        gate=row.gate,
    ).biblio
    biblio = row.biblio
    trusted = usable_work_title(biblio.get("title"))
    new_title = str(incoming.get("title") or "")
    if not trusted and usable_work_title(new_title):
        biblio["title"] = new_title
    if not trusted:
        if publication_year(incoming.get("year")) is not None:
            biblio["year"] = incoming.get("year")
        if incoming.get("authors"):
            biblio["authors"] = list(incoming["authors"])
        if incoming.get("venue"):
            biblio["venue"] = incoming["venue"]
        if incoming.get("type"):
            biblio["type"] = incoming["type"]
        if incoming.get("language"):
            biblio["language"] = incoming["language"]
        if incoming.get("cited_by_count"):
            biblio["cited_by_count"] = incoming["cited_by_count"]
        if incoming.get("oa_url") and not biblio.get("oa_url"):
            biblio["oa_url"] = incoming["oa_url"]
        if "is_oa" in incoming:
            biblio["is_oa"] = incoming["is_oa"]
    else:
        if publication_year(biblio.get("year")) is None and publication_year(incoming.get("year")) is not None:
            biblio["year"] = incoming.get("year")
        if not biblio.get("authors") and incoming.get("authors"):
            biblio["authors"] = list(incoming["authors"])
        if not biblio.get("venue") and incoming.get("venue"):
            biblio["venue"] = incoming["venue"]
        if not biblio.get("cited_by_count") and incoming.get("cited_by_count"):
            biblio["cited_by_count"] = incoming["cited_by_count"]
    oa = short_id(str(work.get("id") or ""))
    if oa and not row.ids.get("openalex"):
        row.ids["openalex"] = oa
    row.provenance["filled_by"] = "openalex"


def _reject_title(row: Candidate) -> None:
    if row.status != "new":
        return
    row.status = "filtered"
    if "(title)" not in (row.why or ""):
        row.why = f"{row.why} (title)".strip()
