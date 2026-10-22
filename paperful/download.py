"""Validated PDF fetching with retries."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

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
# Manual redirect hops (client may have follow_redirects=True by default).
_MAX_REDIRECTS = 10

# Hostnames that must never be fetched even when DNS is skipped (offline tests).
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
    }
)


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


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for loopback, private, link-local, multicast, unspecified, reserved."""
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def is_public_fetch_host(
    host: str,
    *,
    resolve: bool = True,
    resolver: Callable[[str], list[str]] | None = None,
) -> bool:
    """True when ``host`` is safe to fetch for library PDF URLs.

    Blocks loopback / RFC1918 / link-local / metadata literals and known
    metadata hostnames. When ``resolve`` is true, also rejects names that
    resolve only to blocked addresses. DNS failure is fail-open so offline
    fixture hosts (``x.test``) still pass ``is_fetchable_url``.
    """
    raw = (host or "").strip().lower().rstrip(".")
    if not raw:
        return False
    # Strip IPv6 brackets from URL hosts.
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if raw in _BLOCKED_HOSTNAMES or raw.endswith(".localhost"):
        return False
    if raw.endswith(".local") or raw.endswith(".internal"):
        return False
    try:
        if _ip_is_blocked(ipaddress.ip_address(raw)):
            return False
        return True
    except ValueError:
        pass

    if not resolve:
        return True

    lookup = resolver or _resolve_host_ips
    try:
        addrs = lookup(raw)
    except OSError:
        return True
    if not addrs:
        return True
    for addr in addrs:
        try:
            if _ip_is_blocked(ipaddress.ip_address(addr)):
                return False
        except ValueError:
            continue
    return True


def _resolve_host_ips(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    out: list[str] = []
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def is_fetchable_url(url: str, *, resolve: bool = True) -> bool:
    """Absolute http(s) URL that httpx can request while the client holds cookies.

    `javascript:void(0)` is a relative URL to httpx. Cookie merging then asks
    urllib to parse `/void(0)` and raises ValueError, which aborts a run.

    Also rejects loopback / private / link-local / cloud-metadata targets so a
    poisoned library URL cannot SSRF the operator machine (see SECURITY.md).
    """
    raw = (url or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return False
    try:
        parsed = httpx.URL(raw)
    except httpx.InvalidURL:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        return False
    return is_public_fetch_host(parsed.host, resolve=resolve)


def fetch_pdf(
    client: httpx.Client,
    url: str,
    referer: str | None = None,
    min_bytes: int = 10_000,
    retries: int = 3,
) -> Download:
    """GET `url`, insisting on real PDF bytes. Raises DownloadError otherwise."""
    if not is_fetchable_url(url):
        raise DownloadError("not an http(s) URL or blocked host")
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
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                if not is_fetchable_url(current):
                    raise DownloadError("not an http(s) URL or blocked host")
                with client.stream(
                    "GET",
                    current,
                    headers=headers,
                    timeout=_PDF_TIMEOUT,
                    follow_redirects=False,
                ) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        location = resp.headers.get("location")
                        if not location:
                            raise DownloadError(
                                f"HTTP {resp.status_code} without Location"
                            )
                        current = urljoin(str(resp.url), location)
                        continue
                    if resp.status_code in _RETRY_STATUSES:
                        last = f"HTTP {resp.status_code}"
                        status_fails += 1
                        if status_fails >= retries:
                            raise DownloadError(last)
                        _sleep(resp, attempt)
                        break
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
                                raise DownloadError(
                                    f"not a PDF (content-type {ctype})"
                                )
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > MAX_PDF_BYTES:
                            raise DownloadError("file exceeds size cap")
                    content = b"".join(chunks)
                    final_url = str(resp.url)
                if len(content) < min_bytes:
                    raise DownloadError(f"too small ({len(content)} bytes)")
                return Download(
                    content=content,
                    md5=hashlib.md5(content).hexdigest(),
                    final_url=final_url,
                )
            else:
                raise DownloadError("too many redirects")
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
