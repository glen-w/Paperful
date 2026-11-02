"""Export and import screening rows. Dry-run unless ``apply`` is set.

``--apply`` writes the ledger. Library parents are created only when
``collection`` is set, through the existing search-apply path.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from .identify import work_identity
from .screen import append_screen_decision

# Shared columns. Covidence, Rayyan, and ASReview each read a subset.
CSV_FIELDS = (
    "identity",
    "decision",
    "reason",
    "title",
    "authors",
    "year",
    "journal",
    "doi",
    "url",
    "abstract",
)

_FORMATS = frozenset({"csv", "ris", "covidence", "rayyan", "asreview"})


def normalise_format(fmt: str) -> str:
    name = (fmt or "csv").strip().lower()
    if name in {"included.csv", "included"}:
        return "csv"
    if name not in _FORMATS:
        raise ValueError(
            f"unknown format {fmt!r}; use csv, ris, covidence, rayyan, or asreview"
        )
    return name


def export_text(
    rows: list[dict[str, Any]],
    *,
    fmt: str,
    decisions: dict[str, dict[str, Any]] | None = None,
    only_included: bool = True,
) -> str:
    kind = normalise_format(fmt)
    chosen = _select(rows, decisions or {}, only_included=only_included)
    if kind == "ris":
        return _ris(chosen)
    return _csv(chosen)


def parse_import(text: str, *, fmt: str) -> list[dict[str, str]]:
    """Rows with identity, decision, reason, title, doi, url. Decision defaults to include."""
    kind = normalise_format(fmt)
    if kind == "ris":
        return _parse_ris(text)
    return _parse_csv(text)


def apply_import(
    state_dir: Path,
    slug: str,
    rows: list[dict[str, str]],
    *,
    reviewer: str,
    apply: bool,
) -> dict[str, Any]:
    """Append decisions. Dry-run counts them and writes nothing."""
    planned = []
    for row in rows:
        ident = str(row.get("identity") or "").strip()
        if not ident:
            continue
        decision = str(row.get("decision") or "include").strip().lower()
        if decision not in {"include", "exclude", "maybe"}:
            decision = "include"
        planned.append(
            {
                "identity": ident,
                "decision": decision,
                "reason": str(row.get("reason") or ""),
                "title": str(row.get("title") or ""),
                "doi": str(row.get("doi") or ""),
                "url": str(row.get("url") or ""),
                "year": str(row.get("year") or ""),
            }
        )
    written = 0
    if apply:
        for row in planned:
            append_screen_decision(
                state_dir,
                slug,
                identity=row["identity"],
                decision=row["decision"],
                reason=row["reason"],
                reviewer=reviewer or "operator",
            )
            written += 1
    return {
        "planned": len(planned),
        "written": written,
        "rows": planned,
        "apply": apply,
    }


def create_included_parents(
    cfg: Any,
    rows: list[dict[str, Any]],
    collection: str,
    *,
    backend: Any = None,
) -> dict[str, Any]:
    """Create metadata parents for included rows. PDFs stay on ``paperful run``."""
    from ..search.apply import apply_candidates

    candidates = []
    for row in rows:
        if str(row.get("decision") or "include") != "include":
            continue
        doi = str(row.get("doi") or "")
        if not doi and str(row.get("identity") or "").startswith("10."):
            doi = str(row["identity"])
        candidates.append(
            {
                "title": row.get("title") or row.get("identity") or "",
                "doi": doi,
                "url": row.get("url") or "",
                "year": row.get("year") or None,
                "status": "new",
            }
        )
    if not collection:
        return {"created": 0, "skipped": "no collection"}
    return apply_candidates(cfg, candidates, collection, backend=backend)


def _select(
    rows: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    only_included: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        ident = work_identity(row)
        decision = decisions.get(ident) or {}
        label = str(decision.get("decision") or row.get("decision") or "")
        if only_included and label and label != "include":
            continue
        if only_included and not label and decisions:
            continue
        merged = dict(row)
        merged["identity"] = ident
        merged["decision"] = label or "include"
        merged["reason"] = str(decision.get("reason") or row.get("reason") or "")
        out.append(merged)
    if not rows and decisions:
        for ident, decision in decisions.items():
            if only_included and decision.get("decision") != "include":
                continue
            out.append(
                {
                    "identity": ident,
                    "decision": decision.get("decision") or "",
                    "reason": decision.get("reason") or "",
                    "doi": ident if ident.startswith("10.") else "",
                    "title": ident,
                }
            )
    return out


def _csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})
    return buf.getvalue()


def _ris(rows: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for row in rows:
        lines = ["TY  - JOUR", f"TI  - {row.get('title') or row.get('identity') or ''}"]
        doi = str(row.get("doi") or "")
        if not doi and str(row.get("identity") or "").startswith("10."):
            doi = str(row["identity"])
        if doi:
            lines.append(f"DO  - {doi}")
        if row.get("url"):
            lines.append(f"UR  - {row['url']}")
        if row.get("year"):
            lines.append(f"PY  - {row['year']}")
        if row.get("decision"):
            lines.append(f"N1  - decision: {row['decision']}")
        lines.append("ER  - ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, str]] = []
    for raw in reader:
        if not raw:
            continue
        lowered = {
            (key or "").strip().lower(): (value or "").strip()
            for key, value in raw.items()
        }
        doi = lowered.get("doi") or lowered.get("do") or ""
        ident = (
            lowered.get("identity")
            or doi
            or lowered.get("url")
            or lowered.get("title")
            or ""
        )
        out.append(
            {
                "identity": ident,
                "decision": lowered.get("decision") or "include",
                "reason": lowered.get("reason") or "",
                "title": lowered.get("title") or "",
                "doi": doi,
                "url": lowered.get("url") or "",
                "year": lowered.get("year") or lowered.get("published year") or "",
            }
        )
    return out


def _parse_ris(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 6 or line[2:6] != "  - ":
            continue
        tag = line[:2].upper()
        value = line[6:].strip()
        if tag == "TY":
            current = {}
        elif tag == "TI":
            current["title"] = value
        elif tag == "DO":
            current["doi"] = value
        elif tag == "UR":
            current["url"] = value
        elif tag == "PY":
            current["year"] = value[:4]
        elif tag == "N1" and value.lower().startswith("decision:"):
            current["decision"] = value.split(":", 1)[1].strip()
        elif tag == "ER":
            ident = (
                current.get("doi") or current.get("url") or current.get("title") or ""
            )
            if ident:
                current["identity"] = ident
                current.setdefault("decision", "include")
                out.append(current)
            current = {}
    return out


def dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
