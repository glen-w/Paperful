"""Freeze numbers, cites, and refs before a rewrite model call."""

from __future__ import annotations

import re
from typing import Iterable

_LATEX_CITE = re.compile(
    r"\\cite[A-Za-z]*(?:\[[^\]]*\]){0,2}\{([^}]+)\}"
)
_PANDOC_CITE = re.compile(r"\[@([^\]]+)\]")
_AUTHOR_YEAR = re.compile(
    r"\b([A-Z][A-Za-z'-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'-]+)?)\s+\((\d{4}[a-z]?)\)"
)
_FLOAT_REF = re.compile(
    r"\b(?:Figures?|Tables?|Figs?\.?)\s+[A-Za-z0-9]+",
    re.I,
)
_QUOTED = re.compile(r"“[^”]+”|\"[^\"]+\"")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PLACEHOLDER = re.compile(r"«PF[A-Z]\d+»")

_SPECS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("C", _LATEX_CITE),
    ("C", _PANDOC_CITE),
    ("Y", _AUTHOR_YEAR),
    ("F", _FLOAT_REF),
    ("Q", _QUOTED),
    ("N", _NUMBER),
)


def _latex_keys(text: str) -> list[str]:
    keys: list[str] = []
    for m in _LATEX_CITE.finditer(text or ""):
        for part in m.group(1).split(","):
            token = part.strip()
            if token:
                keys.append(token)
    return keys


def _pandoc_keys(text: str) -> list[str]:
    return [m.group(1).strip() for m in _PANDOC_CITE.finditer(text or "") if m.group(1).strip()]


def numbers_in(text: str) -> list[str]:
    return _NUMBER.findall(text or "")


def cites_ok(text: str, hay: str) -> bool:
    """Every cite key in ``text`` must already appear in ``hay`` (casefold)."""
    folded = (hay or "").casefold()
    for key in _latex_keys(text) + _pandoc_keys(text):
        if key.casefold() not in folded:
            return False
    return True


def numbers_ok(text: str, hay: str) -> bool:
    haystack = hay or ""
    for num in numbers_in(text):
        if num not in haystack:
            return False
    return True


def freeze_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Replace frozen spans with placeholders. Mapping is placeholder → original."""
    src = text or ""
    occupied: list[tuple[int, int]] = []
    spans: list[tuple[int, int, str]] = []
    for kind, rx in _SPECS:
        for m in rx.finditer(src):
            start, end = m.start(), m.end()
            if any(not (end <= a or start >= b) for a, b in occupied):
                continue
            occupied.append((start, end))
            spans.append((start, end, kind))
    spans.sort(key=lambda row: row[0])
    mapping: dict[str, str] = {}
    out: list[str] = []
    cursor = 0
    for i, (start, end, kind) in enumerate(spans):
        out.append(src[cursor:start])
        token = f"«PF{kind}{i}»"
        mapping[token] = src[start:end]
        out.append(token)
        cursor = end
    out.append(src[cursor:])
    return "".join(out), mapping


def apply_freeze(text: str, mapping: dict[str, str]) -> str:
    frozen = text or ""
    for placeholder, original in sorted(
        mapping.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        if original:
            frozen = frozen.replace(original, placeholder)
    return frozen


def thaw(text: str, mapping: dict[str, str]) -> str:
    out = text or ""
    for placeholder, original in mapping.items():
        out = out.replace(placeholder, original)
    return out


def placeholders_in(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text or "")


def freeze_preserved(
    *,
    selected_frozen: str,
    reply: str,
    mapping: dict[str, str],
) -> bool:
    """True when every selected placeholder is present unchanged; no extras added."""
    needed = placeholders_in(selected_frozen)
    got = placeholders_in(reply)
    if any(token not in reply for token in needed):
        return False
    if any(token not in mapping for token in got):
        return False
    return set(got) <= set(needed)


def extra_frozen_tokens(reply: str, mapping: Iterable[str]) -> bool:
    allowed = set(mapping)
    return any(token not in allowed for token in placeholders_in(reply))
