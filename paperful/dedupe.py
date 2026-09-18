"""Collection-scoped duplicate packs. Classify on disk; trash only with --apply.

Keep rule (high_doi and proposed medium keeps), highest first:

1. stored/imported PDF (`has_pdf`)
2. linked PDF URL only (`has_linked_url`)
3. richer metadata: non-placeholder title, then a date/year, then more creators
4. older `dateAdded` (missing sorts last), then item key

Same normalised DOI with titles below `TITLE_DIVERGE_BELOW` is held
(`held_divergent_title`) and never trashed. Title+year groups are
`needs_review` and are skipped on `--apply` unless the caller passes
`apply_medium`.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resolve import normalize_doi, normalize_title, title_similarity
from .zot import Item

TITLE_DIVERGE_BELOW = 0.60
PHASES = ("high_doi", "medium_title_year", "all")
SCHEMA = "paperful.dedupe_pack.v1"
_SCOPE_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


@dataclass
class DedupeGroup:
    phase: str
    reason: str
    keep: str | None
    trash: list[str]
    held: bool
    needs_review: bool
    doi: str | None = None
    title_key: str | None = None
    year: int | None = None
    members: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GapCounts:
    items: int
    no_stored_pdf: int
    linked_url_only: int
    missing_doi: int


def normalize_dedupe_title(title: str | None) -> str:
    """Lowercase, unescape HTML entities, strip tags and punctuation."""
    return normalize_title(html.unescape(title or ""))


def classify(items: list[Item], phase: str = "all") -> list[DedupeGroup]:
    """Group duplicates. `phase` is `high_doi`, `medium_title_year`, or `all`."""
    phase = (phase or "all").strip().lower()
    if phase not in PHASES:
        raise ValueError(f"Unknown phase {phase!r}. Known: {', '.join(PHASES)}")
    groups: list[DedupeGroup] = []
    used: set[str] = set()
    if phase in ("high_doi", "all"):
        doi_groups = _high_doi(items)
        groups.extend(doi_groups)
        for group in doi_groups:
            used.update(member["key"] for member in group.members)
    if phase in ("medium_title_year", "all"):
        rest = [it for it in items if it.key not in used]
        groups.extend(_medium_title_year(rest))
    return groups


def summarize_gaps(items: list[Item]) -> GapCounts:
    no_stored = linked = missing = 0
    for item in items:
        if not item.has_pdf:
            no_stored += 1
        if item.has_linked_url and not item.has_pdf:
            linked += 1
        if not item.doi:
            missing += 1
    return GapCounts(
        items=len(items),
        no_stored_pdf=no_stored,
        linked_url_only=linked,
        missing_doi=missing,
    )


def pack_counts(groups: list[DedupeGroup], n_items: int) -> dict[str, int]:
    return {
        "items": n_items,
        "groups": len(groups),
        "held": sum(1 for g in groups if g.held),
        "trash_candidates": sum(len(g.trash) for g in groups if not g.held),
        "high_doi_groups": sum(1 for g in groups if g.phase == "high_doi"),
        "medium_groups": sum(1 for g in groups if g.phase == "medium_title_year"),
    }


def scope_slug(scope: str) -> str:
    slug = _SCOPE_UNSAFE.sub("-", scope.strip()).strip("-").lower()
    return (slug or "scope")[:60]


def write_pack(
    state_dir: Path,
    scope: str,
    groups: list[DedupeGroup],
    *,
    phase: str,
    n_items: int,
    stamp: str | None = None,
) -> tuple[Path, Path]:
    """Write JSON + Markdown under state/dedupe-packs/. Returns both paths."""
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "dedupe-packs"
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{stamp}-{scope_slug(scope)}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    counts = pack_counts(groups, n_items)
    payload = {
        "schema": SCHEMA,
        "scope": scope,
        "phase": phase,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "counts": counts,
        "groups": [asdict(g) for g in groups],
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(scope, phase, counts, groups), encoding="utf-8")
    return json_path, md_path


def actionable_groups(
    groups: list[DedupeGroup], *, apply_medium: bool
) -> list[DedupeGroup]:
    """Groups whose trash list may be applied. high_doi before medium."""
    order = {"high_doi": 0, "medium_title_year": 1}
    chosen: list[DedupeGroup] = []
    for group in sorted(groups, key=lambda g: order.get(g.phase, 9)):
        if group.held or not group.trash or not group.keep:
            continue
        if group.phase == "medium_title_year" and not apply_medium:
            continue
        if group.phase not in ("high_doi", "medium_title_year"):
            continue
        chosen.append(group)
    return chosen


def apply_trash(
    backend: Any,
    groups: list[DedupeGroup],
    *,
    apply_medium: bool,
    audit_path: Path,
    scope: str,
    pack: Path,
) -> tuple[int, list[str]]:
    """Trash extras. Returns (trashed count, per-item errors). Appends the audit jsonl."""
    from .library import LibraryError

    trashed = 0
    errors: list[str] = []
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).isoformat()
    for group in actionable_groups(groups, apply_medium=apply_medium):
        for key in group.trash:
            try:
                backend.trash_item(key)
            except LibraryError:
                raise
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                continue
            trashed += 1
            lines.append(
                json.dumps(
                    {
                        "ts": now,
                        "scope": scope,
                        "phase": group.phase,
                        "keep": group.keep,
                        "trash": key,
                        "reason": group.reason,
                        "pack": str(pack),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    if lines:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.writelines(lines)
    return trashed, errors


def _high_doi(items: list[Item]) -> list[DedupeGroup]:
    buckets: dict[str, list[Item]] = {}
    for item in items:
        doi = normalize_doi(item.doi) if item.doi else None
        if not doi:
            continue
        buckets.setdefault(doi, []).append(item)
    groups: list[DedupeGroup] = []
    for doi, members in sorted(buckets.items()):
        if len(members) < 2:
            continue
        groups.append(_make_group(members, phase="high_doi", doi=doi))
    return groups


def _medium_title_year(items: list[Item]) -> list[DedupeGroup]:
    buckets: dict[tuple[str, int], list[Item]] = {}
    for item in items:
        if item.year is None or not _has_title(item):
            continue
        title = normalize_dedupe_title(item.title)
        if not title:
            continue
        buckets.setdefault((title, item.year), []).append(item)
    groups: list[DedupeGroup] = []
    for (title, year), members in sorted(buckets.items()):
        if len(members) < 2:
            continue
        groups.append(
            _make_group(members, phase="medium_title_year", title_key=title, year=year)
        )
    return groups


def _make_group(
    members: list[Item],
    *,
    phase: str,
    doi: str | None = None,
    title_key: str | None = None,
    year: int | None = None,
) -> DedupeGroup:
    scored = [_member(item) for item in members]
    held = phase == "high_doi" and _titles_diverge(members)
    if held:
        return DedupeGroup(
            phase=phase,
            reason="held_divergent_title",
            keep=None,
            trash=[],
            held=True,
            needs_review=True,
            doi=doi,
            title_key=title_key,
            year=year,
            members=scored,
        )
    keeper = choose_keep(members)
    return DedupeGroup(
        phase=phase,
        reason="doi" if phase == "high_doi" else "title_year",
        keep=keeper.key,
        trash=[item.key for item in members if item.key != keeper.key],
        held=False,
        needs_review=phase == "medium_title_year",
        doi=doi,
        title_key=title_key,
        year=year,
        members=scored,
    )


def choose_keep(items: list[Item]) -> Item:
    """Prefer stored PDF, then linked URL, then richer metadata, then older dateAdded."""
    return sorted(items, key=_keep_sort)[0]


def _keep_sort(item: Item) -> tuple:
    titled = 1 if _has_title(item) else 0
    dated = 1 if (item.date or item.year) else 0
    added = item.date_added or "\uffff"
    return (
        -_attachment_rank(item),
        -titled,
        -dated,
        -item.creator_count,
        added,
        item.key,
    )


def _attachment_rank(item: Item) -> int:
    if item.has_pdf:
        return 2
    if item.has_linked_url:
        return 1
    return 0


def _has_title(item: Item) -> bool:
    title = (item.title or "").strip()
    return bool(title) and title != "(untitled)"


def _titles_diverge(items: list[Item]) -> bool:
    titles = [item.title for item in items]
    for i, left in enumerate(titles):
        for right in titles[i + 1 :]:
            left_plain = html.unescape(left or "")
            right_plain = html.unescape(right or "")
            if title_similarity(left_plain, right_plain) < TITLE_DIVERGE_BELOW:
                return True
    return False


def _member(item: Item) -> dict[str, Any]:
    return {
        "key": item.key,
        "title": item.title,
        "doi": item.doi,
        "year": item.year,
        "has_pdf": item.has_pdf,
        "has_linked_url": item.has_linked_url,
        "date_added": item.date_added,
        "creator_count": item.creator_count,
        "attachment_rank": _attachment_rank(item),
        "has_title": _has_title(item),
        "has_date": bool(item.date or item.year),
    }


def _markdown(
    scope: str, phase: str, counts: dict[str, int], groups: list[DedupeGroup]
) -> str:
    lines = [
        "# Dedupe pack",
        "",
        f"- Scope: {scope}",
        f"- Phase: {phase}",
        f"- Items: {counts['items']}",
        f"- Groups: {counts['groups']}",
        f"- Held: {counts['held']}",
        f"- Trash candidates: {counts['trash_candidates']}",
        "",
        "Nothing is trashed until `paperful dedupe --apply`. "
        "Title+year groups need `--apply-medium`.",
        "",
    ]
    held = [g for g in groups if g.held]
    if held:
        lines.append("## Held")
        lines.append("")
        for group in held:
            keys = ", ".join(m["key"] for m in group.members)
            label = group.doi or group.title_key or "?"
            lines.append(f"- `{label}` — {group.reason} ({keys})")
        lines.append("")
    for phase_name, heading in (
        ("high_doi", "high_doi"),
        ("medium_title_year", "medium_title_year"),
    ):
        subset = [g for g in groups if g.phase == phase_name and not g.held]
        if not subset:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for group in subset:
            review = " (needs review)" if group.needs_review else ""
            trash = ", ".join(f"`{key}`" for key in group.trash) or "none"
            lines.append(f"- Keep `{group.keep}` — trash {trash}{review}")
            for member in group.members:
                flags = []
                if member["has_pdf"]:
                    flags.append("stored PDF")
                elif member["has_linked_url"]:
                    flags.append("linked URL")
                if member["date_added"]:
                    flags.append(member["date_added"])
                extra = f" ({', '.join(flags)})" if flags else ""
                lines.append(f"  - `{member['key']}` {member['title']}{extra}")
        lines.append("")
    if not groups:
        lines.append("No duplicate groups.")
        lines.append("")
    return "\n".join(lines)
