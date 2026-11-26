"""Invisible Unicode and mixed-script homoglyph channels (not combining marks)."""

from __future__ import annotations

import re
import unicodedata

# Zero-width, BOM, word joiner, Mongolian vowel separator, bidi overrides,
# isolates, Unicode Tags (U+E0001–U+E007F), and other non-rendering format chars
# used as hidden payloads. NBSP and combining marks stay.
INVISIBLE_CHARS: tuple[str, ...] = (
    "\u200b",
    "\u200c",
    "\u200d",
    "\ufeff",
    "\u2060",
    "\u180e",
    "\u034f",
    "\u206a",
    "\u206b",
    "\u206c",
    "\u206d",
    "\u206e",
    "\u206f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
    *tuple(chr(cp) for cp in range(0xE0001, 0xE007F + 1)),
)
INVISIBLE_RE = re.compile("[" + "".join(re.escape(ch) for ch in INVISIBLE_CHARS) + "]")
_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_CYR_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ј": "j",
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
        "І": "I",
    }
)
_CODE_FENCE = re.compile(r"```.*?```|`[^`]+`", re.DOTALL)
_MATH = re.compile(r"\$\$[\s\S]+?\$\$|\$[^$]+\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)")


def strip_invisible(text: str) -> tuple[str, int]:
    """Remove hidden format characters. Returns (clean, count removed)."""
    src = text or ""
    n = len(INVISIBLE_RE.findall(src))
    if not n:
        return src, 0
    return INVISIBLE_RE.sub("", src), n


def unicode_stego_flags(text: str) -> list[str]:
    """Compact flags for peer-review (zero-width count, mixed-script tokens)."""
    src = text or ""
    flags: list[str] = []
    zw = len(INVISIBLE_RE.findall(src))
    if zw:
        flags.append(f"zero_width:{zw}")
    mixed = 0
    for token in re.findall(r"\S+", src):
        if _LATIN.search(token) and _CYRILLIC.search(token):
            mixed += 1
    if mixed:
        flags.append(f"mixed_script_tokens:{mixed}")
    return flags


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rx in (_CODE_FENCE, _MATH):
        for m in rx.finditer(text or ""):
            spans.append((m.start(), m.end()))
    return spans


def _in_span(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= index < b for a, b in spans)


def fold_homoglyphs(text: str) -> tuple[str, int]:
    """Fold mixed Latin+Cyrillic tokens to Latin lookalikes. Skip code/math."""
    src = text or ""
    protected = _protected_spans(src)
    parts: list[str] = []
    n = 0
    for m in re.finditer(r"\S+|\s+", src):
        token = m.group(0)
        if token.isspace() or _in_span(m.start(), protected):
            parts.append(token)
            continue
        if _LATIN.search(token) and _CYRILLIC.search(token):
            folded = token.translate(_CYR_TO_LATIN)
            if folded != token:
                n += 1
                parts.append(folded)
                continue
        parts.append(token)
    return "".join(parts), n


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")
