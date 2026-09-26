"""OpenAlex reads for snowball. PDF lookup stays in sources/openalex.py."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

Progress = Callable[[str], None]

import httpx

from ..resolve import normalize_doi
from .candidate import Candidate
from .expand import cap_ids

API = "https://api.openalex.org"
KEY_URL = "https://openalex.org/settings/api"
SELECT = (
    "id,doi,display_name,publication_year,type,cited_by_count,language,"
    "referenced_works,authorships,primary_location,open_access,keywords"
)
Getter = Callable[[str, dict[str, Any]], dict[str, Any]]


class OpenAlexError(RuntimeError):
    pass


class OpenAlexBudgetExceeded(OpenAlexError):
    """Daily budget or a long reset. Burst 429s retry inside the client instead."""

    def __init__(
        self,
        message: str,
        *,
        reset_at: str | None = None,
        reset_in_s: int | None = None,
        pending_ids: list[str] | None = None,
        partial: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.reset_at = reset_at
        self.reset_in_s = reset_in_s
        self.pending_ids = list(pending_ids or [])
        self.partial = list(partial or [])


class OpenAlexClient:
    def __init__(
        self,
        *,
        email: str,
        api_key: str | None = None,
        sleep_s: float = 0.15,
        getter: Getter | None = None,
        progress: Progress | None = None,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        backoff_cap_s: float = 60.0,
        budget_wait_s: float = 0.0,
    ):
        self.email = email
        self.api_key = api_key if api_key is not None else os.environ.get("OPENALEX_API_KEY", "")
        self.sleep_s = sleep_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.budget_wait_s = budget_wait_s
        self.progress = progress
        self.stage = ""
        self.tally: Any = None
        self.deferred: dict[str, Any] | None = None
        self.emit: Callable[[list[Any]], None] | None = None
        self.from_created_date: str | None = None
        self._getter = getter
        self.requests = 0
        self.retries = 0
        self.status_429 = 0
        self._last = 0.0
        self._budget: OpenAlexBudgetExceeded | None = None
        self._using_key = False
        self._http_client: httpx.Client | None = None

    def _created_filter(self, from_created_date: str | None = None) -> str | None:
        """OpenAlex ``from_created_date`` (YYYY-MM-DD). Watch cursor, or an override."""
        value = (from_created_date or self.from_created_date or "").strip()
        return value or None

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._budget is not None:
            raise self._budget
        query = dict(params or {})
        if self.email:
            query["mailto"] = self.email
        self.requests += 1
        try:
            data = self._getter(path, query) if self._getter is not None else self._http(path, query)
        except OpenAlexBudgetExceeded as exc:
            self._budget = exc
            raise
        self._tally_works(data)
        return data

    def _http(self, path: str, query: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last
        if self.sleep_s and elapsed < self.sleep_s:
            time.sleep(self.sleep_s - elapsed)
        url = f"{API}{path}"
        client = self._client()
        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            try:
                resp = client.get(url, params=query, headers=self._headers())
            except (httpx.TransportError, httpx.TimeoutException):
                self.retries += 1
                if attempt < attempts - 1:
                    time.sleep(self._delay(attempt, None))
                    continue
                raise OpenAlexError(f"OpenAlex failed for {path}") from None
            self._last = time.monotonic()
            if resp.status_code in (401, 403) and self._using_key and self.api_key:
                raise OpenAlexError("OpenAlex API key was rejected")
            if resp.status_code == 429 or resp.status_code >= 500:
                self.status_429 += int(resp.status_code == 429)
                self.retries += 1
                reset_at, reset_in_s = _reset(resp)
                if (
                    resp.status_code == 429
                    and _is_budget(resp, self.budget_wait_s)
                    and self._promote_key()
                ):
                    continue
                if resp.status_code == 429 and _is_budget(resp, self.budget_wait_s):
                    raise OpenAlexBudgetExceeded(
                        "OpenAlex daily budget is spent",
                        reset_at=reset_at,
                        reset_in_s=reset_in_s,
                    )
                if attempt < attempts - 1:
                    time.sleep(self._delay(attempt, resp.headers.get("Retry-After")))
                    continue
                if resp.status_code == 429:
                    raise OpenAlexBudgetExceeded(
                        "OpenAlex daily budget is spent",
                        reset_at=reset_at,
                        reset_in_s=reset_in_s,
                    )
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise OpenAlexError("OpenAlex response was not an object")
            return data
        raise OpenAlexError(f"OpenAlex failed for {path}")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"paperful-snowball/0.1 (mailto:{self.email})",
        }
        if self._using_key and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _promote_key(self) -> bool:
        """Switch a keyless crawl onto the one configured key. Once only."""
        if self._using_key or not self.api_key:
            return False
        self._using_key = True
        self.note(keyless_limit_message(has_key=True))
        return True

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        parsed = _header_float(retry_after)
        if parsed is not None and parsed >= 0:
            return min(parsed, self.backoff_cap_s)
        base = self.backoff_base_s * (2**attempt)
        return min(self.backoff_cap_s, base * (0.5 + random.random() / 2))

    def note(self, message: str) -> None:
        """Print a milestone. The live bar updates on every note."""
        if self.tally is not None:
            self.tally.stage = self.stage or message
        if self.progress is not None:
            self.progress(message)
        self.touch()

    def touch(self) -> None:
        if self.tally is None:
            return
        self.tally.stage = self.stage or self.tally.stage
        self.tally.refresh()

    def _tally_works(self, data: dict[str, Any]) -> None:
        if self.tally is None:
            return
        self.tally.searches += 1
        results = data.get("results")
        if isinstance(results, list):
            self.tally.papers += len(results)
        elif data.get("id") or data.get("doi"):
            self.tally.papers += 1
        self.tally.refresh()

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=60.0, follow_redirects=True)
        return self._http_client

    def _collect(
        self,
        path: str,
        params: dict[str, Any],
        limit: int,
        *,
        use_cursor: bool = False,
    ) -> list[dict[str, Any]]:
        """Page while OpenAlex reports more hits. ``limit <= 0`` keeps every page (up to 50)."""
        if use_cursor:
            return self._collect_cursor(path, params, limit)
        uncapped = limit <= 0
        out: list[dict[str, Any]] = []
        page = 1
        while page <= 50 and (uncapped or len(out) < limit):
            room = 200 if uncapped else limit - len(out)
            query = dict(params)
            query["per_page"] = max(1, min(100, room))
            query["page"] = page
            payload = self.get(path, query)
            batch = list(payload.get("results") or [])
            if not batch:
                break
            out.extend(batch)
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
            if not meta:
                break
            count = int(meta.get("count") or 0)
            if len(out) >= count or len(batch) < int(query["per_page"]):
                break
            if not uncapped and len(out) >= limit:
                break
            page += 1
        return out if uncapped else out[:limit]

    def _collect_cursor(self, path: str, params: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        """Cursor pages. Used when a search asks for more than 50 pages."""
        uncapped = limit <= 0
        out: list[dict[str, Any]] = []
        cursor = "*"
        seen: set[str] = set()
        while cursor and cursor not in seen and (uncapped or len(out) < limit):
            seen.add(cursor)
            room = 100 if uncapped else limit - len(out)
            query = dict(params)
            query.pop("page", None)
            query["per_page"] = max(1, min(100, room))
            query["cursor"] = cursor
            payload = self.get(path, query)
            batch = list(payload.get("results") or [])
            if not batch:
                break
            out.extend(batch)
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
            nxt = str((meta or {}).get("next_cursor") or "")
            count = int((meta or {}).get("count") or 0)
            if not nxt or (count and len(out) >= count):
                break
            cursor = nxt
        return out if uncapped else out[:limit]

    def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        from_created_date: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to is not None:
            filters.append(f"to_publication_date:{year_to}-12-31")
        created = self._created_filter(from_created_date)
        if created:
            filters.append(f"from_created_date:{created}")
        params: dict[str, Any] = {"search": query, "select": SELECT}
        if filters:
            params["filter"] = ",".join(filters)
        use_cursor = limit <= 0 or limit > 5000
        return self._collect("/works", params, limit, use_cursor=use_cursor)

    def work_by_doi(self, doi: str) -> dict[str, Any] | None:
        payload = self.get(f"/works/https://doi.org/{doi}", {"select": SELECT})
        if payload.get("id") or payload.get("doi"):
            return payload
        return None

    def works_by_dois(
        self, dois: list[str], *, select: str = "id,doi,referenced_works"
    ) -> list[dict[str, Any]]:
        """Works for these DOIs. The default select is id, doi, and referenced_works."""
        out: list[dict[str, Any]] = []
        ids = [doi for doi in dois if doi]
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            try:
                out.extend(self._doi_batch(batch, select=select))
            except OpenAlexBudgetExceeded as exc:
                exc.partial = out + list(exc.partial or [])
                raise
        return out

    def _doi_batch(self, batch: list[str], *, select: str) -> list[dict[str, Any]]:
        """One DOI filter. A 400 is one bad id: split the batch and skip that id."""
        if not batch:
            return []
        try:
            payload = self.get(
                "/works",
                {
                    "filter": "doi:" + "|".join(batch),
                    "per_page": len(batch),
                    "select": select,
                },
            )
        except OpenAlexBudgetExceeded:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            if len(batch) == 1:
                return []
            mid = len(batch) // 2
            return self._doi_batch(batch[:mid], select=select) + self._doi_batch(batch[mid:], select=select)
        return list(payload.get("results") or [])

    def works_by_ids(self, openalex_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ids = list(openalex_ids)
        if self.tally is not None and ids:
            self.tally.track(len(ids))
        for start in range(0, len(ids), 100):
            batch = ids[start : start + 100]
            if not batch:
                continue
            try:
                payload = self.get(
                    "/works",
                    {
                        "filter": "openalex:" + "|".join(batch),
                        "per_page": len(batch),
                        "select": SELECT,
                    },
                )
            except OpenAlexBudgetExceeded as exc:
                exc.pending_ids = ids[start:]
                exc.partial = out
                raise
            out.extend(payload.get("results") or [])
            if self.tally is not None:
                self.tally.advance(len(batch))
        return out

    def works_citing(
        self,
        openalex_id: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: str | None = None,
        from_created_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Works that cite ``openalex_id`` (OpenAlex ``filter=cites:``)."""
        oa = short_id(openalex_id)
        if not oa:
            return []
        filters = [f"cites:{oa}"]
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to is not None:
            filters.append(f"to_publication_date:{year_to}-12-31")
        created = self._created_filter(from_created_date)
        if created:
            filters.append(f"from_created_date:{created}")
        params: dict[str, Any] = {"filter": ",".join(filters), "select": SELECT}
        if sort:
            params["sort"] = sort
        return self._collect("/works", params, limit)

    def works_by_keywords(
        self,
        slugs: list[str],
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: str | None = None,
        from_created_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Works carrying any of ``slugs``. ``limit`` must be a positive integer."""
        if limit <= 0:
            raise OpenAlexError(
                "keyword_hop_limit must be a positive integer. "
                "all is not allowed; a keyword filter is an open query."
            )
        cleaned = [slug for slug in slugs if slug]
        if not cleaned:
            return []
        filters = ["keywords.id:" + "|".join(cleaned)]
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to is not None:
            filters.append(f"to_publication_date:{year_to}-12-31")
        created = self._created_filter(from_created_date)
        if created:
            filters.append(f"from_created_date:{created}")
        params: dict[str, Any] = {"filter": ",".join(filters), "select": SELECT}
        if sort:
            params["sort"] = sort
        return self._collect("/works", params, limit)

    def works_by_author_orcid(
        self,
        orcid: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
        from_created_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """OpenAlex works for an ORCID (fills gaps left by the ORCID public API)."""
        cleaned = normalize_orcid(orcid)
        if not cleaned:
            return []
        filters = [f"author.orcid:{cleaned}"]
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to is not None:
            filters.append(f"to_publication_date:{year_to}-12-31")
        created = self._created_filter(from_created_date)
        if created:
            filters.append(f"from_created_date:{created}")
        self.stage = self.stage or f"OpenAlex author {cleaned}"
        return self._collect(
            "/works",
            {"filter": ",".join(filters), "select": SELECT},
            limit,
        )



def keyless_limit_message(*, has_key: bool, reset_at: str | None = None) -> str:
    """Shown when the no-key allowance for this public address is spent."""
    text = (
        "OpenAlex's free no-key allowance for this network address is used up. "
        "It is shared by everyone on the same public IP, which is common on a VPN. "
        f"The reliable fix is a free API key: {KEY_URL}"
    )
    if has_key:
        return text + " Continuing with your API key."
    wait = f" Or wait until {reset_at}." if reset_at else ""
    return (
        text
        + " Set OPENALEX_API_KEY, then run paperful snowball resume."
        + wait
        + " Changing VPN server can reach a fresh allowance, but an API key is more reliable."
    )


def _header_float(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _reset(resp: httpx.Response) -> tuple[str | None, int | None]:
    raw = _header_float(resp.headers.get("X-RateLimit-Reset"))
    if raw is None:
        return None, None
    seconds = max(0, int(raw))
    when = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return when.replace(microsecond=0).isoformat(), seconds


def _is_budget(resp: httpx.Response, budget_wait_s: float) -> bool:
    """True when waiting would sit on a daily reset rather than a short burst."""
    remaining = _header_float(resp.headers.get("X-RateLimit-Remaining"))
    if remaining is not None and remaining <= 0:
        return True
    reset_s = _header_float(resp.headers.get("X-RateLimit-Reset"))
    retry_s = _header_float(resp.headers.get("Retry-After"))
    wait = reset_s if reset_s is not None else retry_s
    if wait is None:
        return False
    return wait > budget_wait_s and wait >= 60


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
            "is_oa": bool((work.get("open_access") or {}).get("is_oa")),
            "language": str(work.get("language") or ""),
            "cited_by_count": int(work.get("cited_by_count") or 0),
        },
        why=why,
        status="new",
        provenance={"backend": "openalex", "endpoint": "/works", "retrieved_at": _now()},
        gate=gate,
        score=float(work.get("cited_by_count") or 0),
    )


def keyword_slug(raw: str) -> str:
    """OpenAlex keyword id as a slug (``machine-learning``)."""
    text = str(raw or "").strip()
    if "/keywords/" in text:
        text = text.rsplit("/keywords/", 1)[-1]
    return text.strip().strip("/").lower().replace(" ", "-")


def keyword_slugs(work: dict[str, Any]) -> list[str]:
    """Every keyword slug on a work, highest score first."""
    return chosen_keywords(work, limit=0, min_score=0.0)


def chosen_keywords(work: dict[str, Any], *, limit: int, min_score: float) -> list[str]:
    """Top ``limit`` keyword slugs at or above ``min_score``. ``limit <= 0`` keeps every one."""
    ranked: list[tuple[float, str]] = []
    for item in work.get("keywords") or []:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score < min_score:
            continue
        slug = keyword_slug(str(item.get("id") or item.get("display_name") or ""))
        if slug:
            ranked.append((score, slug))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    out: list[str] = []
    for _score, slug in ranked:
        if slug not in out:
            out.append(slug)
        if limit > 0 and len(out) >= limit:
            break
    return out


def referenced_ids(work: dict[str, Any], per_hop_limit: int = 0) -> list[str]:
    """OpenAlex reference ids for a work. ``per_hop_limit <= 0`` keeps every id."""
    raw = [short_id(str(ref)) for ref in (work.get("referenced_works") or [])]
    return cap_ids([item for item in raw if item], per_hop_limit)


def normalize_orcid(raw: str) -> str:
    """Strip URL wrapper; return XXXX-XXXX-XXXX-XXXX or empty."""
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.rstrip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    text = text.upper()
    if len(text) == 19 and text.count("-") == 3:
        return text
    digits = text.replace("-", "")
    if len(digits) == 16 and digits[:15].isdigit() and (digits[15].isdigit() or digits[15] == "X"):
        return f"{digits[0:4]}-{digits[4:8]}-{digits[8:12]}-{digits[12:16]}"
    return ""

