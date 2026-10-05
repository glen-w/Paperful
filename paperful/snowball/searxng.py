"""Opt-in local SearXNG client for author-site discovery. Never a default source."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
import httpx

from ..config import Config
from .authors import host_of, is_blocked_host, is_simple_host


def searxng_base_url(cfg: Config) -> str:
    return (cfg.searxng_base_url or os.environ.get("SEARXNG_BASE_URL") or "").rstrip("/")


def rank_hit(url: str, *, surname: str, title: str = "") -> int:
    text = (url or "").lower()
    host = host_of(url)
    score = 0
    token = (surname or "").lower()
    if token and token in text:
        score += 50
    if text.split("?", 1)[0].endswith(".pdf"):
        score += 20
    if is_simple_host(url):
        score += 15
    if is_blocked_host(host):
        return -1
    if title:
        bits = [p for p in title.lower().split() if len(p) > 4][:4]
        if bits and all(p in text for p in bits[:2]):
            score += 10
    return score


def search_author_site(
    cfg: Config,
    *,
    name: str,
    affiliation: str = "",
    surname: str = "",
    getter: Any = None,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    base = searxng_base_url(cfg)
    if not base:
        return []
    query = f'"{name}"'
    if affiliation:
        query += f" {affiliation}"
    query += " (homepage OR faculty OR github.io OR weebly) filetype:pdf"
    payload = _cached_search(base, query, getter=getter, cache_dir=cache_dir)
    results = payload.get("results") if isinstance(payload, dict) else []
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in results or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        score = rank_hit(url, surname=surname or name.split()[-1] if name else "")
        if score < 0:
            continue
        ranked.append((score, {"url": url, "title": str(row.get("title") or ""), "score": score}))
    ranked.sort(key=lambda pair: -pair[0])
    return [row for _score, row in ranked[:8]]


def _cached_search(
    base: str, query: str, *, getter: Any, cache_dir: Path | None
) -> dict[str, Any]:
    key = hashlib.sha256(f"{base}\n{query}".encode()).hexdigest()[:16]
    if cache_dir is not None:
        path = cache_dir / f"{key}.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    if getter is not None:
        data = getter(query)
    else:
        data = _http_search(base, query)
    if cache_dir is not None and isinstance(data, dict):
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return data if isinstance(data, dict) else {}


def _http_search(base: str, query: str) -> dict[str, Any]:
    url = f"{base}/search"
    for attempt in range(3):
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(url, params={"q": query, "format": "json"})
            if resp.status_code >= 500:
                time.sleep(0.5 * (2**attempt))
                continue
            if resp.status_code >= 400:
                return {}
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            time.sleep(0.5 * (2**attempt))
    return {}
