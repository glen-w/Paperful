"""Polite OpenAlex reads for snowball. PDF lookup stays in sources/openalex.py."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from ..resolve import normalize_doi
from .candidate import Candidate
from .expand import cap_ids

API = "https://api.openalex.org"
SELECT = (
    "id,doi,display_name,publication_year,type,cited_by_count,"
    "referenced_works,authorships,primary_location"
)
Getter = Callable[[str, dict[str, Any]], dict[str, Any]]


class OpenAlexError(RuntimeError):
    pass


class OpenAlexClient:
    def __init__(
        self,
        *,
        email: str,
        api_key: str | None = None,
        sleep_s: float = 0.15,
        getter: Getter | None = None,
    ):
        self.email = email
        self.api_key = api_key if api_key is not None else os.environ.get("OPENALEX_API_KEY", "")
        self.sleep_s = sleep_s
        self._getter = getter
        self.requests = 0
        self.retries = 0
        self.status_429 = 0
        self._last = 0.0

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        if self.email:
            query["mailto"] = self.email
        self.requests += 1
        if self._getter is not None:
            return self._getter(path, query)
        return self._http(path, query)

    def _http(self, path: str, query: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last
        if self.sleep_s and elapsed < self.sleep_s:
            time.sleep(self.sleep_s - elapsed)
        headers = {
            "Accept": "application/json",
            "User-Agent": f"paperful-snowball/0.1 (mailto:{self.email})",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{API}{path}"
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            for attempt in range(6):
                resp = client.get(url, params=query, headers=headers)
                self._last = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    self.status_429 += int(resp.status_code == 429)
                    self.retries += 1
                    if attempt < 5:
                        time.sleep(min(2.0 * (attempt + 1), 30.0))
                        continue
                if resp.status_code == 404:
                    return {}
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise OpenAlexError("OpenAlex response was not an object")
                return data
        raise OpenAlexError(f"OpenAlex failed for {path}")

    def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to is not None:
            filters.append(f"to_publication_date:{year_to}-12-31")
        params: dict[str, Any] = {
            "search": query,
            "per_page": max(1, min(limit, 200)),
            "select": SELECT,
        }
        if filters:
            params["filter"] = ",".join(filters)
        payload = self.get("/works", params)
        return list(payload.get("results") or [])

    def work_by_doi(self, doi: str) -> dict[str, Any] | None:
        payload = self.get(f"/works/https://doi.org/{doi}", {"select": SELECT})
        if payload.get("id") or payload.get("doi"):
            return payload
        return None

    def works_by_ids(self, openalex_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for start in range(0, len(openalex_ids), 50):
            batch = openalex_ids[start : start + 50]
            if not batch:
                continue
            payload = self.get(
                "/works",
                {
                    "filter": "openalex:" + "|".join(batch),
                    "per_page": len(batch),
                    "select": SELECT,
                },
            )
            out.extend(payload.get("results") or [])
        return out


def short_id(url: str) -> str:
    return (url or "").rstrip("/").split("/")[-1]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def work_to_candidate(
    work: dict[str, Any],
    *,
    run_id: str,
    seed: dict[str, str],
    hop: int,
    direction: str,
    why: str,
    gate: str,
) -> Candidate:
    doi = normalize_doi(str(work.get("doi") or "")) or ""
    oa = short_id(str(work.get("id") or ""))
    authors: list[str] = []
    for row in work.get("authorships") or []:
        author = row.get("author") or {}
        name = (author.get("display_name") or row.get("raw_author_name") or "").strip()
        if name:
            authors.append(name)
    year = work.get("publication_year")
    venue = ""
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    if isinstance(source, dict):
        venue = str(source.get("display_name") or "")
    return Candidate(
        run_id=run_id,
        seed=seed,
        hop=hop,
        direction=direction,
        ids={"doi": doi, "openalex": oa},
        biblio={
            "title": work.get("display_name") or "",
            "year": int(year) if year else None,
            "authors": authors,
            "venue": venue,
            "type": work.get("type") or "",
            "oa_url": (loc.get("pdf_url") or loc.get("landing_page_url") or ""),
        },
        why=why,
        status="new",
        provenance={"backend": "openalex", "endpoint": "/works", "retrieved_at": _now()},
        gate=gate,
        score=float(work.get("cited_by_count") or 0),
    )


def referenced_ids(work: dict[str, Any], per_hop_limit: int) -> list[str]:
    raw = [short_id(str(ref)) for ref in (work.get("referenced_works") or [])]
    return cap_ids([item for item in raw if item], per_hop_limit)
