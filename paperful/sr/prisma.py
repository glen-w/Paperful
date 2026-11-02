"""PRISMA 2020 flow from exact screening counts. No recall percentage."""

from __future__ import annotations

from typing import Any

SCHEMA = "paperful.sr.prisma.v1"

# identified = screened + pending. pending is never negative.
# screened = included + excluded + maybe.


def prisma_counts(
    identified: int,
    *,
    included: int,
    excluded: int,
    maybe: int,
) -> dict[str, int]:
    screened = max(0, included) + max(0, excluded) + max(0, maybe)
    identified_n = max(max(0, identified), screened)
    pending = identified_n - screened
    return {
        "identified": identified_n,
        "screened": screened,
        "included": max(0, included),
        "excluded": max(0, excluded),
        "maybe": max(0, maybe),
        "pending": pending,
    }


def counts_hold(counts: dict[str, int]) -> bool:
    screened = counts["included"] + counts["excluded"] + counts["maybe"]
    return (
        counts["pending"] >= 0
        and counts["screened"] == screened
        and counts["identified"] == counts["screened"] + counts["pending"]
    )


def prisma_svg(counts: dict[str, int], *, title: str = "PRISMA 2020") -> str:
    """Deterministic flow diagram. Boxes are the counts; nothing is illustrated."""
    rows = [
        ("Identification", counts["identified"]),
        ("Screened", counts["screened"]),
        ("Included", counts["included"]),
        ("Excluded", counts["excluded"]),
        ("Maybe", counts["maybe"]),
        ("Pending", counts["pending"]),
    ]
    width = 420
    height = 36 + 44 * len(rows)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'role="img" aria-label="{_xml(title)}">',
        f"<title>{_xml(title)}</title>",
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="16" y="22" font-family="sans-serif" font-size="14">{_xml(title)}</text>',
    ]
    y = 36
    for label, value in rows:
        parts.append(
            f'<rect x="16" y="{y}" width="388" height="36" fill="none" stroke="#222"/>'
        )
        parts.append(
            f'<text x="28" y="{y + 23}" font-family="sans-serif" font-size="13">'
            f"{_xml(label)}: {int(value)}</text>"
        )
        y += 44
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def prisma_payload(counts: dict[str, int]) -> dict[str, Any]:
    return {"schema": SCHEMA, **counts}


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
