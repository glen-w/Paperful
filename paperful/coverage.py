"""Briefing / note / file DOI lists vs collection membership.

Sibling of ``refs gap`` (PDF bibliographies). Always dry-run — findings only.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .dedupe import normalize_dedupe_title, scope_slug
from .identity import LibraryFingerprint, publication_year
from .resolve import DOI_RE, normalize_doi

SCHEMA = "paperful.coverage.pack.v1"
# Required on every pack.json from write_pack(). Extra keys may be added.
COVERAGE_PACK_KEYS = frozenset(
    {"schema", "scope", "created_at", "source", "counts", "rows"}
)

# Snowball briefing line: `2019 — Title — \`10.1000/x\`` (optional stamps after).
_BRIEFING_LINE = re.compile(
    r"^(?P<year>\d{4}|n\.d\.)\s*[—\-]\s*(?P<title>.+?)"
    r"(?:\s*[—\-]\s*`(?P<doi>10\.\d{4,9}/[^`]+)`)?\s*$",
    re.IGNORECASE,
)


@dataclass
class Mention:
    doi: str = ""
    title: str = ""
    year: int | None = None
    raw: str = ""


@dataclass
class CoverageRow:
    doi: str = ""
    title: str = ""
    year: int | None = None
    status: str = "missing"  # in_collection | missing | ambiguous
    item_key: str = ""
    exists_kind: str = ""
    suggested_action: str = "skip"
    provenance_hint: str = ""
    finding: str = ""


@dataclass
class CoveragePack:
    rows: list[CoverageRow] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    scope: str = ""


class _StripHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def strip_html(html: str) -> str:
    parser = _StripHTML()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return parser.text()


def _clean_doi(raw: str | None) -> str:
    doi = normalize_doi(raw) or ""
    return doi.rstrip("`*'\"")


def extract_mentions(text: str) -> list[Mention]:
    """Pull DOIs (and optional title/year) from markdown, HTML, or DOI lists."""
    if not text or not text.strip():
        return []
    plain = text
    if "<" in text and re.search(r"<(?:p|div|br|a|li|span)\b", text, re.I):
        plain = strip_html(text)
    mentions: list[Mention] = []
    seen: set[str] = set()

    def _add(doi: str = "", title: str = "", year: int | None = None, raw: str = "") -> None:
        doi = _clean_doi(doi)
        title = (title or "").strip()
        if doi:
            if doi in seen:
                for row in mentions:
                    if row.doi == doi:
                        if title and not row.title:
                            row.title = title
                        if year is not None and row.year is None:
                            row.year = year
                        break
                return
            seen.add(doi)
            mentions.append(Mention(doi=doi, title=title, year=year, raw=raw))
            return
        if title and year is not None:
            ident = f"{normalize_dedupe_title(title)}|{year}"
            if ident in seen:
                return
            seen.add(ident)
            mentions.append(Mention(title=title, year=year, raw=raw))

    # Briefing-shaped bullets (title/year + optional DOI).
    for line in plain.splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if not cleaned:
            continue
        m = _BRIEFING_LINE.match(cleaned)
        if m:
            year_raw = m.group("year")
            year = None if year_raw == "n.d." else publication_year(year_raw)
            _add(
                doi=m.group("doi") or "",
                title=m.group("title") or "",
                year=year,
                raw=cleaned,
            )
            continue
        # DOI-only line (or URL line).
        doi = _clean_doi(cleaned)
        if doi and cleaned.lower().startswith(("10.", "http://", "https://", "doi:")):
            _add(doi=doi, raw=cleaned)

    # Any remaining inline DOIs (markdown body + raw HTML for hrefs).
    for blob in (plain, text):
        for match in DOI_RE.finditer(blob):
            _add(doi=match.group(1), raw=match.group(0))

    return mentions


def load_text_from_note(backend: Any, key_or_path: str, *, out_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    """Load note HTML/text. ``key_or_path`` is a filesystem path or note item key."""
    path = Path(key_or_path)
    if path.is_file():
        return path.read_text(encoding="utf-8"), {"kind": "file", "ref": str(path)}
    key = key_or_path.strip()
    if not key:
        raise ValueError("empty --from-note")
    # Mirror-first for standalone notes.
    if out_dir is not None:
        note_path = out_dir / "_notes" / key / "note.html"
        if note_path.is_file():
            return note_path.read_text(encoding="utf-8"), {
                "kind": "note",
                "ref": key,
                "via": "mirror",
            }
        alt = out_dir / "_notes" / key
        if alt.is_dir():
            for candidate in sorted(alt.glob("*.html")):
                return candidate.read_text(encoding="utf-8"), {
                    "kind": "note",
                    "ref": key,
                    "via": "mirror",
                }
    raw = backend.raw_item(key) if hasattr(backend, "raw_item") else None
    if raw is None:
        raise LookupError(f"note {key!r} not found")
    data = raw.get("data") or raw
    if str(data.get("itemType") or "") != "note":
        raise LookupError(f"{key!r} is not a note (itemType={data.get('itemType')!r})")
    html = str(data.get("note") or "")
    return html, {"kind": "note", "ref": key, "via": "library"}


def classify_mentions(
    mentions: list[Mention],
    collection_fp: LibraryFingerprint,
    library_fp: LibraryFingerprint | None = None,
    *,
    tag_lookup: dict[str, list[str]] | None = None,
) -> list[CoverageRow]:
    """Mark each mention in_collection / missing / ambiguous vs ``-C``."""
    rows: list[CoverageRow] = []
    for mention in mentions:
        doi = normalize_doi(mention.doi) or ""
        title = (mention.title or "").strip()
        year = mention.year
        col_hit = collection_fp.find(doi or None, title or None, year)
        lib_hit = None
        if library_fp is not None and col_hit is None:
            lib_hit = library_fp.find(doi or None, title or None, year)

        if col_hit is not None:
            hint = ""
            if tag_lookup:
                tags = tag_lookup.get(col_hit.item_key) or []
                hint = _provenance_hint(tags)
            rows.append(
                CoverageRow(
                    doi=doi,
                    title=title,
                    year=year,
                    status="in_collection",
                    item_key=col_hit.item_key,
                    exists_kind=col_hit.kind,
                    suggested_action="skip",
                    provenance_hint=hint,
                )
            )
            continue
        if lib_hit is not None:
            rows.append(
                CoverageRow(
                    doi=doi,
                    title=title,
                    year=year,
                    status="ambiguous",
                    item_key=lib_hit.item_key,
                    exists_kind=lib_hit.kind,
                    suggested_action="skip",
                    finding="in_library_outside_collection",
                )
            )
            continue
        if doi:
            action = "ingest-dois"
        elif title:
            action = "snowball doi"
        else:
            action = "skip"
        rows.append(
            CoverageRow(
                doi=doi,
                title=title,
                year=year,
                status="missing",
                suggested_action=action,
            )
        )
    return rows


def _provenance_hint(tags: list[str]) -> str:
    bits: list[str] = []
    for tag in tags:
        low = str(tag or "").strip().lower()
        if low.startswith("grey:") or low.startswith("oa:") or low.startswith("campus:"):
            bits.append(low)
    return ", ".join(bits[:4])


def write_pack(
    state_dir: Path,
    scope: str,
    rows: list[CoverageRow],
    source: dict[str, Any],
    *,
    stamp: str | None = None,
) -> Path:
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "coverage" / f"{stamp}-{scope_slug(scope)}"
    folder.mkdir(parents=True, exist_ok=True)
    missing = [r for r in rows if r.status == "missing"]
    payload = {
        "schema": SCHEMA,
        "scope": scope,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": source,
        "counts": {
            "mentioned": len(rows),
            "in_collection": sum(1 for r in rows if r.status == "in_collection"),
            "missing": len(missing),
            "ambiguous": sum(1 for r in rows if r.status == "ambiguous"),
            "ingest_dois": sum(
                1 for r in missing if r.suggested_action == "ingest-dois"
            ),
        },
        "rows": [asdict(r) for r in rows],
    }
    (folder / "pack.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (folder / "dois.txt").write_text(
        "".join(
            f"{r.doi}\n"
            for r in rows
            if r.doi and r.status == "missing" and r.suggested_action == "ingest-dois"
        ),
        encoding="utf-8",
    )
    (folder / "pack.md").write_text(
        _markdown(scope, payload["counts"], rows), encoding="utf-8"
    )
    return folder


def dois_from_coverage_pack(path: Path) -> list[str]:
    """DOIs from a ``paperful.coverage.pack.v1`` whose action is ingest-dois."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") not in {"", "missing"}:
            continue
        action = str(row.get("suggested_action") or "")
        if action and action != "ingest-dois":
            continue
        doi = normalize_doi(row.get("doi"))
        if not doi or doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return out


def _markdown(scope: str, counts: dict[str, Any], rows: list[CoverageRow]) -> str:
    lines = [
        f"# Collection coverage — {scope}",
        "",
        f"Mentioned {counts.get('mentioned', 0)}; "
        f"in collection {counts.get('in_collection', 0)}; "
        f"missing {counts.get('missing', 0)}; "
        f"ambiguous {counts.get('ambiguous', 0)}.",
        "",
        "| Status | DOI | Title | Year | Item | Action | Hint |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        title = (row.title or "").replace("|", "/")
        lines.append(
            f"| {row.status} | {row.doi or ''} | {title} | {row.year or ''} | "
            f"{row.item_key} | {row.suggested_action} | {row.provenance_hint} |"
        )
    lines.append("")
    return "\n".join(lines)
