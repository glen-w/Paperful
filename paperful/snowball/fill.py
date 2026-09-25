"""Fill empty metadata. OpenAlex wins when a field is already set."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from .candidate import Candidate

CrossrefGet = Callable[[str], dict[str, Any] | None]
S2Get = Callable[[str], dict[str, Any] | None]


def fill_crossref(rows: list[Candidate], getter: CrossrefGet) -> None:
    for row in rows:
        if row.status == "error":
            continue
        doi = row.ids.get("doi") or ""
        if not doi or _complete(row):
            continue
        payload = getter(doi)
        if not payload:
            continue
        _fill_empty(row, payload, backend="crossref")


def fill_semanticscholar(
    rows: list[Candidate],
    getter: S2Get,
    *,
    per_hop_limit: int,
    direction: str,
) -> list[Candidate]:
    """Fill holes and append reference neighbours OpenAlex did not already emit."""
    added: list[Candidate] = []
    known = {row.identity for row in rows if row.identity}
    want_refs = direction in {"refs", "both"}
    for row in list(rows):
        doi = row.ids.get("doi") or ""
        if not doi or row.status == "error":
            continue
        payload = getter(doi)
        if not payload:
            continue
        _fill_empty(
            row,
            {
                "title": payload.get("title") or "",
                "year": payload.get("year"),
                "venue": payload.get("venue") or "",
                "authors": [
                    (author.get("name") or "")
                    for author in (payload.get("authors") or [])
                    if isinstance(author, dict)
                ],
            },
            backend="semanticscholar",
        )
        if not want_refs:
            continue
        kept = 0
        for ref in payload.get("references") or []:
            if kept >= per_hop_limit:
                break
            if not isinstance(ref, dict):
                continue
            ref_doi = str((ref.get("externalIds") or {}).get("DOI") or "").lower()
            if not ref_doi:
                continue
            ident = f"doi:{ref_doi}"
            if ident in known:
                continue
            known.add(ident)
            child = Candidate(
                run_id=row.run_id,
                seed=dict(row.seed),
                hop=row.hop + 1 if row.hop else 1,
                direction="refs",
                ids={"doi": ref_doi},
                biblio={
                    "title": ref.get("title") or "",
                    "year": ref.get("year"),
                    "authors": [],
                    "venue": "",
                    "type": "article",
                    "cited_by_count": 0,
                    "seed_keys": [f"{row.seed.get('type')}:{row.seed.get('value')}"],
                },
                why=f"s2 ref of {doi}",
                status="new",
                provenance={
                    "backend": "semanticscholar",
                    "endpoint": "/graph/v1/paper",
                    "retrieved_at": "",
                },
                gate=row.gate,
            )
            added.append(child)
            kept += 1
    return added


def _complete(row: Candidate) -> bool:
    biblio = row.biblio
    return bool(biblio.get("title") and biblio.get("year") and biblio.get("venue") and biblio.get("authors"))


def _fill_empty(row: Candidate, payload: dict[str, Any], *, backend: str) -> None:
    biblio = row.biblio
    if not biblio.get("title") and payload.get("title"):
        biblio["title"] = payload["title"]
        row.provenance["filled_by"] = backend
    if not biblio.get("year") and payload.get("year"):
        biblio["year"] = int(payload["year"])
        row.provenance["filled_by"] = backend
    if not biblio.get("venue") and payload.get("venue"):
        biblio["venue"] = payload["venue"]
        row.provenance["filled_by"] = backend
    authors = payload.get("authors") or []
    if not biblio.get("authors") and authors:
        biblio["authors"] = [str(name) for name in authors if name]
        row.provenance["filled_by"] = backend


def crossref_work(doi: str, *, email: str = "") -> dict[str, Any] | None:
    import httpx

    params = {"mailto": email} if email else None
    try:
        resp = httpx.get(f"https://api.crossref.org/works/{doi}", params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        message = resp.json().get("message") or {}
    except (httpx.HTTPError, ValueError):
        return None
    titles = message.get("title") or []
    venues = message.get("container-title") or []
    issued = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = issued[0] if issued else None
    authors = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
        if name:
            authors.append(name)
    return {
        "title": titles[0] if titles else "",
        "year": year,
        "venue": venues[0] if venues else "",
        "authors": authors,
    }


def s2_paper(doi: str, *, cache_dir: Path, api_key: str) -> dict[str, Any] | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{doi.replace('/', '_')}.json"
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            return loaded
    import httpx

    try:
        resp = httpx.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "title,year,venue,authors,references.externalIds,references.title,references.year"},
            headers={"x-api-key": api_key},
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def s2_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
