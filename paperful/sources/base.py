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
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None
