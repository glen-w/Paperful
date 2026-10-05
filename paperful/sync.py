"""Refresh the mirror from the manager: what changed, and nothing else.

The one place a whole-library read happens. A refresh asks the manager what
changed since the last library version, rewrites those items' folders, marks
items that left, and only then records the new version. A read that fails
stops the refresh before the version moves, so the next one covers the same
ground. See ``docs/architecture.md`` (Mirror first).
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .library import ChangeSet, LibraryError, LibraryReadError
from .mirror import (
    GONE_STATES,
    item_from_record,
    library_state,
    load_record,
    mirror_index,
    record_pdf,
    retire,
)
from .progress import Track
from .snapshot import (
    merge_index,
    read_index,
    write_collections,
    write_history,
    write_item,
)
from .store import item_filename, load_json, record_path, write_json
from .zot import SKIP_TYPES, Item, is_pdf_attachment, item_from_rows

SYNC_SCHEMA = "paperful.sync.v1"
_STATE_FILE = "_sync.json"
STANDALONE_SCHEMA = "paperful.standalone.v1"
NOTES_DIR = "_notes"
ATTACHMENTS_DIR = "_attachments"


@dataclass
class SyncStats:
    full: bool = False
    previous: int | None = None  # library version before
    version: int | None = None  # library version read
    written: int = 0  # items whose folders were rewritten
    gone: int = 0  # items marked as having left the library
    unread: int = 0  # items the manager could not give; version not advanced
    unwritten: list[str] = field(default_factory=list)  # the disk refused; version not advanced
    pdf_exports: int = 0
    pdf_keys: list[str] = field(default_factory=list)  # items whose PDF was copied in
    pdf_missing: int = 0  # the manager lists a PDF it could not hand over
    notes: int = 0
    index: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.written or self.gone or self.pdf_exports)


def sync_state(out_dir: Path) -> dict[str, Any] | None:
    """What the last refresh recorded, or ``None`` when there has not been one."""
    state = load_json(out_dir / _STATE_FILE)
    return state if state and state.get("schema") == SYNC_SCHEMA else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _Plan:
    """Items to rewrite: the parent payload, its children, and its annotations."""

    parents: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    children: dict[str, list[dict[str, Any]] | None] = field(default_factory=dict)
    annotations: dict[str, list[dict[str, Any]] | None] = field(default_factory=dict)


def _partition(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    """``(parents, children by parent, annotations by attachment)``."""
    parents: dict[str, dict[str, Any]] = {}
    kids: dict[str, list[dict[str, Any]]] = {}
    annos: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        data = row.get("data") or {}
        kind = data.get("itemType")
        parent = data.get("parentItem")
        if kind == "annotation":
            if parent:
                annos.setdefault(str(parent), []).append(row)
        elif parent:
            kids.setdefault(str(parent), []).append(row)
        elif kind not in SKIP_TYPES and row.get("key"):
            parents[str(row["key"])] = row
    return parents, kids, annos


def _plan_full(changes: ChangeSet) -> _Plan:
    parents, kids, annos = _partition(changes.rows)
    plan = _Plan()
    for key, raw in parents.items():
        children = kids.get(key, [])
        count = ((raw or {}).get("meta") or {}).get("numChildren")
        # Zotero listings carry ``numChildren``; when it matches, the rows are
        # complete. Mendeley/EndNote omit it and leave children out of ``rows``,
        # so ``None`` asks ``_write_planned`` to fetch via ``backend.children``.
        whole = isinstance(count, int) and count == len(children)
        plan.parents[key] = raw
        plan.children[key] = children if whole else None
        plan.annotations[key] = (
            [a for ch in children for a in annos.get(str(ch.get("key")), [])]
            if whole
            else None
        )
    return plan


def _plan_delta(
    changes: ChangeSet, index: dict[str, dict[str, Any]], backend: Any
) -> _Plan:
    """Parents touched by the delta. Payloads not in the delta are ``None``: read later."""
    parents, kids, annos = _partition(changes.rows)
    child_parent: dict[str, str] = {}
    anno_parent: dict[str, str] = {}
    for key, row in index.items():
        for child in row.get("children") or []:
            child_parent[str(child)] = key
        for anno in row.get("annotations") or []:
            anno_parent[str(anno)] = key
    for parent, rows in kids.items():
        for row in rows:
            child_parent[str(row.get("key"))] = parent

    affected: set[str] = set(parents) | set(kids)
    annotated: set[str] = set()
    for attachment in annos:
        parent = child_parent.get(attachment)
        if parent is None:
            raw = backend.raw_item(attachment)
            parent = str(((raw or {}).get("data") or {}).get("parentItem") or "")
        if parent:
            affected.add(parent)
            annotated.add(parent)
    # A child removed in the manager is not in any listing. Its key going missing is the signal.
    if changes.track_child_keys:
        for child, parent in child_parent.items():
            if child not in changes.all_keys:
                affected.add(parent)
        for anno, parent in anno_parent.items():
            if anno not in changes.all_keys:
                affected.add(parent)
                annotated.add(parent)

    plan = _Plan()
    for key in sorted(affected & changes.top_keys):
        raw = parents.get(key)
        listed = kids.get(key, [])
        count = ((raw or {}).get("meta") or {}).get("numChildren")
        # Every child is in the delta (a new item, usually): no second request.
        whole = isinstance(count, int) and count == len(listed)
        plan.parents[key] = raw
        plan.children[key] = listed if whole else None
        # An empty list asks for the annotations to be read when the item is written.
        plan.annotations[key] = [] if key in annotated else None
    return plan


def _read_annotations(backend: Any, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ch in children:
        data = ch.get("data") or {}
        if data.get("itemType") != "attachment" or not ch.get("key"):
            continue
        for row in backend.children(str(ch["key"])):
            if (row.get("data") or {}).get("itemType") == "annotation":
                out.append(row)
    return out


def _write_planned(
    cfg: Config,
    backend: Any,
    plan: _Plan,
    changes: ChangeSet,
    stats: SyncStats,
    *,
    track: Track | None,
) -> list[Item]:
    written: list[Item] = []
    keys = list(plan.parents)
    for key in track(keys) if track else keys:
        try:
            raw = plan.parents[key]
            if raw is None:
                raw = backend.raw_item(key)
                if raw is None:
                    raise LibraryReadError(f"item {key} could not be read")
            children = plan.children[key]
            if children is None:
                children = backend.children(key)
            annotations = plan.annotations[key]
            if annotations is not None and not changes.full:
                annotations = _read_annotations(backend, children)
        except LibraryError:
            # Could not read is not the same as nothing there. Keep what is on disk.
            stats.unread += 1
            continue
        item = item_from_rows(raw, children, changes.collections)
        try:
            _n, _pdf, n_notes, row = write_item(
                cfg.out_dir,
                item,
                raw,
                children,
                changes.collections,
                cfg.summaries_dir,
                "none",
                exact=True,
                annotations=annotations,
            )
        except OSError as exc:
            # One folder the disk refused. The rest still get done; the version waits.
            stats.unwritten.append(f"{key}: {exc}")
            continue
        stats.written += 1
        stats.notes += n_notes
        stats.index.append(row)
        written.append(item)
    return written


def _retire_gone(
    cfg: Config,
    changes: ChangeSet,
    index: dict[str, dict[str, Any]],
    stats: SyncStats,
    *,
    dry_run: bool,
    accept_gone: bool = False,
) -> None:
    trashed = {str(row.get("key")) for row in changes.trashed}
    known = mirror_index(cfg.out_dir).keys()
    absent = [key for key in known if key not in changes.top_keys]
    if not accept_gone and len(known) >= 100 and len(absent) * 2 > len(known):
        raise LibraryError(
            f"{len(absent)} of {len(known)} mirrored items are not in this library. "
            "That looks like a different library. Nothing was marked. "
            "Pass --accept-gone if it is right."
        )
    for key in absent:
        state = "trashed" if key in trashed else "gone"
        if (index.get(key) or {}).get("state") == state:
            continue
        record = load_record(cfg.out_dir, key)
        if record is None:
            continue
        if library_state(record) != state:
            stats.gone += 1
            if not dry_run:
                retire(cfg.out_dir, key, state, policy=cfg.mirror_gone)
        row = dict(index.get(key) or {"item_key": key, "dirs": []})
        row["state"] = state
        stats.index.append(row)


def stored_pdf_missing(record: dict[str, Any], folder: Path) -> bool:
    """The manager holds a PDF for this item and the folder does not."""
    if library_state(record) in GONE_STATES:
        return False
    rows = [r for r in (record.get("attachments") or []) if isinstance(r, dict)]
    return any(is_pdf_attachment(r) for r in rows) and record_pdf(folder, record) is None


def _cache_is_current(cached: Path, record: dict[str, Any]) -> bool:
    """An earlier export of this item's PDF. Checked against the manager's MD5 when it gave one."""
    if not cached.is_file():
        return False
    known = {
        r.get("md5")
        for r in record.get("attachments") or []
        if isinstance(r, dict) and r.get("md5")
    }
    if not known:
        return True
    return hashlib.md5(cached.read_bytes()).hexdigest() in known


def copy_pdfs(
    cfg: Config,
    backend: Any,
    keys: list[str] | None,
    stats: SyncStats,
    *,
    track: Track | None = None,
) -> bool:
    """Bring files the manager holds into their item folders. Returns True when none are left.

    ``keys`` limits the pass; ``None`` walks the whole mirror. A file already
    exported to ``state/pdf-cache/`` is moved in instead of asked for again.
    When ``pdfs=all``, non-PDF stored attachments are copied too. Safe to stop
    and run again: each file is done or not.
    """
    index = mirror_index(cfg.out_dir)
    todo: list[tuple[str, Path, dict[str, Any]]] = []
    for key in keys if keys is not None else index.keys():
        dirs = index.dirs(key)
        if not dirs:
            continue
        record = load_json(record_path(dirs[0]))
        if record is None:
            continue
        if stored_pdf_missing(record, dirs[0]) or _non_pdf_missing(record, dirs[0]):
            todo.append((key, dirs[0], record))
    complete = True
    rows = track(todo) if track else todo
    export_att = getattr(backend, "export_attachment", None)
    for key, folder, record in rows:
        item = item_from_record(record, folder, cfg.out_dir)
        if item is None:
            continue
        if stored_pdf_missing(record, folder):
            dest = folder / item_filename(item)
            cached = cfg.pdf_cache_dir / f"{key}.pdf"
            got: Path | None = None
            if _cache_is_current(cached, record):
                shutil.move(str(cached), dest)
                got = dest
            else:
                try:
                    got = backend.export_pdf(item, dest)
                except LibraryError:
                    stats.unread += 1
                    complete = False
                    continue
            if got is None or not Path(got).is_file():
                # The row is there and the bytes are not: a ghost. Not ours to fix here.
                stats.pdf_missing += 1
            else:
                stats.pdf_exports += 1
                stats.pdf_keys.append(key)
                for extra in index.dirs(key)[1:]:
                    target = extra / Path(got).name
                    if not target.exists():
                        try:
                            target.hardlink_to(got)
                        except OSError:
                            shutil.copyfile(got, target)
        if callable(export_att):
            for row in record.get("attachments") or []:
                if not isinstance(row, dict) or not row.get("key"):
                    continue
                if row.get("linkMode") == "linked_url":
                    continue
                if is_pdf_attachment(row) or row.get("contentType") == "application/pdf":
                    continue
                name = row.get("filename") or row.get("title") or f"{row['key']}.bin"
                safe = Path(str(name)).name or f"{row['key']}.bin"
                dest = folder / safe
                if dest.is_file():
                    continue
                try:
                    got = export_att(str(row["key"]), dest)
                except LibraryError:
                    stats.unread += 1
                    complete = False
                    continue
                if got is None or not Path(got).is_file():
                    continue
                stats.pdf_exports += 1
                for extra in index.dirs(key)[1:]:
                    target = extra / Path(got).name
                    if not target.exists():
                        try:
                            target.hardlink_to(got)
                        except OSError:
                            shutil.copyfile(got, target)
    return complete


def _non_pdf_missing(record: dict[str, Any], folder: Path) -> bool:
    if library_state(record) in GONE_STATES:
        return False
    for row in record.get("attachments") or []:
        if not isinstance(row, dict) or not row.get("key"):
            continue
        if row.get("linkMode") == "linked_url":
            continue
        if is_pdf_attachment(row) or row.get("contentType") == "application/pdf":
            continue
        name = row.get("filename") or row.get("title") or f"{row['key']}.bin"
        safe = Path(str(name)).name or f"{row['key']}.bin"
        if not (folder / safe).is_file():
            return True
    return False


def run_sync(
    cfg: Config,
    backend: Any,
    *,
    full: bool = False,
    dry_run: bool = False,
    pdfs: str | None = None,
    accept_gone: bool = False,
    backfill: bool = True,
    track: Track | None = None,
    pdf_track: Track | None = None,
    status: Callable[[str], None] | None = None,
) -> SyncStats:
    """Bring ``out/`` up to the manager's current state. Raises ``LibraryError`` on a failed read.

    ``backfill=False`` is the refresh a command does before it reads: PDFs are
    copied for the items that changed, and a mirror that is still missing
    older PDFs is left for ``paperful sync`` to fill.
    """
    say = status or (lambda _msg: None)
    mode = pdfs or cfg.mirror_pdfs
    state = sync_state(cfg.out_dir) or {}
    stats = SyncStats(previous=state.get("version"))
    read = getattr(backend, "changes", None)
    if not callable(read):
        raise LibraryError("This manager has no incremental refresh. Use snapshot.")

    since = None if full else state.get("version")
    say("Asking the library what changed…")
    changes: ChangeSet = read(since)
    if since is not None and state.get("library") not in ("", None, changes.library_id):
        # Another database answers on the same port. Its versions mean nothing here.
        since = None
        changes = read(None)
    stats.full = changes.full
    stats.version = changes.version

    index = read_index(cfg.out_dir)
    if changes.full:
        plan = _plan_full(changes)
    else:
        plan = _plan_delta(changes, index, backend)

    if dry_run:
        stats.written = len(plan.parents)
        _retire_gone(cfg, changes, index, stats, dry_run=True, accept_gone=True)
        stats.index.clear()
        return stats

    # Checked before anything is written: a wrong library must not half-apply.
    _retire_gone(cfg, changes, index, SyncStats(), dry_run=True, accept_gone=accept_gone)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_collections(cfg.out_dir, changes.collections)
    if plan.parents:
        say(f"Writing {len(plan.parents)} item(s)…")
    written = _write_planned(cfg, backend, plan, changes, stats, track=track)
    _retire_gone(cfg, changes, index, stats, dry_run=False, accept_gone=True)
    _write_standalones(cfg, backend, changes, stats, dry_run=False)
    if stats.index:
        merge_index(cfg.out_dir, stats.index)
    write_history(cfg.out_dir, cfg)

    # The version moves only when everything it covers is on disk.
    pdfs_complete = bool(state.get("pdfs_complete"))
    if stats.unread == 0 and not stats.unwritten:
        _write_state(cfg, changes, state, stats, pdfs_complete=pdfs_complete and mode == "all")

    if mode == "all" and (backfill or not changes.full):
        # A command's own refresh never starts the whole-library copy, even
        # when it is the first one: that is for ``paperful sync``.
        whole = backfill and (changes.full or not pdfs_complete)
        keys = None if whole else [i.key for i in written]
        if whole:
            say("Copying PDFs into the mirror…")
        done = copy_pdfs(cfg, backend, keys, stats, track=pdf_track)
        if whole and done and stats.unread == 0 and not stats.unwritten:
            _write_state(cfg, changes, state, stats, pdfs_complete=True)
    return stats


def _write_standalones(
    cfg: Config,
    backend: Any,
    changes: ChangeSet,
    stats: SyncStats,
    *,
    dry_run: bool,
) -> None:
    """Mirror top-level notes and attachments under ``out/_notes`` / ``out/_attachments``."""
    if dry_run:
        return
    export_att = getattr(backend, "export_attachment", None)
    for row in changes.rows:
        data = row.get("data") or {}
        if data.get("parentItem"):
            continue
        kind = data.get("itemType")
        key = str(row.get("key") or "")
        if not key:
            continue
        if kind == "note":
            folder = cfg.out_dir / NOTES_DIR / key
            folder.mkdir(parents=True, exist_ok=True)
            html = str(data.get("note") or "")
            (folder / "note.html").write_text(html, encoding="utf-8")
            tags = [
                str(t.get("tag"))
                for t in (data.get("tags") or [])
                if isinstance(t, dict) and t.get("tag")
            ]
            collections = [
                str(c) for c in (data.get("collections") or []) if c
            ]
            write_json(
                folder / "record.json",
                {
                    "schema": STANDALONE_SCHEMA,
                    "key": key,
                    "item_type": "note",
                    "title": data.get("title") or "",
                    "tags": tags,
                    "collections": collections,
                    "note_file": "note.html",
                },
            )
            stats.notes += 1
        elif kind == "attachment":
            folder = cfg.out_dir / ATTACHMENTS_DIR / key
            folder.mkdir(parents=True, exist_ok=True)
            name = data.get("filename") or data.get("title") or f"{key}.bin"
            safe = Path(str(name)).name or f"{key}.bin"
            dest = folder / safe
            if (
                not dest.is_file()
                and callable(export_att)
                and data.get("linkMode") != "linked_url"
            ):
                try:
                    export_att(key, dest)
                except LibraryError:
                    stats.unread += 1
            collections = [
                str(c) for c in (data.get("collections") or []) if c
            ]
            write_json(
                folder / "record.json",
                {
                    "schema": STANDALONE_SCHEMA,
                    "key": key,
                    "item_type": "attachment",
                    "title": data.get("title") or "",
                    "filename": safe,
                    "contentType": data.get("contentType"),
                    "linkMode": data.get("linkMode"),
                    "md5": data.get("md5"),
                    "collections": collections,
                    "file": safe if dest.is_file() else None,
                },
            )


def _write_state(
    cfg: Config,
    changes: ChangeSet,
    previous: dict[str, Any],
    stats: SyncStats,
    *,
    pdfs_complete: bool,
) -> None:
    now = _now()
    write_json(
        cfg.out_dir / _STATE_FILE,
        {
            "schema": SYNC_SCHEMA,
            "manager": (cfg.manager or "zotero").strip().lower(),
            "library": changes.library_id,
            "version": changes.version,
            "synced_at": now,
            "full_sync_at": now if changes.full else previous.get("full_sync_at"),
            "pdfs_complete": pdfs_complete,
            "last_written": stats.written,
            "last_gone": stats.gone,
        },
    )


def clean_pdf_cache(
    cfg: Config, *, apply: bool = False
) -> dict[str, Any]:
    """Remove ``state/pdf-cache/`` files already absorbed into ``out/`` or stale vs MD5.

    Dry-run by default (``apply=False``). Returns counts of kept / removable / removed.
    """
    cache = cfg.pdf_cache_dir
    removable: list[Path] = []
    kept = 0
    if cache.is_dir():
        index = mirror_index(cfg.out_dir)
        for path in sorted(cache.glob("*.pdf")):
            key = path.stem
            dirs = index.dirs(key)
            record = load_json(record_path(dirs[0])) if dirs else None
            in_mirror = bool(dirs) and (
                (record is not None and record_pdf(dirs[0], record) is not None)
                or any(dirs[0].glob("*.pdf"))
            )
            stale = record is not None and not _cache_is_current(path, record)
            if in_mirror or stale:
                removable.append(path)
            else:
                kept += 1
    removed = 0
    failed = 0
    if apply:
        for path in list(removable):
            try:
                path.unlink()
                removed += 1
            except OSError:
                failed += 1
                kept += 1
    return {
        "cache_dir": str(cache),
        "kept": kept,
        "removable": len(removable),
        "removed": removed,
        "failed": failed,
        "apply": apply,
        "paths": [str(p) for p in removable] if not apply else [],
    }


def sync_report(cfg: Config, stats: SyncStats, *, dry_run: bool, pdfs: str) -> dict[str, Any]:
    now = _now()
    return {
        "schema": "paperful.run_report.v1",
        "command": "sync",
        "started_at": now,
        "finished_at": now,
        "scope": "whole library",
        "flags": {"dry_run": dry_run, "pdfs": pdfs, "full": stats.full},
        "paths": {"out_dir": str(cfg.out_dir), "state_dir": str(cfg.state_dir)},
        "summary": {
            "library_version": stats.version,
            "previous_version": stats.previous,
            "written": stats.written,
            "gone": stats.gone,
            "unread": stats.unread,
            "unwritten": len(stats.unwritten),
            "pdf_exports": stats.pdf_exports,
            "pdf_missing": stats.pdf_missing,
            "notes": stats.notes,
        },
    }
