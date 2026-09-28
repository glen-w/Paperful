"""Validated PDF fetching with retries."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import httpx

MAX_PDF_BYTES = 300 * 1024 * 1024
_RETRY_STATUSES = {429, 500, 502, 503, 504}
# Short connect; keep a long read for large PDFs once the socket is open.
_PDF_TIMEOUT = httpx.Timeout(connect=15.0, read=90.0, write=90.0, pool=15.0)
_TRANSPORT_ERRORS = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)
# Transport blips get one retry; status retries use the caller ``retries`` cap.
_TRANSPORT_ATTEMPTS = 2


class DownloadError(Exception):
    pass


def is_transport_download_error(exc: DownloadError | str) -> bool:
    """True when ``fetch_pdf`` failed on connect/read/pool, not HTTP/body."""
    msg = str(exc)
    return msg in {
        "ConnectTimeout",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutException",
    }


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
    transport_fails = 0
    status_fails = 0
    # Bound the loop: status retries + transport retries, whichever is larger.
    max_attempts = max(retries, _TRANSPORT_ATTEMPTS)
    for attempt in range(max_attempts):
        try:
            with client.stream("GET", url, headers=headers, timeout=_PDF_TIMEOUT) as resp:
                if resp.status_code in _RETRY_STATUSES:
                    last = f"HTTP {resp.status_code}"
                    status_fails += 1
                    if status_fails >= retries:
                        break
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
        except _TRANSPORT_ERRORS as exc:
            last = type(exc).__name__
            transport_fails += 1
            if transport_fails >= _TRANSPORT_ATTEMPTS:
                break
            time.sleep(1.5 * transport_fails)
        except httpx.HTTPError as exc:
            last = type(exc).__name__
            status_fails += 1
            if status_fails >= retries:
                break
            time.sleep(1.5 * (attempt + 1))
    raise DownloadError(last)


def _sleep(resp: httpx.Response, attempt: int) -> None:
    retry_after = resp.headers.get("Retry-After")
    try:
        delay = float(retry_after) if retry_after else 2.0 * (attempt + 1)
    except ValueError:
        delay = 2.0 * (attempt + 1)
    time.sleep(min(delay, 30))
