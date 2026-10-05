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

from .progress import Track
from .config import Config
from .library import LibraryError, LibraryReadError
from .mirror import place_item_dirs
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
    unread: int = 0  # the manager could not be read; the record on disk was left alone
    index: list[dict[str, Any]] = field(default_factory=list)
    pdf_keys: list[str] = field(default_factory=list)  # items whose PDF was exported


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
    """Child rows. A backend that cannot list children has none; a failed read raises."""
    fn = getattr(backend, "children", None)
    if fn is None:
        return []
    return [ch for ch in (fn(key) or []) if isinstance(ch, dict)]


def _raw_item(backend: Any, key: str) -> dict[str, Any] | None:
    """The manager's own payload. ``None`` only when the backend has no such call."""
    fn = getattr(backend, "raw_item", None)
    if fn is None:
        return None
    raw = fn(key)
    if not isinstance(raw, dict):
        raise LibraryReadError(f"item {key} could not be read")
    return raw


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def attachment_rows(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ch in children:
        data = ch.get("data") or {}
        if data.get("itemType") != "attachment":
            continue
        row = {
            "key": ch.get("key"),
            "filename": data.get("filename") or data.get("title"),
            "linkMode": data.get("linkMode"),
            "contentType": data.get("contentType"),
            "md5": data.get("md5") or None,
        }
        for name in ("title", "url", "path"):
            if data.get(name):
                row[name] = data[name]
        rows.append(row)
    # PDFs first: the first row is the one a reader means by "the file".
    rows.sort(key=lambda r: r.get("contentType") != "application/pdf")
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
        tags = [
            str(t.get("tag"))
            for t in (data.get("tags") or [])
            if isinstance(t, dict) and t.get("tag")
        ]
        if fname in seen:
            # The file is already there (the disk summary). Record whose note it is.
            for row in meta:
                if row["file"] == fname and key and "key" not in row:
                    row["key"] = key
                    if tags:
                        row["tags"] = tags
            continue
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


def maybe_export_attachments(
    primary: Path,
    extras: list[Path],
    backend: Any,
    children: list[dict[str, Any]],
    pdfs: str,
    *,
    dry_run: bool,
) -> int:
    """Copy stored non-PDF attachments into the item folder when ``pdfs=all``."""
    if pdfs != "all" or dry_run:
        return 0
    export_fn = getattr(backend, "export_attachment", None)
    if not callable(export_fn):
        return 0
    n = 0
    for ch in children:
        data = ch.get("data") or {}
        if data.get("itemType") != "attachment":
            continue
        if data.get("linkMode") == "linked_url":
            continue
        if is_pdf_attachment(data):
            continue
        key = ch.get("key")
        if not key:
            continue
        name = data.get("filename") or data.get("title") or f"{key}.bin"
        safe = Path(str(name)).name or f"{key}.bin"
        dest = primary / safe
        if dest.is_file():
            continue
        got = export_fn(str(key), dest)
        if got is None or not Path(got).is_file():
            continue
        n += 1
        for extra in extras:
            extra.mkdir(parents=True, exist_ok=True)
            target = extra / Path(got).name
            if target.exists():
                continue
            try:
                target.hardlink_to(got)
            except OSError:
                shutil.copyfile(got, target)
    return n


def _preserve_fetch(rec: dict[str, Any], item_dir: Path) -> None:
    existing = load_json(record_path(item_dir))
    if not existing:
        return
    if existing.get("fetch") and not rec.get("fetch"):
        rec["fetch"] = existing["fetch"]
        rec["pdf_doi"] = existing.get("pdf_doi")
    if existing.get("notes") and not rec.get("notes"):
        rec["notes"] = existing["notes"]


def _link_pdfs(dirs: list[Path]) -> None:
    """Each collection folder holds the PDF. Hardlinks, so no second copy of the bytes."""
    pdfs: list[Path] = []
    for d in dirs:
        pdfs = [p for p in d.glob("*.pdf") if p.is_file()]
        if pdfs:
            break
    for d in dirs:
        if any(d.glob("*.pdf")):
            continue
        for pdf in pdfs:
            target = d / pdf.name
            try:
                target.hardlink_to(pdf)
            except OSError:
                shutil.copyfile(pdf, target)


ANNOTATIONS_SCHEMA = "paperful.annotations.v1"


def _write_annotations(item_dir: Path, annotations: list[dict[str, Any]]) -> None:
    """The reader's highlights and notes, as the manager holds them."""
    path = item_dir / "annotations.json"
    if not annotations:
        path.unlink(missing_ok=True)
        return
    rows = []
    for row in annotations:
        data = dict(row.get("data") or {})
        data.setdefault("key", row.get("key"))
        rows.append(data)
    write_json(path, {"schema": ANNOTATIONS_SCHEMA, "annotations": rows})


def write_item(
    out_dir: Path,
    item: Item,
    raw: dict[str, Any] | None,
    children: list[dict[str, Any]],
    cols: dict[str, Collection],
    summaries_dir: Path,
    pdfs: str,
    *,
    backend: Any = None,
    dry_run: bool = False,
    exact: bool = False,
    annotations: list[dict[str, Any]] | None = None,
) -> tuple[int, int, int, dict[str, Any]]:
    """Write one item's folders from data already read. Asks the manager only for PDF bytes.

    ``exact`` is passed to :func:`place_item_dirs`. ``annotations`` is the
    item's whole set when known; ``None`` leaves ``annotations.json`` alone.
    """
    children = [ch for ch in children if not (ch.get("data") or {}).get("deleted")]
    dirs = place_item_dirs(out_dir, item, dry_run=dry_run, exact=exact)
    primary, extras = dirs[0], dirs[1:]
    rec = record_from_raw(raw, item, cols)
    rec["schema"] = ITEM_SCHEMA
    if ((raw or {}).get("data") or {}).get("deleted"):
        rec["library"] = {"state": "trashed"}
    attachments = attachment_rows(children)
    exported = backend is not None and maybe_export_pdf(
        item, primary, extras, backend, attachments, pdfs, dry_run=dry_run
    )
    if backend is not None:
        maybe_export_attachments(
            primary, extras, backend, children, pdfs, dry_run=dry_run
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
    # A scoped fetch may have landed in any one of the folders.
    for d in dirs:
        _preserve_fetch(rec, d)
    if not dry_run:
        _link_pdfs(dirs)
        for d in dirs:
            write_json(record_path(d), rec)
            if annotations is not None:
                _write_annotations(d, annotations)
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
        # Child keys, so a refresh can tell when one was removed in the manager.
        "children": sorted(str(ch.get("key")) for ch in children if ch.get("key")),
    }
    if annotations is not None:
        row["annotations"] = sorted(
            str(a.get("key")) for a in annotations if a.get("key")
        )
    return 1, int(exported), n_notes, row


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
    """Read one item from the manager and write its folders. A failed read raises."""
    raw = _raw_item(backend, item.key)
    children = _children(backend, item.key)
    return write_item(
        out_dir,
        item,
        raw,
        children,
        cols,
        summaries_dir,
        pdfs,
        backend=backend,
        dry_run=dry_run,
    )


def _index_put(by_key: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    """Later row wins. Annotation keys carry over when the later row did not read them."""
    old = by_key.get(str(row["item_key"]))
    if old and "annotations" in old and "annotations" not in row:
        row = {**row, "annotations": old["annotations"]}
    by_key[str(row["item_key"])] = row


def read_index(out_dir: Path) -> dict[str, dict[str, Any]]:
    """``_index.jsonl`` by item key. Lines appended after the last rewrite count."""
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
                _index_put(by_key, row)
    return by_key


def append_index(out_dir: Path, row: dict[str, Any]) -> None:
    """Add one row without rewriting the file. The next ``merge_index`` compacts it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "_index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def merge_index(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    path = out_dir / "_index.jsonl"
    by_key = read_index(out_dir)
    for row in rows:
        _index_put(by_key, row)
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
    track: Track | None = None,
) -> SnapshotStats:
    stats = SnapshotStats()
    cols: dict[str, Collection] = {}
    fn = getattr(backend, "collections", None)
    if fn is not None:
        try:
            cols = fn() or {}
        except Exception:
            cols = {}
    for item in track(items) if track else items:
        try:
            n_rec, n_pdf, n_notes, row = snapshot_item(
                cfg.out_dir,
                item,
                backend,
                cols,
                cfg.summaries_dir,
                pdfs,
                dry_run=dry_run,
            )
        except LibraryError:
            # Could not read is not the same as nothing there. Keep what is on disk.
            stats.unread += 1
            continue
        stats.records += n_rec
        stats.pdf_exports += n_pdf
        if n_pdf:
            stats.pdf_keys.append(item.key)
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
            "unread": stats.unread,
        },
    }


def count_item_dirs(out_dir: Path) -> int:
    """Count item directories in the mirror."""
    if not out_dir.is_dir():
        return 0
    seen: set[Path] = set()
    for pdf in out_dir.rglob("*.pdf"):
        if is_item_dirname(pdf.parent.name):
            seen.add(pdf.parent)
    for rec in out_dir.rglob("record.json"):
        if is_item_dirname(rec.parent.name):
            seen.add(rec.parent)
    return len(seen)
