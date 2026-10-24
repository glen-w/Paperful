"""Wanted report cards: one model for the workbench and the cleaning report.

"N found" is the number of Found stamps, which means ``doi_match`` rows only.
Held files that still need a look are "check", never "found". There is no
percent-complete figure on purpose.
"""

from __future__ import annotations

import csv
import io
from typing import Any

SCHEMA = "paperful.wanted_cards.v1"
_BUCKETS = ("have", "held", "missing")


def card_counts(data: dict[str, Any]) -> dict[str, int]:
    """Counts from ``ui.pages.wanted_rows`` output (stamps decide, not buckets)."""
    rows = [r for name in _BUCKETS for r in data.get(name, [])]
    return {
        "found": sum(1 for r in rows if r.get("stamp") == "found"),
        "check": sum(1 for r in rows if r.get("stamp") == "check"),
        "missing": len(data.get("missing", [])),
        "total": len(rows),
    }


def _card(row: dict[str, Any], bucket: str) -> dict[str, Any]:
    return {
        "key": row.get("key", ""),
        "title": row.get("title", ""),
        "doi": row.get("doi", ""),
        "bucket": bucket,
        "stamp": row.get("stamp", ""),
        "state": row.get("state", ""),
        "reason": row.get("miss_surface") or row.get("reason", ""),
        "reason_plain": row.get("miss_plain") or row.get("verify_plain", ""),
    }


def report_cards(data: dict[str, Any], *, collection: str = "") -> dict[str, Any]:
    cards = [_card(r, name) for name in _BUCKETS for r in data.get(name, [])]
    return {
        "schema": SCHEMA,
        "collection": collection,
        "counts": card_counts(data),
        "cards": cards,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        f"# Wanted report{': ' + report['collection'] if report.get('collection') else ''}",
        "",
        f"{counts['found']} found · {counts['check']} to check · {counts['missing']} missing",
        "",
        "| Stamp | Title | DOI | Why |",
        "| --- | --- | --- | --- |",
    ]
    for card in report["cards"]:
        stamp = card["stamp"].capitalize() or "Missing"
        title = str(card["title"]).replace("|", "\\|")
        lines.append(f"| {stamp} | {title} | {card['doi']} | {card['reason_plain']} |")
    return "\n".join(lines) + "\n"


def render_misses_csv(report: dict[str, Any]) -> str:
    """``misses.csv``: every card that is not a Found stamp, with its reason."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["key", "title", "doi", "stamp", "reason_code", "reason"])
    for card in report["cards"]:
        if card["stamp"] == "found":
            continue
        writer.writerow(
            [
                card["key"],
                card["title"],
                card["doi"],
                card["stamp"] or "missing",
                card["reason"],
                card["reason_plain"],
            ]
        )
    return buf.getvalue()
