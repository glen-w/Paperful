"""``paperful.rewrite.plan.v1`` merge and serialisation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

SCHEMA = "paperful.rewrite.plan.v1"
EDIT_KINDS = ("replace", "insert", "delete", "comment")
SKIP_REASONS = (
    "no_unique_span",
    "overlap",
    "quote",
    "not_actionable",
    "needs_author",
    "no_evidence",
    "dismissed",
    "leakage",
    "cap",
)


@dataclass
class RewriteEdit:
    kind: str
    finding_ids: list[str]
    area: str
    loc: str = ""
    quote: str = ""
    replacement: str = ""
    body: str = ""
    source_paragraph: str = ""
    target_paragraph: str = ""
    start: int = -1
    end: int = -1

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        if self.kind != "replace":
            row.pop("replacement", None)
        if self.kind != "comment":
            row.pop("body", None)
        if not self.source_paragraph:
            row.pop("source_paragraph", None)
        if not self.target_paragraph:
            row.pop("target_paragraph", None)
        if self.start < 0:
            row.pop("start", None)
        if self.end < 0:
            row.pop("end", None)
        return row


@dataclass
class RewritePlan:
    edits: list[RewriteEdit] = field(default_factory=list)
    skips: list[dict[str, str]] = field(default_factory=list)
    worklog: dict[str, Any] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        addressed = [
            e.quote[:80] or (e.body[:80] if e.body else e.kind) for e in self.edits
        ]
        return {
            "schema": SCHEMA,
            "worklog": {
                "addressed": list(self.worklog.get("addressed") or addressed),
                "skipped": [
                    f"{s.get('finding_id')}: {s.get('reason')}" for s in self.skips
                ],
                "models": dict(self.models),
                **{
                    k: v
                    for k, v in (self.worklog or {}).items()
                    if k not in {"addressed", "skipped", "models"}
                },
            },
            "edits": [e.to_dict() for e in self.edits],
            "skips": list(self.skips),
        }


def _span(edit: RewriteEdit) -> tuple[int, int] | None:
    if edit.start >= 0 and edit.end > edit.start:
        return edit.start, edit.end
    return None


def merge_edits(
    edits: Iterable[RewriteEdit],
    *,
    max_edits: int = 80,
    existing_skips: list[dict[str, str]] | None = None,
) -> RewritePlan:
    """Keep document order; drop later overlapping body edits."""
    ordered = sorted(
        (e for e in edits if e.kind in EDIT_KINDS),
        key=lambda e: (e.start if e.start >= 0 else 10**9, e.kind != "comment"),
    )
    kept: list[RewriteEdit] = []
    skips = list(existing_skips or [])
    occupied: list[tuple[int, int]] = []
    for edit in ordered:
        if len(kept) >= max_edits:
            for fid in edit.finding_ids:
                skips.append({"finding_id": fid, "reason": "cap"})
            continue
        span = _span(edit)
        if span is not None and edit.kind != "comment":
            start, end = span
            if any(not (end <= a or start >= b) for a, b in occupied):
                for fid in edit.finding_ids:
                    skips.append({"finding_id": fid, "reason": "overlap"})
                continue
            occupied.append(span)
        kept.append(edit)
    return RewritePlan(edits=kept, skips=skips)
