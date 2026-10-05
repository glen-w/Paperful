"""Opt-in author-request ledger and ResearchGate URL detection.

Paperful never clicks ResearchGate “Request full-text”. When ``[request].channels``
includes ``rg``, handoff may open an existing publication URL in the system
browser so the operator can click.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Config
from .zot import Item

SCHEMA = "paperful.author_request.v1"
CHANNEL_RG = "rg"
CHANNEL_EMAIL = "email"
_RG_HOSTS = ("researchgate.net",)
_SKIP_PATH = ("/profile/", "/scientific-contributions/", "/login")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def request_channels(cfg: Config) -> str:
    return (cfg.request_channels or "off").strip().lower() or "off"


def rg_handoff_enabled(cfg: Config) -> bool:
    if cfg.request_rg_override is False:
        return False
    if cfg.request_rg_override is True:
        return True
    return request_channels(cfg) in {"rg", "both", "rg_then_email_after_days"}


def apply_request_rg_override(cfg: Config, flag: bool | None) -> None:
    cfg.request_rg_override = flag


def author_requests_path(cfg: Config) -> Path:
    return cfg.state_dir / "author-requests.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_researchgate_url(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in _RG_HOSTS)


def is_researchgate_publication_url(url: str) -> bool:
    text = (url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    if not is_researchgate_url(text):
        return False
    path = (urlparse(text).path or "").lower()
    if any(tok in path for tok in _SKIP_PATH):
        return False
    return "/publication/" in path or "/paper/" in path or path.startswith("/pub/")


def _urls_from_extra(extra: str) -> list[str]:
    return _URL_RE.findall(extra or "")


def researchgate_publication_url(item: Item) -> str:
    candidates = [(item.url or "").strip()]
    candidates.extend(_urls_from_extra(item.extra or ""))
    for raw in candidates:
        if is_researchgate_publication_url(raw):
            return raw
    return ""


def load_requested_keys(cfg: Config, *, channel: str = CHANNEL_RG) -> set[str]:
    path = author_requests_path(cfg)
    if not path.is_file():
        return set()
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if str(row.get("channel") or "") != channel:
            continue
        key = str(row.get("key") or "").strip()
        if key:
            keys.add(key)
    return keys


def already_requested(cfg: Config, key: str, *, channel: str = CHANNEL_RG) -> bool:
    return key in load_requested_keys(cfg, channel=channel)


def record_request(
    cfg: Config,
    *,
    key: str,
    url: str,
    channel: str = CHANNEL_RG,
    status: str = "handoff_opened",
    doi: str = "",
    title: str = "",
) -> dict[str, Any]:
    row = {
        "schema": SCHEMA,
        "key": key,
        "doi": doi,
        "title": title,
        "channel": channel,
        "url": url,
        "status": status,
        "requested_at": _now(),
    }
    path = author_requests_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
