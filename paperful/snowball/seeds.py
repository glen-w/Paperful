"""DOI / ORCID seed lists from a file or stdin."""

from __future__ import annotations

import sys
from pathlib import Path

from ..resolve import normalize_doi
from .openalex import normalize_orcid


def parse_seed_lines(text: str) -> list[str]:
    """One token per line. ``#`` comments. Blank lines skipped. Order kept, deduped."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def read_seeds_text(path: str, *, stdin=None) -> str:
    from .command import SnowballError

    handle = stdin if stdin is not None else sys.stdin
    if path.strip() == "-":
        if getattr(handle, "isatty", lambda: False)():
            raise SnowballError("stdin is a TTY. Pass --seeds-file PATH or pipe a list.")
        return handle.read()
    dest = Path(path).expanduser()
    if not dest.is_file():
        raise SnowballError(f"Seeds file not found: {dest}")
    return dest.read_text(encoding="utf-8")


def dois_from_seeds(tokens: list[str]) -> list[str]:
    from .command import SnowballError

    out: list[str] = []
    seen: set[str] = set()
    bad: list[str] = []
    for token in tokens:
        doi = normalize_doi(token) or normalize_doi(_strip_url(token))
        if not doi:
            bad.append(token)
            continue
        if doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    if bad:
        raise SnowballError(f"Not a DOI: {bad[0]!r}")
    return out


def orcids_from_seeds(tokens: list[str]) -> list[str]:
    from .command import SnowballError

    out: list[str] = []
    seen: set[str] = set()
    bad: list[str] = []
    for token in tokens:
        cleaned = normalize_orcid(token)
        if not cleaned:
            bad.append(token)
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    if bad:
        raise SnowballError(f"Not an ORCID iD: {bad[0]!r}")
    return out


def merge_tokens(*groups: list[str] | tuple[str, ...] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for item in group or ():
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out


def _strip_url(raw: str) -> str:
    text = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :].strip()
    return text
