"""Thicken ``out/`` into per-item restore folders.

``paperful snapshot`` writes ``record.json`` for every scoped item, optional
PDF bytes (see ``[mirror].pdfs``), child notes, a collection tree, an index,
and a pointer file at the append-only ledgers. It does not copy sessions or
API keys.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .store import (
    COLLECTIONS_SCHEMA,
    HISTORY_SCHEMA,
    ITEM_SCHEMA,
    Manifest,
    empty_item_record,
    is_item_dirname,
    item_dirname,
    item_filename,
    load_json,
    migrate_flat_tree,
    record_path,
    write_json,
)
from .zot import Collection, Item, is_pdf_attachment

_PROMOTED = frozenset(
    {
        "itemType",
        "title",
        "creators",
        "abstractNote",
        "date",
        "DOI",
        "url",
        "extra",
        "publicationTitle",
        "tags",
        "relations",
        "collections",
        "dateAdded",
        "dateModified",
        "key",
        "version",
    }
)
_NOTE_NAME = re.compile(r"[^\w.-]+")


@dataclass
class SnapshotStats:
    records: int = 0
    pdf_exports: int = 0
    notes: int = 0
    migrations: int = 0
    index: list[dict[str, Any]] = field(default_factory=list)


def record_from_raw(
    raw: dict[str, Any] | None, item: Item, cols: dict[str, Collection]
) -> dict[str, Any]:
    """``paperful.item.v1`` from a Zotero item payload, falling back to ``Item``."""
    rec = empty_item_record(item)
    data = (raw or {}).get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return rec
    rec["version"] = raw.get("version") if isinstance(raw, dict) else None
    rec["date_added"] = (data.get("dateAdded") or "").strip() or item.date_added
    rec["date_modified"] = (data.get("dateModified") or "").strip() or None
    title = (data.get("title") or "").strip()
    if title:
        rec["title"] = title
    creators = data.get("creators")
    if isinstance(creators, list) and creators:
        rec["creators"] = creators
    abstract = (data.get("abstractNote") or "").strip()
    if abstract:
        rec["abstract"] = abstract
    if data.get("extra"):
        rec["extra"] = data.get("extra") or ""
    date = (data.get("date") or "").strip()
    if date:
        rec["date"] = date
    venue = (data.get("publicationTitle") or "").strip()
    if venue:
        rec["publication_title"] = venue
    url = (data.get("url") or "").strip()
    if url:
        rec["url"] = url
    tags: list[dict[str, Any]] = []
    for tag in data.get("tags") or []:
        if isinstance(tag, dict) and tag.get("tag"):
            row: dict[str, Any] = {"tag": tag["tag"]}
            if tag.get("type"):
                row["type"] = tag["type"]
            tags.append(row)
        elif isinstance(tag, str) and tag:
            tags.append({"tag": tag})
    rec["tags"] = tags
    relations = data.get("relations")
    rec["relations"] = relations if isinstance(relations, dict) else {}
    collections: list[dict[str, Any]] = []
    paths: list[str] = []
    for ck in data.get("collections") or []:
        col = cols.get(ck)
        path = col.path if col is not None else None
        collections.append({"key": ck, "path": path})
        if path:
            paths.append(path)
    if collections:
        rec["collections"] = collections
    if paths:
        rec["collection_paths"] = paths
    fields = {k: v for k, v in data.items() if k not in _PROMOTED}
    rec["fields"] = fields
    return rec


def item_dirs(out_dir: Path, item: Item) -> list[Path]:
    paths = item.collection_paths or ["_uncollected"]
    return [out_dir / p / item_dirname(item) for p in paths]


def _children(backend: Any, key: str) -> list[dict[str, Any]]:
    fn = getattr(backend, "children", None)
    if fn is None:
        return []
    try:
        kids = fn(key) or []
    except Exception:
        return []
    return [ch for ch in kids if isinstance(ch, dict)]


def _raw_item(backend: Any, key: str) -> dict[str, Any] | None:
    fn = getattr(backend, "raw_item", None)
    if fn is None:
        return None
    try:
        raw = fn(key)
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def attachment_rows(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ch in children:
        data = ch.get("data") or {}
        if data.get("itemType") != "attachment":
            continue
        if not is_pdf_attachment(data) and data.get("contentType") != "application/pdf":
            continue
        rows.append(
            {
                "key": ch.get("key"),
                "filename": data.get("filename") or data.get("title"),
                "linkMode": data.get("linkMode"),
                "contentType": data.get("contentType"),
                "md5": data.get("md5") or None,
            }
        )
    return rows


def _note_filename(data: dict[str, Any], key: str) -> str:
    tags = []
    for tag in data.get("tags") or []:
        if isinstance(tag, dict) and tag.get("tag"):
            tags.append(str(tag["tag"]))
    for tag in tags:
        if tag.startswith("paperful-"):
            safe = _NOTE_NAME.sub("-", tag).strip("-") or key
            return f"{safe}.html"
    return f"{key}.html"


def export_notes(
    item_dir: Path,
    item: Item,
    children: list[dict[str, Any]],
    summaries_dir: Path,
    *,
    dry_run: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Copy the on-disk summary and Zotero child notes into ``notes/``."""
    meta: list[dict[str, Any]] = []
    notes_dir = item_dir / "notes"
    summary = summaries_dir / f"{item.key}.html"
    if summary.is_file():
        meta.append({"file": "paperful-summary.html", "tag": "paperful-summary"})
        if not dry_run:
            notes_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(summary, notes_dir / "paperful-summary.html")
    seen = {row["file"] for row in meta}
    for ch in children:
        data = ch.get("data") or {}
        if data.get("itemType") != "note":
            continue
        key = str(ch.get("key") or "")
        fname = _note_filename(data, key or "note")
        if fname in seen:
            continue
        tags = [
            str(t.get("tag"))
            for t in (data.get("tags") or [])
            if isinstance(t, dict) and t.get("tag")
        ]
        row: dict[str, Any] = {"file": fname}
        if key:
            row["key"] = key
        if tags:
            row["tags"] = tags
        meta.append(row)
        seen.add(fname)
        if dry_run:
            continue
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / fname).write_text(str(data.get("note") or ""), encoding="utf-8")
    return len(meta), meta


def _folder_has_md5(item_dir: Path, md5: str | None) -> bool:
    if not item_dir.is_dir():
        return False
    pdfs = [p for p in item_dir.glob("*.pdf") if p.is_file()]
    if not pdfs:
        return False
    if not md5:
        return True
    for pdf in pdfs:
        try:
            if _file_md5(pdf) == md5:
                return True
        except OSError:
            continue
    return False


def maybe_export_pdf(
    item: Item,
    primary: Path,
    extras: list[Path],
    backend: Any,
    attachments: list[dict[str, Any]],
    pdfs: str,
    *,
    dry_run: bool,
) -> bool:
    """Copy an existing Zotero PDF into the item folder when ``pdfs=all``."""
    if pdfs != "all" or not item.has_pdf or item.has_linked_url:
        return False
    want = next((a.get("md5") for a in attachments if a.get("md5")), None)
    if _folder_has_md5(primary, want if isinstance(want, str) else None):
        return False
    if dry_run:
        return True
    dest = primary / item_filename(item)
    exported = backend.export_pdf(item, dest)
    if exported is None or not Path(exported).is_file():
        return False
    for extra in extras:
        extra.mkdir(parents=True, exist_ok=True)
        target = extra / Path(exported).name
        if target.exists():
            continue
        try:
            target.hardlink_to(exported)
        except OSError:
            shutil.copyfile(exported, target)
    return True


def _preserve_fetch(rec: dict[str, Any], item_dir: Path) -> None:
    existing = load_json(record_path(item_dir))
    if not existing:
        return
    if existing.get("fetch") and not rec.get("fetch"):
        rec["fetch"] = existing["fetch"]
        rec["pdf_doi"] = existing.get("pdf_doi")
    if existing.get("notes") and not rec.get("notes"):
        rec["notes"] = existing["notes"]


def snapshot_item(
    out_dir: Path,
    item: Item,
    backend: Any,
    cols: dict[str, Collection],
    summaries_dir: Path,
    pdfs: str,
    *,
    dry_run: bool,
) -> tuple[int, int, int, dict[str, Any]]:
    dirs = item_dirs(out_dir, item)
    primary, extras = dirs[0], dirs[1:]
    raw = _raw_item(backend, item.key)
    children = _children(backend, item.key)
    rec = record_from_raw(raw, item, cols)
    rec["schema"] = ITEM_SCHEMA
    attachments = attachment_rows(children)
    exported = maybe_export_pdf(
        item, primary, extras, backend, attachments, pdfs, dry_run=dry_run
    )
    if exported:
        for row in attachments:
            row.setdefault("origin", "zotero_export")
    rec["attachments"] = attachments
    n_notes, note_meta = export_notes(
        primary, item, children, summaries_dir, dry_run=dry_run
    )
    for extra in extras:
        if dry_run:
            break
        # Notes are small; duplicate so each collection folder stands alone.
        src = primary / "notes"
        if src.is_dir():
            dest = extra / "notes"
            dest.mkdir(parents=True, exist_ok=True)
            for note in src.glob("*.html"):
                target = dest / note.name
                if not target.exists():
                    shutil.copyfile(note, target)
    rec["notes"] = note_meta
    _preserve_fetch(rec, primary)
    if not dry_run:
        for d in dirs:
            _preserve_fetch(rec, d)
            write_json(record_path(d), rec)
    md5 = None
    fetch = rec.get("fetch") if isinstance(rec.get("fetch"), dict) else None
    if fetch and fetch.get("md5"):
        md5 = fetch["md5"]
    elif attachments and attachments[0].get("md5"):
        md5 = attachments[0]["md5"]
    has_pdf = (not dry_run and any(primary.glob("*.pdf"))) or bool(
        item.has_pdf and pdfs == "all" and not item.has_linked_url
    )
    if not dry_run:
        has_pdf = any(p.suffix == ".pdf" for p in primary.glob("*.pdf"))
    row = {
        "item_key": item.key,
        "dirs": [str(d.relative_to(out_dir)) for d in dirs],
        "has_pdf": has_pdf,
        "md5": md5,
    }
    return 1, int(exported), n_notes, row


def merge_index(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    path = out_dir / "_index.jsonl"
    by_key: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json_loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("item_key"):
                by_key[str(row["item_key"])] = row
    for row in rows:
        by_key[str(row["item_key"])] = row
    lines = [
        json.dumps(by_key[k], ensure_ascii=False) for k in sorted(by_key)
    ]
    path.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")


def json_loads(line: str) -> Any:
    return json.loads(line)


def write_collections(out_dir: Path, cols: dict[str, Collection]) -> None:
    rows = [
        {"key": c.key, "name": c.name, "parent": c.parent, "path": c.path}
        for c in cols.values()
    ]
    rows.sort(key=lambda r: (r["path"] or "").lower())
    write_json(
        out_dir / "_collections.json",
        {"schema": COLLECTIONS_SCHEMA, "collections": rows},
    )


def write_history(out_dir: Path, cfg: Config) -> None:
    """Point at ledgers. Never copy sessions, cookies, or the API key."""
    runs = cfg.state_dir / "runs"
    latest = None
    if runs.is_dir():
        files = sorted(p.name for p in runs.glob("*.json"))
        if files:
            latest = files[-1]
    payload = {
        "schema": HISTORY_SCHEMA,
        "ledgers": [
            {"name": "manifest", "path": str(cfg.manifest_path), "kind": "jsonl"},
            {
                "name": "metadata-patches",
                "path": str(cfg.patches_path),
                "kind": "jsonl",
            },
            {
                "name": "dedupe-applied",
                "path": str(cfg.dedupe_applied_path),
                "kind": "jsonl",
            },
            {"name": "runs", "path": str(runs), "kind": "dir"},
            {
                "name": "last-run",
                "path": str(cfg.state_dir / "last-run.json"),
                "kind": "json",
            },
        ],
        "latest_run": latest,
    }
    names = {row["name"] for row in payload["ledgers"]}
    banned = names & {"sessions", "cookies", "zotero-local-api-key"}
    if banned:
        raise RuntimeError(f"history witness must not list {sorted(banned)}")
    write_json(out_dir / "_history.json", payload)


def run_snapshot(
    cfg: Config,
    backend: Any,
    items: list[Item],
    *,
    pdfs: str,
    dry_run: bool,
    manifest: Manifest | None,
) -> SnapshotStats:
    stats = SnapshotStats()
    stats.migrations = migrate_flat_tree(cfg.out_dir, manifest, dry_run=dry_run)
    cols: dict[str, Collection] = {}
    fn = getattr(backend, "collections", None)
    if fn is not None:
        try:
            cols = fn() or {}
        except Exception:
            cols = {}
    for item in items:
        n_rec, n_pdf, n_notes, row = snapshot_item(
            cfg.out_dir,
            item,
            backend,
            cols,
            cfg.summaries_dir,
            pdfs,
            dry_run=dry_run,
        )
        stats.records += n_rec
        stats.pdf_exports += n_pdf
        stats.notes += n_notes
        stats.index.append(row)
    if not dry_run:
        cfg.out_dir.mkdir(parents=True, exist_ok=True)
        merge_index(cfg.out_dir, stats.index)
        write_collections(cfg.out_dir, cols)
        write_history(cfg.out_dir, cfg)
    return stats


def snapshot_report(
    cfg: Config, scope: str, pdfs: str, dry_run: bool, stats: SnapshotStats
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": "paperful.run_report.v1",
        "command": "snapshot",
        "started_at": now,
        "finished_at": now,
        "scope": scope,
        "flags": {"dry_run": dry_run, "pdfs": pdfs},
        "paths": {"out_dir": str(cfg.out_dir), "state_dir": str(cfg.state_dir)},
        "summary": {
            "records": stats.records,
            "pdf_exports": stats.pdf_exports,
            "notes": stats.notes,
            "migrations": stats.migrations,
        },
    }


def count_layout(out_dir: Path) -> tuple[int, int]:
    """(flat PDFs, item directories)."""
    flat = 0
    dirs = 0
    if not out_dir.is_dir():
        return 0, 0
    seen: set[Path] = set()
    for pdf in out_dir.rglob("*.pdf"):
        if is_item_dirname(pdf.parent.name):
            seen.add(pdf.parent)
        elif pdf.parent.name not in {"notes"}:
            flat += 1
    for rec in out_dir.rglob("record.json"):
        if is_item_dirname(rec.parent.name):
            seen.add(rec.parent)
    dirs = len(seen)
    return flat, dirs
