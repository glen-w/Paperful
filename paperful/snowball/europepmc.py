"""Europe PMC citation lists for snowball. PDF lookup stays in sources/europepmc.py.

Membership is a batched DOI search. A reference list is fetched only when the
record says it has one. Misses and hits are cached so the hop and the fill
pass share them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .fill import FillPaused

_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_REFS = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{ident}/references"
_HEADERS = {"User-Agent": "paperful-snowball/0.1"}

PROBE_SIZE = 25
BATCH_SIZE = 25


def europepmc_work(doi: str, *, cache_dir: Path | None = None) -> dict[str, Any] | None:
    """Metadata plus outgoing references for one DOI. A miss is None. A 429 pauses."""
    found = lookup_dois([doi], cache_dir=cache_dir)
    return found.get(_norm_doi(doi))


def lookup_dois(dois: list[str], *, cache_dir: Path | None = None) -> dict[str, dict[str, Any] | None]:
    """Look up these DOIs. None means the DOI is not in Europe PMC.

    One search covers the whole list (chunked). ``/references`` runs only for
    ``hasReferences=Y``. A MEDLINE id with no DOI is resolved when the index
    has a DOI for it. Transport errors and 429 pause; they are not cached.
    """
    ordered = _unique(dois)
    if not ordered:
        return {}
    out: dict[str, dict[str, Any] | None] = {}
    pending: list[str] = []
    for doi in ordered:
        hit, payload = cached_payload(doi, cache_dir)
        if hit:
            out[doi] = payload
        else:
            pending.append(doi)
    for chunk in _chunks(pending, BATCH_SIZE):
        found = _fetch_chunk(chunk)
        for doi, payload in found.items():
            _store(cache_dir, doi, payload)
            out[doi] = payload
    return out


def cached_payload(doi: str, cache_dir: Path | None) -> tuple[bool, dict[str, Any] | None]:
    """`(True, payload-or-None)` when this DOI is already cached."""
    if cache_dir is None:
        return False, None
    path = _cache_path(cache_dir, doi)
    if not path.is_file():
        return False, None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    if not isinstance(loaded, dict):
        return False, None
    if loaded.get("miss"):
        return True, None
    return True, loaded


def spread_dois(dois: list[str], n: int) -> list[str]:
    """Even sample, always including the first and last DOI when `n` allows."""
    if n <= 0 or not dois:
        return []
    if len(dois) <= n:
        return list(dois)
    if n == 1:
        return [dois[0]]
    step = (len(dois) - 1) / (n - 1)
    out: list[str] = []
    seen: set[str] = set()
    for index in range(n):
        doi = dois[round(index * step)]
        if doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return out


def _fetch_chunk(dois: list[str]) -> dict[str, dict[str, Any] | None]:
    data = _request(
        _SEARCH,
        {"query": " OR ".join(f"DOI:{doi}" for doi in dois), "format": "json", "resultType": "core", "pageSize": str(len(dois))},
    )
    by_doi = {_norm_doi(str(hit.get("doi") or "")): hit for hit in _results(data)}
    by_doi.pop("", None)
    payloads: dict[str, dict[str, Any] | None] = {}
    for doi in dois:
        hit = by_doi.get(doi)
        if hit is None:
            payloads[doi] = None
            continue
        references: list[dict[str, Any]] = []
        if _lists_references(hit):
            source = str(hit.get("source") or "")
            ident = str(hit.get("id") or "")
            if source and ident:
                references = _reference_list(source, ident)
        payloads[doi] = _payload(hit, references)
    _hydrate_pmids([ref for payload in payloads.values() if payload for ref in payload["references"]])
    return payloads


def _reference_list(source: str, ident: str) -> list[dict[str, Any]]:
    data = _request(_REFS.format(source=source, ident=ident), {"format": "json", "pageSize": "1000"})
    listed = ((data.get("referenceList") or {}).get("reference")) or []
    refs: list[dict[str, Any]] = []
    for ref in listed:
        if not isinstance(ref, dict):
            continue
        doi = str(ref.get("doi") or "").strip()
        pmid = ""
        ref_source = str(ref.get("source") or "")
        ref_id = str(ref.get("id") or "").strip()
        if not doi and ref_source == "MED" and ref_id.isdigit():
            pmid = ref_id
        refs.append(
            {
                "doi": doi,
                "pmid": pmid,
                "title": str(ref.get("title") or ""),
                "year": ref.get("pubYear"),
            }
        )
    return refs


def _hydrate_pmids(references: list[dict[str, Any]]) -> None:
    need = [ref for ref in references if not ref.get("doi") and ref.get("pmid")]
    if not need:
        return
    for chunk in _chunks(need, BATCH_SIZE):
        query = " OR ".join(f"EXT_ID:{ref['pmid']}" for ref in chunk)
        data = _request(
            _SEARCH,
            {"query": query, "format": "json", "resultType": "lite", "pageSize": str(len(chunk))},
        )
        by_pmid: dict[str, str] = {}
        for hit in _results(data):
            pmid = str(hit.get("pmid") or hit.get("id") or "")
            doi = _norm_doi(str(hit.get("doi") or ""))
            if pmid and doi:
                by_pmid[pmid] = doi
        for ref in chunk:
            doi = by_pmid.get(str(ref.get("pmid") or ""))
            if doi:
                ref["doi"] = doi


def _payload(hit: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": str(hit.get("title") or ""),
        "year": hit.get("pubYear"),
        "venue": str(hit.get("journalTitle") or ""),
        "authors": [part.strip() for part in str(hit.get("authorString") or "").split(",") if part.strip()],
        "references": references,
    }


def _lists_references(hit: dict[str, Any]) -> bool:
    return str(hit.get("hasReferences") or "").upper() == "Y"


def _results(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = ((data.get("resultList") or {}).get("result")) or []
    return [hit for hit in raw if isinstance(hit, dict)]


def _request(url: str, params: dict[str, str]) -> dict[str, Any]:
    import httpx

    try:
        resp = httpx.get(url, params=params, headers=_HEADERS, timeout=30)
    except httpx.HTTPError as exc:
        raise FillPaused("europepmc") from exc
    if resp.status_code == 404:
        return {}
    if resp.status_code == 429 or resp.status_code >= 500:
        raise FillPaused("europepmc")
    try:
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise FillPaused("europepmc") from exc
    return data if isinstance(data, dict) else {}


def _store(cache_dir: Path | None, doi: str, payload: dict[str, Any] | None) -> None:
    if cache_dir is None:
        return
    path = _cache_path(cache_dir, doi)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"miss": True} if payload is None else payload
    path.write_text(json.dumps(body), encoding="utf-8")


def _cache_path(cache_dir: Path, doi: str) -> Path:
    return cache_dir / f"{_norm_doi(doi).replace('/', '_')}.json"


def _norm_doi(doi: str) -> str:
    text = (doi or "").strip()
    lower = text.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lower.startswith(prefix):
            text = text[len(prefix) :]
            lower = text.lower()
            break
    return lower


def _unique(dois: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in dois:
        doi = _norm_doi(raw)
        if not doi or doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return out


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
