"""OpenAlex topic-classifier epoch: stamp runs, spot pre-migration state.

OpenAlex moved works to new topic assignments in October 2026 (keywords are now
linked to topics). Keyword hops before that date cannot be reproduced, so every
snowball run records which side of the change it ran on.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

#: Works switched to the new topic assignments; local snapshots must reload from here.
TOPIC_MIGRATION = date(2026, 10, 14)
EPOCH_BEFORE = "pre-2026-10"
EPOCH_AFTER = "2026-10"


def topic_epoch(on: date) -> str:
    return EPOCH_AFTER if on >= TOPIC_MIGRATION else EPOCH_BEFORE


def openalex_stamp(today: date | None = None) -> dict[str, Any]:
    """Run-metadata keys for ``summary.json`` (additive)."""
    day = today or datetime.now(timezone.utc).date()
    return {
        "openalex_run_date": day.isoformat(),
        "openalex_topic_epoch": topic_epoch(day),
    }


def parse_day(raw: str | None) -> date | None:
    """Date part of an ISO date or timestamp; ``None`` when unparseable."""
    text = (raw or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def predates_migration(raw: str | None) -> bool:
    """True when ``raw`` is a date before the topic migration (unknown is False)."""
    day = parse_day(raw)
    return day is not None and day < TOPIC_MIGRATION
