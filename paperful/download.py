"""Validated PDF fetching with retries."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import httpx

MAX_PDF_BYTES = 300 * 1024 * 1024
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class DownloadError(Exception):
    pass


@dataclass
class Download:
    content: bytes
    md5: str
    final_url: str


def looks_like_pdf(head: bytes) -> bool:
    return b"%PDF-" in head[:1024]


def is_fetchable_url(url: str) -> bool:
    """Absolute http(s) URL that httpx can request while the client holds cookies.

    `javascript:void(0)` is a relative URL to httpx. Cookie merging then asks
    urllib to parse `/void(0)` and raises ValueError, which aborts a run.
    """
    raw = (url or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return False
    try:
        parsed = httpx.URL(raw)
    except httpx.InvalidURL:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.host)


def fetch_pdf(
    client: httpx.Client,
    url: str,
    referer: str | None = None,
    min_bytes: int = 10_000,
    retries: int = 3,
) -> Download:
    """GET `url`, insisting on real PDF bytes. Raises DownloadError otherwise."""
    if not is_fetchable_url(url):
        raise DownloadError("not an http(s) URL")
    headers = {"Accept": "application/pdf,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    last = "unknown error"
    for attempt in range(retries):
        try:
            with client.stream("GET", url, headers=headers, timeout=90) as resp:
                if resp.status_code in _RETRY_STATUSES:
                    last = f"HTTP {resp.status_code}"
                    _sleep(resp, attempt)
                    continue
                if resp.status_code >= 400:
                    raise DownloadError(f"HTTP {resp.status_code}")
                chunks: list[bytes] = []
                total = 0
                first = b""
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    if not first:
                        first = chunk
                        if not looks_like_pdf(first):
                            ctype = resp.headers.get("content-type", "?")
                            raise DownloadError(f"not a PDF (content-type {ctype})")
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        raise DownloadError("file exceeds size cap")
                content = b"".join(chunks)
            if len(content) < min_bytes:
                raise DownloadError(f"too small ({len(content)} bytes)")
            return Download(
                content=content,
                md5=hashlib.md5(content).hexdigest(),
                final_url=str(resp.url),
            )
        except DownloadError:
            raise
        except ValueError as exc:
            # Cookie merging rejects some non-http URLs with ValueError
            # (`unknown url type`) instead of httpx.InvalidURL.
            raise DownloadError(str(exc) or "invalid URL") from exc
        except httpx.HTTPError as exc:
            last = type(exc).__name__
            time.sleep(1.5 * (attempt + 1))
    raise DownloadError(last)


def _sleep(resp: httpx.Response, attempt: int) -> None:
    retry_after = resp.headers.get("Retry-After")
    try:
        delay = float(retry_after) if retry_after else 2.0 * (attempt + 1)
    except ValueError:
        delay = 2.0 * (attempt + 1)
    time.sleep(min(delay, 30))
