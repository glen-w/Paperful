"""Shared types for sources."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol

import httpx

from ..config import Config
from ..zot import Item

if TYPE_CHECKING:
    from ..session import BrowserSession


class ApiKeyRejected(Exception):
    """A request sent a key and the server refused it. This is not a missing paper."""

    def __init__(self, service: str):
        self.service = service
        super().__init__(f"{service} API key was rejected")


class Outcome(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    CAPTCHA = "captcha"
    ERROR = "error"
    SKIPPED = "skipped"  # source not applicable (e.g. no DOI)


@dataclass
class Candidate:
    url: str
    source: str
    outcome: Outcome = Outcome.FOUND
    referer: str | None = None
    note: str = ""
    alternates: list[str] = field(
        default_factory=list
    )  # further PDF URLs to try if `url` fails
    content: bytes | None = (
        None  # pre-fetched PDF bytes (e.g. htmlpdf); skips HTTP download
    )
    playbook: str = ""  # grey playbook name when the direct lane hit one

    @classmethod
    def miss(cls, source: str, outcome: Outcome, note: str = "") -> Candidate:
        return cls(url="", source=source, outcome=outcome, note=note)

    @property
    def urls(self) -> list[str]:
        seen: list[str] = []
        for u in [self.url, *self.alternates]:
            if u and u not in seen:
                seen.append(u)
        return seen


@dataclass
class Context:
    config: Config
    client: httpx.Client
    mirror_failures: dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    browser: BrowserSession | None = None

    def mirror_ok(self, mirror: str) -> bool:
        return (
            self.mirror_failures.get(mirror, 0)
            < self.config.mirror_failures_before_skip
        )

    def mirror_failed(self, mirror: str) -> None:
        with self.lock:
            self.mirror_failures[mirror] = self.mirror_failures.get(mirror, 0) + 1

    def mirror_succeeded(self, mirror: str) -> None:
        with self.lock:
            self.mirror_failures[mirror] = 0


class Source(Protocol):
    NAME: str

    def find(self, item: Item, ctx: Context) -> Candidate: ...


def _sent_api_key(headers: dict[str, str] | None) -> bool:
    if not headers:
        return False
    for name, value in headers.items():
        if name.lower() in {"authorization", "x-api-key"} and str(value).strip():
            return True
    return False


def _service_name(url: str) -> str:
    host = url.split("/")[2] if "://" in url else url
    if "core.ac.uk" in host:
        return "CORE"
    if "openalex.org" in host:
        return "OpenAlex"
    if "semanticscholar.org" in host:
        return "Semantic Scholar"
    return host


def http_json(
    ctx: Context,
    url: str,
    params: dict | None = None,
    timeout: float = 30,
    headers: dict[str, str] | None = None,
) -> dict | None:
    """GET JSON, returning None on any HTTP/network/parse failure. Honours one 429 Retry-After."""
    try:
        resp = ctx.client.get(url, params=params, timeout=timeout, headers=headers)
        if resp.status_code == 429:
            try:
                delay = min(float(resp.headers.get("Retry-After", "5")), 20.0)
            except ValueError:
                delay = 5.0
            time.sleep(delay)
            resp = ctx.client.get(url, params=params, timeout=timeout, headers=headers)
        if resp.status_code in (401, 403) and _sent_api_key(headers):
            raise ApiKeyRejected(_service_name(url))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None
