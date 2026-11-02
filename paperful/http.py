"""Shared HTTP client: redirect SSRF check and bounded retries.

``fetch_pdf`` keeps its own retry loop. Pass ``retries=0`` there. Other
callers get jittered retries on 429 and transport errors. 401 and 403 are
not retried. Operator-configured localhost services (SearXNG, GROBID,
Twenty, Ollama) pass ``guard=False``.
"""

from __future__ import annotations

import time
from typing import Any, Literal, overload

import httpx

from .download import is_fetchable_url

_RETRY_STATUS = 429


def _guard_request(request: httpx.Request) -> None:
    url = str(request.url)
    if not is_fetchable_url(url, resolve=False):
        raise httpx.RequestError(f"blocked URL {url}", request=request)


class _RetryClient:
    """Proxy around ``httpx.Client`` that retries 429 and transport errors."""

    def __init__(self, inner: httpx.Client, *, retries: int) -> None:
        self._inner = inner
        self._retries = max(0, int(retries))

    def __enter__(self) -> _RetryClient:
        self._inner.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._inner.__exit__(*args)

    def close(self) -> None:
        self._inner.close()

    def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:
        last_exc: BaseException | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._inner.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= self._retries:
                    raise
                time.sleep(_backoff(attempt))
                continue
            if resp.status_code in {401, 403}:
                return resp
            if resp.status_code == _RETRY_STATUS and attempt < self._retries:
                time.sleep(_backoff(attempt))
                continue
            return resp
        if last_exc is not None:
            raise last_exc
        raise httpx.TransportError("request failed")

    def get(self, url: Any, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: Any, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def head(self, url: Any, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _backoff(attempt: int) -> float:
    base = 0.05 * (2**attempt)
    jitter = (time.time_ns() % 1000) / 1000 * base
    return base + jitter


@overload
def client(
    *,
    timeout: float | httpx.Timeout | None = ...,
    follow_redirects: bool = ...,
    headers: dict[str, str] | None = ...,
    retries: Literal[0],
    guard: bool = ...,
    **kwargs: Any,
) -> httpx.Client: ...


@overload
def client(
    *,
    timeout: float | httpx.Timeout | None = ...,
    follow_redirects: bool = ...,
    headers: dict[str, str] | None = ...,
    retries: int = ...,
    guard: bool = ...,
    **kwargs: Any,
) -> httpx.Client | _RetryClient: ...


def client(
    *,
    timeout: float | httpx.Timeout | None = 30.0,
    follow_redirects: bool = True,
    headers: dict[str, str] | None = None,
    retries: int = 2,
    guard: bool = True,
    **kwargs: Any,
) -> httpx.Client | _RetryClient:
    """httpx client. ``guard`` rejects non-public URL literals before send."""
    hooks = dict(kwargs.pop("event_hooks", {}) or {})
    if guard:
        existing = list(hooks.get("request") or [])
        existing.append(_guard_request)
        hooks["request"] = existing
    inner = httpx.Client(
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=headers,
        event_hooks=hooks,
        **kwargs,
    )
    if retries <= 0:
        return inner
    return _RetryClient(inner, retries=retries)
