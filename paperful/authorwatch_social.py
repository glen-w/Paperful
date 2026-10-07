"""Parse operator-saved social follow exports (HTML/CSV). No live scraping."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .snowball.openalex import normalize_orcid

_ORCID_RE = re.compile(
    r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b", re.IGNORECASE
)
_RG_PROFILE = re.compile(
    r"researchgate\.net/profile/([^/\">\s]+)",
    re.IGNORECASE,
)
_ACAD_PROFILE = re.compile(
    r"academia\.edu/([^/\">\s]+)",
    re.IGNORECASE,
)
_LINKEDIN_PROFILE = re.compile(
    r"linkedin\.com/in/([^/\">\s?#]+)",
    re.IGNORECASE,
)


class AuthorwatchSocialError(ValueError):
    """Unrecognized social export markup."""


@dataclass(frozen=True)
class SocialRow:
    display_name: str
    orcid: str = ""
    profile_url: str = ""
    source: str = ""


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = ""
        for key, val in attrs:
            if key.lower() == "href" and val:
                href = val.strip()
                break
        self._href = href
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        label = " ".join(self._text).strip()
        self.links.append((self._href, label))
        self._href = ""
        self._text = []


def _slug_to_name(slug: str) -> str:
    text = (slug or "").replace("-", " ").replace("_", " ").strip()
    return " ".join(part.capitalize() for part in text.split() if part)


def _rows_from_csv(text: str) -> list[SocialRow]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise AuthorwatchSocialError("CSV needs a header row (name, orcid).")
    fields = {str(k or "").strip().lower(): k for k in reader.fieldnames}
    out: list[SocialRow] = []
    for raw in reader:
        name = ""
        orcid = ""
        for key in ("name", "display_name", "author", "full name"):
            col = fields.get(key)
            if col and raw.get(col):
                name = str(raw[col]).strip()
                break
        for key in ("orcid", "orcid_id"):
            col = fields.get(key)
            if col and raw.get(col):
                orcid = normalize_orcid(str(raw[col]))
                break
        if not name and not orcid:
            continue
        out.append(SocialRow(display_name=name or orcid, orcid=orcid, source="csv"))
    return out


def _rows_from_html(text: str, source: str) -> list[SocialRow]:
    collector = _LinkCollector()
    try:
        collector.feed(text)
    except Exception:
        pass
    seen: set[str] = set()
    out: list[SocialRow] = []
    patterns = {
        "rg": _RG_PROFILE,
        "researchgate": _RG_PROFILE,
        "linkedin": _LINKEDIN_PROFILE,
        "academia": _ACAD_PROFILE,
    }
    pat = patterns.get(source.lower(), _RG_PROFILE)
    for href, label in collector.links:
        m = pat.search(href)
        if not m:
            continue
        slug = m.group(1)
        key = f"{source}:{slug.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        name = label or _slug_to_name(slug)
        orcid = ""
        om = _ORCID_RE.search(label) or _ORCID_RE.search(href)
        if om:
            orcid = normalize_orcid(om.group(1))
        out.append(
            SocialRow(
                display_name=name,
                orcid=orcid,
                profile_url=href,
                source=source,
            )
        )
    for om in _ORCID_RE.finditer(text):
        orcid = normalize_orcid(om.group(1))
        key = f"orcid:{orcid}"
        if key in seen:
            continue
        seen.add(key)
        out.append(SocialRow(display_name=orcid, orcid=orcid, source=source))
    return out


def parse_social_file(path: Path, *, source: str) -> list[SocialRow]:
    """Read a saved HTML or CSV export. Never uses the network."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        raise AuthorwatchSocialError(
            "JSON follow export: use authorwatch import --source json."
        )
    if stripped.lower().startswith("<!doctype") or stripped.lower().startswith("<html"):
        rows = _rows_from_html(text, source)
    elif "," in text.splitlines()[0] if text.splitlines() else False:
        rows = _rows_from_csv(text)
    else:
        rows = _rows_from_html(text, source)
    if not rows:
        raise AuthorwatchSocialError(
            f"No people found in {path.name}. Save the follows page as HTML or export CSV."
        )
    return rows
