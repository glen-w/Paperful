"""Opt-in PyPI update notice. Off by default; sends no telemetry.

When ``[updates] check = true``, ``paperful doctor`` may ask PyPI for the
latest paperful version and report when a newer one exists. The request
carries only the standard HTTP user agent — no library data, no identifier,
nothing about the operator. Any failure (offline, timeout, bad payload) is
silent: an update check must never break or slow a real command, so callers
bound it with a short timeout and cache the result for a day.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PYPI_JSON_URL = "https://pypi.org/pypi/paperful/json"
CACHE_NAME = "update-check.json"
CACHE_TTL_S = 24 * 60 * 60


def _parse_version(text: str) -> tuple[int, ...] | None:
    parts: list[int] = []
    for chunk in str(text or "").strip().split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def newer_version(current: str, latest: str) -> bool:
    """True when ``latest`` is a strictly newer dotted-numeric version."""
    cur = _parse_version(current)
    lat = _parse_version(latest)
    if cur is None or lat is None:
        return False
    width = max(len(cur), len(lat))
    return lat + (0,) * (width - len(lat)) > cur + (0,) * (width - len(cur))


def fetch_latest_version(
    *, timeout_s: float = 3.0, opener: Callable[..., Any] | None = None
) -> str:
    """Latest paperful version from PyPI, or "" on any failure."""
    try:
        if opener is not None:
            payload = opener(PYPI_JSON_URL, timeout=timeout_s)
        else:
            import httpx

            resp = httpx.get(
                PYPI_JSON_URL,
                timeout=timeout_s,
                headers={"User-Agent": "paperful-update-check"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            payload = resp.json()
        if isinstance(payload, dict):
            info = payload.get("info") or {}
            if isinstance(info, dict):
                return str(info.get("version") or "").strip()
    except Exception:
        return ""
    return ""


def cached_latest(state_dir: Path, *, now: float | None = None) -> str:
    """Version cached by a previous check, or "" when stale/missing."""
    path = state_dir / CACHE_NAME
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        stamp = float(body.get("checked_at") or 0)
        moment = time.time() if now is None else now
        if moment - stamp <= CACHE_TTL_S:
            return str(body.get("latest") or "").strip()
    except Exception:
        return ""
    return ""


def check_for_update(
    current: str,
    state_dir: Path,
    *,
    fetcher: Callable[[], str] | None = None,
    now: float | None = None,
) -> str:
    """Newer version string when one exists, else "" (never raises)."""
    moment = time.time() if now is None else now
    latest = cached_latest(state_dir, now=moment)
    if not latest:
        latest = (fetcher or fetch_latest_version)()
        if latest:
            try:
                from paperful.fsio import atomic_write_json

                atomic_write_json(
                    state_dir / CACHE_NAME,
                    {"checked_at": moment, "latest": latest},
                )
            except OSError:
                pass
    if latest and newer_version(current, latest):
        return latest
    return ""
