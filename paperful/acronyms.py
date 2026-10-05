"""Collection-scoped acronym allowlist for Title Case.

Harvest is frequency and shape only: an all-caps token inside mixed-case
titles, abstracts, or venues. No model. ``fix-metadata`` and parent create
keep those tokens uppercase when they recase an ALL CAPS title.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .identity import seed_slug
from .zot import Item

SCHEMA = "paperful.acronyms.v1"
_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{2,9}\b")
# A real Roman numeral, not merely letters from that alphabet (so LCD stays).
_ROMAN = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)
_SMALL = frozenset(
    {
        "AND",
        "THE",
        "FOR",
        "FROM",
        "WITH",
        "VIA",
        "PER",
        "BUT",
        "NOR",
    }
)


@dataclass(frozen=True)
class Acronym:
    token: str
    count: int


def _is_roman(token: str) -> bool:
    return bool(token) and bool(_ROMAN.fullmatch(token))


def _uniform(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return True
    return all(ch.isupper() for ch in letters) or all(ch.islower() for ch in letters)


def tokens_in(text: str) -> set[str]:
    """All-caps tokens that stand out inside mixed-case text."""
    raw = (text or "").strip()
    if not raw or _uniform(raw):
        return set()
    found: set[str] = set()
    for match in _TOKEN.finditer(raw):
        token = match.group(0)
        if token in _SMALL or _is_roman(token):
            continue
        if sum(ch.isalpha() for ch in token) < 2:
            continue
        found.add(token)
    return found


def harvest(items: list[Item], *, min_count: int = 2) -> list[Acronym]:
    """Count each token once per item. Longer tokens need more repeats."""
    if min_count < 1:
        raise ValueError("min_count must be at least 1")
    counts: dict[str, int] = {}
    for item in items:
        seen: set[str] = set()
        for field in (item.title, item.abstract or "", item.publication_title or ""):
            seen |= tokens_in(field)
        for token in seen:
            counts[token] = counts.get(token, 0) + 1
    rows: list[Acronym] = []
    for token, count in counts.items():
        need = min_count if len(token) <= 6 else max(min_count, 5)
        if count >= need:
            rows.append(Acronym(token=token, count=count))
    rows.sort(key=lambda row: (-row.count, row.token))
    return rows


def allowlist_dir(state_dir: Path) -> Path:
    return state_dir / "acronyms"


def file_slug(collections: list[str], *, library: bool) -> str:
    if library or not collections:
        return "library"
    return seed_slug("+".join(collections), fallback="library")


def allowlist_path(state_dir: Path, slug: str) -> Path:
    return allowlist_dir(state_dir) / f"{slug}.json"


def write_allowlist(
    state_dir: Path,
    slug: str,
    *,
    scope: str,
    rows: list[Acronym],
    min_count: int,
    n_items: int,
) -> Path:
    """Replace harvested tokens. A hand-edited ``extra`` list is kept."""
    path = allowlist_path(state_dir, slug)
    extra = _read_extra(path)
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "scope": scope,
        "min_count": min_count,
        "items": n_items,
        "tokens": [{"token": row.token, "count": row.count} for row in rows],
        "extra": extra,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def _read_extra(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(body, dict):
        return []
    extra: list[str] = []
    seen: set[str] = set()
    for token in body.get("extra") or []:
        text = str(token or "").strip().upper()
        if text and text not in seen:
            seen.add(text)
            extra.append(text)
    return extra


def load_acronym_allowlist(state_dir: Path) -> frozenset[str]:
    """Union of every ``state/acronyms/*.json`` tokens list plus ``extra``."""
    root = allowlist_dir(state_dir)
    if not root.is_dir():
        return frozenset()
    tokens: set[str] = set()
    for path in sorted(root.glob("*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(body, dict):
            continue
        for row in body.get("tokens") or []:
            if isinstance(row, dict) and row.get("token"):
                tokens.add(str(row["token"]).strip().upper())
            elif isinstance(row, str) and row.strip():
                tokens.add(row.strip().upper())
        for extra in body.get("extra") or []:
            text = str(extra or "").strip().upper()
            if text:
                tokens.add(text)
    return frozenset(tokens)
