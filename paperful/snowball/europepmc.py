"""Europe PMC citation lists for snowball. PDF lookup stays in sources/europepmc.py."""

from __future__ import annotations

from typing import Any

from .fill import FillPaused

_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_REFS = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{ident}/references"


def europepmc_work(doi: str) -> dict[str, Any] | None:
    """Metadata plus outgoing DOI references. A miss is None. A 429 pauses."""
    import httpx

    try:
        found = httpx.get(
            _SEARCH,
            params={"query": f"DOI:{doi}", "format": "json", "resultType": "lite", "pageSize": "1"},
            timeout=30,
        )
        if found.status_code == 404:
            return None
        if found.status_code == 429 or found.status_code >= 500:
            raise FillPaused("europepmc")
        found.raise_for_status()
        results = ((found.json().get("resultList") or {}).get("result")) or []
        if not results or not isinstance(results[0], dict):
            return None
        hit = results[0]
        source = str(hit.get("source") or "")
        ident = str(hit.get("id") or "")
        if not source or not ident:
            return None
        refs = httpx.get(
            _REFS.format(source=source, ident=ident),
            params={"format": "json", "pageSize": "1000"},
            timeout=30,
        )
        if refs.status_code == 404:
            listed: list[Any] = []
        elif refs.status_code == 429 or refs.status_code >= 500:
            raise FillPaused("europepmc")
        else:
            refs.raise_for_status()
            listed = ((refs.json().get("referenceList") or {}).get("reference")) or []
    except FillPaused:
        raise
    except (httpx.HTTPError, ValueError):
        return None
    references = []
    for ref in listed:
        if not isinstance(ref, dict):
            continue
        references.append(
            {
                "doi": str(ref.get("doi") or ""),
                "title": str(ref.get("title") or ""),
                "year": ref.get("pubYear"),
            }
        )
    return {
        "title": str(hit.get("title") or ""),
        "year": hit.get("pubYear"),
        "venue": str(hit.get("journalTitle") or ""),
        "authors": [part.strip() for part in str(hit.get("authorString") or "").split(",") if part.strip()],
        "references": references,
    }
