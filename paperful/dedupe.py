"""Collection-scoped duplicate packs. Classify on disk; merge only with --apply.

Keep rule (high_doi and proposed medium keeps), highest first:

1. stored/imported PDF (`has_pdf`)
2. linked PDF URL only (`has_linked_url`)
3. richer metadata: non-placeholder title, then a date/year, then more creators
4. older `dateAdded` (missing sorts last), then item key

`--apply` copies the extra parent's PDF, notes, and better fields onto the
keeper, then trashes the emptied parent. Same normalised DOI with titles
below `TITLE_DIVERGE_BELOW` is held (`held_divergent_title`) and never
merged. Title+year groups are `needs_review` and are skipped on `--apply`
unless the caller passes `apply_medium`.
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
from .zot import Item, is_linked_url_pdf, is_pdf_attachment

TITLE_DIVERGE_BELOW = 0.60
PHASES = ("high_doi", "medium_title_year", "all")
SCHEMA = "paperful.dedupe_pack.v1"
_SCOPE_UNSAFE = re.compile(r"[^A-Za-z0-9]+")
_FILENAME_TITLE = re.compile(r"\.pdf$", re.IGNORECASE)
# Zotero stores the abstract as abstractNote.
_LONGER_WINS = ("abstractNote", "extra")
_FILL_BLANK = (
    "date",
    "publicationTitle",
    "url",
    "pages",
    "volume",
    "issue",
    "publisher",
    "ISBN",
    "ISSN",
    "language",
    "accessDate",
    "shortTitle",
    "archive",
    "archiveLocation",
    "libraryCatalog",
    "callNumber",
    "rights",
    "series",
    "seriesTitle",
)


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
    merge_preview: list[dict[str, Any]] = field(default_factory=list)


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


def apply_merge(
    backend: Any,
    groups: list[DedupeGroup],
    *,
    apply_medium: bool,
    audit_path: Path,
    scope: str,
    pack: Path,
) -> tuple[int, list[str]]:
    """Merge extras onto the keeper, then trash them.

    Returns (merged count, per-item errors). A failed child move does not
    trash that donor. Appends the audit jsonl.
    """
    from .library import LibraryError

    merged = 0
    errors: list[str] = []
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).isoformat()
    for group in actionable_groups(groups, apply_medium=apply_medium):
        for key in group.trash:
            try:
                result = backend.merge_into(group.keep, key)
            except LibraryError:
                raise
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                continue
            if not isinstance(result, dict):
                result = {}
            merged += 1
            lines.append(
                json.dumps(
                    {
                        "ts": now,
                        "scope": scope,
                        "phase": group.phase,
                        "keep": group.keep,
                        "drop": key,
                        "moved": list(result.get("moved") or []),
                        "trashed_children": list(result.get("trashed_children") or []),
                        "fields": list(result.get("fields") or []),
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
    return merged, errors


def attach_merge_previews(backend: Any, groups: list[DedupeGroup]) -> None:
    """Fill ``merge_preview`` on non-held groups. Missing items stay empty."""
    preview = getattr(backend, "preview_merge", None)
    if not callable(preview):
        return
    for group in groups:
        if group.held or not group.keep or not group.trash:
            continue
        rows: list[dict[str, Any]] = []
        for key in group.trash:
            try:
                row = preview(group.keep, key)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        group.merge_preview = rows


def merge_parent_patch(keep: dict[str, Any], drop: dict[str, Any]) -> dict[str, Any]:
    """Fields, collections, tags, and relations to write onto the keeper.

    The keeper wins a real conflict. A donor value replaces it only when the
    donor value is clearly better (blank fill, longer abstract/extra, a
    filename title, or a creator list that contains the keeper's surnames).
    """
    fields: dict[str, Any] = {}
    title = _better_title(keep.get("title"), drop.get("title"))
    if title is not None:
        fields["title"] = title
    doi = _better_doi(keep.get("DOI"), drop.get("DOI"))
    if doi is not None:
        fields["DOI"] = doi
    creators = _better_creators(keep.get("creators"), drop.get("creators"))
    if creators is not None:
        fields["creators"] = creators
    for name in _LONGER_WINS:
        chosen = _longer_text(keep.get(name), drop.get(name))
        if chosen is not None:
            fields[name] = chosen
    for name in _FILL_BLANK:
        if _is_blank(keep.get(name)) and not _is_blank(drop.get(name)):
            fields[name] = drop.get(name)
    collections = _union_list(keep.get("collections"), drop.get("collections"))
    tags = _merge_tags(keep.get("tags"), drop.get("tags"))
    relations = _merge_relations(keep.get("relations"), drop.get("relations"))
    date_added = _earlier_date(keep.get("dateAdded"), drop.get("dateAdded"))
    return {
        "fields": fields,
        "collections": collections,
        "tags": tags,
        "relations": relations,
        "date_added": date_added,
    }


def plan_child_moves(
    keep_children: list[dict[str, Any]],
    drop_children: list[dict[str, Any]],
    annotation_counts: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    """How to combine children. ``reparent`` moves onto the keeper; ``trash`` drops a duplicate file."""
    counts = annotation_counts or {}
    moves: list[dict[str, str]] = []
    live_pdfs: dict[str, str] = {}
    for child in keep_children:
        data = child.get("data") or {}
        key = _child_key(child)
        digest = _imported_md5(data)
        if key and digest:
            live_pdfs.setdefault(digest, key)
    keep_urls = {
        (child.get("data") or {}).get("url", "").strip()
        for child in keep_children
        if is_linked_url_pdf(child.get("data") or {})
        and (child.get("data") or {}).get("url", "").strip()
    }
    for child in drop_children:
        data = child.get("data") or {}
        key = _child_key(child)
        if not key:
            continue
        if data.get("itemType") == "note":
            moves.append({"key": key, "action": "reparent", "kind": "note"})
            continue
        if is_linked_url_pdf(data):
            url = (data.get("url") or "").strip()
            if url and url in keep_urls:
                moves.append({"key": key, "action": "trash", "kind": "linked_url"})
            else:
                if url:
                    keep_urls.add(url)
                moves.append({"key": key, "action": "reparent", "kind": "linked_url"})
            continue
        digest = _imported_md5(data)
        if digest and digest in live_pdfs:
            survivor = live_pdfs[digest]
            drop_notes = counts.get(key, 0)
            keep_notes = counts.get(survivor, 0)
            if drop_notes > 0 and keep_notes > 0:
                moves.append({"key": key, "action": "reparent", "kind": "pdf"})
            elif drop_notes > 0 and keep_notes == 0:
                moves.append({"key": survivor, "action": "trash", "kind": "pdf"})
                moves.append({"key": key, "action": "reparent", "kind": "pdf"})
                live_pdfs[digest] = key
            else:
                moves.append({"key": key, "action": "trash", "kind": "pdf"})
            continue
        if digest:
            live_pdfs[digest] = key
        kind = "pdf" if is_pdf_attachment(data) else "attachment"
        moves.append({"key": key, "action": "reparent", "kind": kind})
    return moves


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        return not text or text == "(untitled)"
    if isinstance(value, list):
        return len(value) == 0
    return False


def _better_title(keep: Any, drop: Any) -> str | None:
    if _is_blank(keep) and isinstance(drop, str) and not _is_blank(drop):
        return drop
    if isinstance(keep, str) and _FILENAME_TITLE.search(keep.strip()):
        if isinstance(drop, str) and not _is_blank(drop) and not _FILENAME_TITLE.search(drop.strip()):
            return drop
    return None


def _better_doi(keep: Any, drop: Any) -> str | None:
    """Copy a DOI only into a blank. Differing DOIs stay on the keeper."""
    if _is_blank(drop) or not isinstance(drop, str):
        return None
    if _is_blank(keep):
        return drop
    return None


def _better_creators(keep: Any, drop: Any) -> list[Any] | None:
    keep_list = keep if isinstance(keep, list) else []
    drop_list = drop if isinstance(drop, list) else []
    if not drop_list:
        return None
    if not keep_list:
        return drop_list
    if len(drop_list) <= len(keep_list):
        return None
    keep_names = {_surname(c) for c in keep_list if isinstance(c, dict)}
    keep_names.discard("")
    drop_names = {_surname(c) for c in drop_list if isinstance(c, dict)}
    if keep_names and keep_names <= drop_names:
        return drop_list
    return None


def _surname(creator: dict[str, Any]) -> str:
    return str(creator.get("lastName") or creator.get("name") or "").strip().casefold()


def _longer_text(keep: Any, drop: Any) -> str | None:
    if not isinstance(drop, str) or _is_blank(drop):
        return None
    if _is_blank(keep):
        return drop
    if isinstance(keep, str) and len(drop.strip()) > len(keep.strip()):
        return drop
    return None


def _union_list(keep: Any, drop: Any) -> list[Any] | None:
    keep_list = [x for x in keep if x] if isinstance(keep, list) else []
    drop_list = [x for x in drop if x] if isinstance(drop, list) else []
    extra = [x for x in drop_list if x not in keep_list]
    if not extra:
        return None
    return keep_list + extra


def _merge_tags(keep: Any, drop: Any) -> list[dict[str, Any]] | None:
    """Union tags. A manual tag (type 0) wins over an automatic one."""
    keep_list = [t for t in keep if isinstance(t, dict)] if isinstance(keep, list) else []
    drop_list = [t for t in drop if isinstance(t, dict)] if isinstance(drop, list) else []
    by: dict[str, int] = {}
    order: list[str] = []
    for tag in keep_list + drop_list:
        name = str(tag.get("tag") or "").strip()
        if not name:
            continue
        typ = _tag_type(tag)
        if name not in by:
            by[name] = typ
            order.append(name)
        elif by[name] != 0 and typ == 0:
            by[name] = 0
    merged = [{"tag": name, "type": by[name]} for name in order]
    keep_norm = [{"tag": str(t.get("tag") or "").strip(), "type": _tag_type(t)} for t in keep_list if str(t.get("tag") or "").strip()]
    if merged == keep_norm:
        return None
    return merged


def _tag_type(tag: dict[str, Any]) -> int:
    if tag.get("type") == 1:
        return 1
    return 0


def _merge_relations(keep: Any, drop: Any) -> dict[str, list[str]] | None:
    keep_rel = keep if isinstance(keep, dict) else {}
    drop_rel = drop if isinstance(drop, dict) else {}
    if not drop_rel:
        return None
    merged: dict[str, list[str]] = {}
    for pred, val in list(keep_rel.items()) + list(drop_rel.items()):
        bucket = merged.setdefault(str(pred), [])
        for item in _relation_values(val):
            if item not in bucket:
                bucket.append(item)
    if merged == {str(k): _relation_values(v) for k, v in keep_rel.items()}:
        return None
    return merged


def _relation_values(val: Any) -> list[str]:
    if isinstance(val, str) and val:
        return [val]
    if isinstance(val, list):
        return [str(item) for item in val if item]
    return []


def _earlier_date(keep: Any, drop: Any) -> str | None:
    if not isinstance(drop, str) or not drop.strip():
        return None
    if not isinstance(keep, str) or not keep.strip():
        return drop
    if drop < keep:
        return drop
    return None


def _child_key(child: dict[str, Any]) -> str:
    return str(child.get("key") or (child.get("data") or {}).get("key") or "")


def _imported_md5(data: dict[str, Any]) -> str | None:
    if data.get("linkMode") not in {"imported_file", "imported_url"}:
        return None
    if not is_pdf_attachment(data):
        return None
    digest = str(data.get("md5") or "").strip().lower()
    return digest or None


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
        "Nothing is merged until `paperful dedupe --apply`. "
        "`--apply` copies the extra parent's PDF, notes, and better fields "
        "onto the keeper, then trashes the emptied parent. "
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
            donors = ", ".join(f"`{key}`" for key in group.trash) or "none"
            lines.append(f"- Keep `{group.keep}` — merge into keeper from {donors}{review}")
            for preview in group.merge_preview:
                fields = ", ".join(preview.get("fields") or []) or "none"
                moves = preview.get("move") or []
                bits = [
                    f"{row['kind']} `{row['key']}` ({row['action']})"
                    for row in moves
                    if row.get("key")
                ]
                moved = ", ".join(bits) or "no children"
                lines.append(
                    f"  - From `{preview.get('drop')}`: fields {fields}; {moved}"
                )
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
