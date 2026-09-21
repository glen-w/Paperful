"""Rebuild missing Zotero items from ``out/`` restore folders.

Match an on-disk record to a live item by key, then DOI, then title+year.
Existing items are left alone: no field overwrites, no trash. A local PDF is
attached only when the match has no imported PDF. Notes are created only when
that tag or key is not already a child.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import is_item_dirname, load_json
from .zot import Item, normalize_doi


@dataclass
class RestoreAction:
    kind: str  # create_item | attach_pdf | create_note | exists
    item_key: str
    title: str
    detail: str
    record_dir: Path
    pdf: Path | None = None
    note_html: str | None = None
    note_tag: str | None = None
    payload: dict[str, Any] | None = None


@dataclass
class RestorePlan:
    actions: list[RestoreAction] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for action in self.actions:
            out[action.kind] = out.get(action.kind, 0) + 1
        return out


def iter_records(out_dir: Path, collection_prefixes: list[str] | None) -> list[Path]:
    """Item dirs under ``out_dir``, optionally limited to collection path prefixes."""
    if not out_dir.is_dir():
        return []
    found: list[Path] = []
    prefixes = [p.strip("/") for p in (collection_prefixes or []) if p.strip("/")]
    for rec in out_dir.rglob("record.json"):
        if not is_item_dirname(rec.parent.name):
            continue
        if prefixes:
            try:
                rel = rec.parent.relative_to(out_dir).as_posix()
            except ValueError:
                continue
            if not any(rel == pre or rel.startswith(pre + "/") for pre in prefixes):
                continue
        found.append(rec)
    return sorted(found)


def match_item(record: dict[str, Any], items: list[Item]) -> Item | None:
    """DOI, then item key, then title+year. First hit wins."""
    want = normalize_doi(record.get("doi") or record.get("library_doi"))
    if want:
        for it in items:
            if it.doi and normalize_doi(it.doi) == want:
                return it
    key = str(record.get("item_key") or "")
    for it in items:
        if key and it.key == key:
            return it
    title = (record.get("title") or "").strip().lower()
    year = record.get("year")
    if title and isinstance(year, int):
        for it in items:
            if (it.title or "").strip().lower() == title and it.year == year:
                return it
    return None


def record_in_scope(
    record: dict[str, Any],
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | set[str] | None = None,
) -> bool:
    """Same year and type rules as library item filters. Undated rows drop when a year is set."""
    if item_types and record.get("item_type") not in item_types:
        return False
    if year_from is None and year_to is None:
        return True
    year = record.get("year")
    if not isinstance(year, int):
        return False
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


def parent_payload(record: dict[str, Any], collection_keys: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "itemType": record.get("item_type") or "document",
        "title": record.get("title") or "",
        "creators": record.get("creators") or [],
        "abstractNote": record.get("abstract") or "",
        "date": record.get("date") or "",
        "DOI": record.get("doi") or "",
        "url": record.get("url") or "",
        "extra": record.get("extra") or "",
        "publicationTitle": record.get("publication_title") or "",
        "tags": list(record.get("tags") or []),
        "collections": collection_keys,
        "relations": record.get("relations") or {},
    }
    fields = record.get("fields")
    if isinstance(fields, dict):
        for key, value in fields.items():
            if key not in data:
                data[key] = value
    return data


def _local_pdf(item_dir: Path, record: dict[str, Any]) -> Path | None:
    fetch = record.get("fetch") if isinstance(record.get("fetch"), dict) else {}
    named = fetch.get("pdf") if isinstance(fetch, dict) else None
    if named:
        candidate = item_dir / str(named)
        if candidate.is_file():
            return candidate
    pdfs = sorted(p for p in item_dir.glob("*.pdf") if p.is_file())
    return pdfs[0] if pdfs else None


def plan_restore(
    records: list[tuple[Path, dict[str, Any]]],
    library: list[Item],
    *,
    note_tags_for: dict[str, set[str]] | None = None,
) -> RestorePlan:
    """Decide creates and attaches. ``note_tags_for`` maps live item key → tags present."""
    plan = RestorePlan()
    tags_for = note_tags_for or {}
    for path, record in records:
        item_dir = path.parent
        key = str(record.get("item_key") or "")
        title = str(record.get("title") or "")
        match = match_item(record, library)
        if match is None:
            plan.actions.append(
                RestoreAction(
                    kind="create_item",
                    item_key=key,
                    title=title,
                    detail="no live match",
                    record_dir=item_dir,
                    payload=parent_payload(record, []),
                )
            )
            live_key = ""
            has_pdf = False
            present_tags: set[str] = set()
        else:
            plan.actions.append(
                RestoreAction(
                    kind="exists",
                    item_key=match.key,
                    title=title,
                    detail="matched; fields left unchanged",
                    record_dir=item_dir,
                )
            )
            live_key = match.key
            has_pdf = bool(match.has_pdf)
            present_tags = tags_for.get(match.key, set())
        pdf = _local_pdf(item_dir, record)
        if pdf is not None and not has_pdf:
            plan.actions.append(
                RestoreAction(
                    kind="attach_pdf",
                    item_key=live_key or key,
                    title=title,
                    detail=pdf.name,
                    record_dir=item_dir,
                    pdf=pdf,
                )
            )
        for note in record.get("notes") or []:
            if not isinstance(note, dict):
                continue
            fname = str(note.get("file") or "")
            if not fname:
                continue
            tag = note.get("tag")
            if not tag:
                tags = note.get("tags") or []
                tag = tags[0] if tags else None
            if tag and str(tag).lower() in {t.lower() for t in present_tags}:
                continue
            html_path = item_dir / "notes" / fname
            if not html_path.is_file():
                continue
            plan.actions.append(
                RestoreAction(
                    kind="create_note",
                    item_key=live_key or key,
                    title=title,
                    detail=fname,
                    record_dir=item_dir,
                    note_html=html_path.read_text(encoding="utf-8"),
                    note_tag=str(tag) if tag else "paperful-restored",
                )
            )
    return plan


def apply_restore(plan: RestorePlan, backend: Any, attacher: Any) -> dict[str, int]:
    """Create missing items, attach local PDFs, and add missing notes.

    Fields on an item that already exists are not written.
    """
    done = {"create_item": 0, "attach_pdf": 0, "create_note": 0}
    created: dict[Path, str] = {}
    for action in plan.actions:
        if action.kind == "exists":
            continue
        if action.kind == "create_item":
            record = load_json(action.record_dir / "record.json") or {}
            paths = [
                p
                for p in (record.get("collection_paths") or [])
                if isinstance(p, str) and p and p != "_uncollected"
            ]
            keys = [backend.ensure_collection_path(p) for p in paths]
            payload = dict(action.payload or parent_payload(record, []))
            payload["collections"] = keys
            new_key = backend.create_parent(payload)
            created[action.record_dir] = new_key
            done["create_item"] += 1
            continue
        key = created.get(action.record_dir) or action.item_key
        if action.kind == "attach_pdf" and action.pdf is not None:
            attacher.attach(key, action.pdf, action.title)
            done["attach_pdf"] += 1
        elif action.kind == "create_note" and action.note_html is not None:
            backend.create_or_update_note(
                key, action.note_html, action.note_tag or "paperful-restored"
            )
            done["create_note"] += 1
    return done
