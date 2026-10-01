"""Read side of the native mirror under ``out/``.

Paperful works from this copy. The manager API refreshes it and takes explicit
write-back; nothing here calls a manager. See ``docs/architecture.md``
(Mirror first).
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import (
    Manifest,
    is_item_dirname,
    item_dirname,
    item_key_from_dirname,
    load_json,
    record_path,
    resolve_pdf_path,
    write_json,
)
from .zot import (
    UNCOLLECTED,
    Item,
    is_linked_url_pdf,
    is_pdf_attachment,
    item_from_json,
)

# Folders of items that left the library, when ``[mirror].gone = "trash"``.
TRASH_DIR = "_trash"
GONE_POLICIES = frozenset({"mark", "trash"})

_INDEXES: dict[Path, "MirrorIndex"] = {}
_INDEX_LOCK = threading.Lock()


def _clean_prefixes(prefixes: list[str] | None) -> list[str]:
    return [p.strip("/") for p in (prefixes or []) if p and p.strip("/")]


def iter_item_dirs(
    out_dir: Path, collection_prefixes: list[str] | None = None
) -> Iterator[Path]:
    """Item folders (``<stem> -- KEY``) in path order. Does not look inside them."""
    if not out_dir.is_dir():
        return
    prefixes = _clean_prefixes(collection_prefixes)
    for root, dirs, _files in os.walk(out_dir):
        dirs.sort()
        here = Path(root)
        if here == out_dir and TRASH_DIR in dirs:
            dirs.remove(TRASH_DIR)
        keep: list[str] = []
        for name in dirs:
            if not is_item_dirname(name):
                keep.append(name)
                continue
            if prefixes:
                collection = here.relative_to(out_dir).as_posix()
                collection = "" if collection == "." else collection
                if not any(
                    collection == pre or collection.startswith(pre + "/")
                    for pre in prefixes
                ):
                    continue
            yield here / name
        dirs[:] = keep


class MirrorIndex:
    """Item key → folders. A key has one folder per collection path."""

    def __init__(self, out_dir: Path, by_key: dict[str, list[Path]]):
        self.out_dir = out_dir
        self.by_key = by_key

    @classmethod
    def scan(cls, out_dir: Path) -> MirrorIndex:
        by_key: dict[str, list[Path]] = {}
        for folder in iter_item_dirs(out_dir):
            key = item_key_from_dirname(folder.name)
            if key:
                by_key.setdefault(key, []).append(folder)
        return cls(out_dir, by_key)

    def dirs(self, key: str) -> list[Path]:
        return [d for d in self.by_key.get(key, []) if d.is_dir()]

    def add(self, key: str, folder: Path) -> None:
        rows = self.by_key.setdefault(key, [])
        if folder not in rows:
            rows.append(folder)

    def move(self, key: str, old: Path, new: Path) -> None:
        rows = self.by_key.setdefault(key, [])
        if old in rows:
            rows.remove(old)
        if new not in rows:
            rows.append(new)

    def drop(self, key: str, folder: Path) -> None:
        rows = self.by_key.get(key, [])
        if folder in rows:
            rows.remove(folder)

    def keys(self) -> list[str]:
        return sorted(self.by_key)


def mirror_index(out_dir: Path, *, rescan: bool = False) -> MirrorIndex:
    """One scan per process and ``out_dir``. Pass ``rescan`` after moving folders."""
    root = out_dir.resolve()
    with _INDEX_LOCK:
        if rescan or root not in _INDEXES:
            _INDEXES[root] = MirrorIndex.scan(out_dir)
        return _INDEXES[root]


def forget_index(out_dir: Path | None = None) -> None:
    if out_dir is None:
        _INDEXES.clear()
    else:
        _INDEXES.pop(out_dir.resolve(), None)


def note_folder(out_dir: Path, key: str, folder: Path) -> None:
    """Tell an index that is already loaded about a folder made after its scan."""
    index = _INDEXES.get(out_dir.resolve())
    if index is not None:
        index.add(key, folder)


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if a.samefile(b):
            return True
        if a.stat().st_size != b.stat().st_size:
            return False
        return hashlib.md5(a.read_bytes()).digest() == hashlib.md5(b.read_bytes()).digest()
    except OSError:
        return False


def same_place(a: Path, b: Path) -> bool:
    """Two spellings of one directory.

    On a filesystem that ignores case or Unicode form (macOS), a folder named
    for ``ANALYSIS OF…`` and one named for ``Analysis of…`` are the same
    folder. Comparing the strings would call it two.
    """
    if a == b:
        return True
    try:
        return a.samefile(b)
    except OSError:
        return False


def fold_folder(src: Path, dest: Path) -> None:
    """Empty ``src`` into ``dest`` and remove it. No file is lost.

    The record is dropped (``dest`` has its own). A file ``dest`` already
    holds, byte for byte, is dropped. Anything else moves across, under a
    numbered name when the name is taken.
    """
    if same_place(src, dest):
        return  # folding a folder into itself would delete what it holds
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if rel.as_posix() == "record.json":
            path.unlink()
            continue
        target = dest / rel
        if target.exists():
            if _same_bytes(path, target):
                path.unlink()
                continue
            n = 2
            while target.exists():
                target = dest / rel.with_name(f"{rel.stem} ({n}){rel.suffix}")
                n += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
    for path in sorted(src.rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()
    src.rmdir()


def place_item_dirs(
    out_dir: Path, item: Item, *, dry_run: bool = False, exact: bool = False
) -> list[Path]:
    """Folders ``item`` belongs in, one per collection path. Creates what is missing.

    A folder named for an older title or author is renamed in place, so a
    retitled item keeps its PDF and does not grow a second folder.

    ``exact`` says ``item.collection_paths`` is the item's whole membership,
    not a scoped slice of it. Then a folder in a collection the item left is
    moved to one it joined, or folded into the first folder. Without it,
    folders in other collections are left alone.
    """
    wanted = [
        out_dir / path / item_dirname(item)
        for path in item.collection_paths or [UNCOLLECTED]
    ]
    if dry_run:
        return wanted
    index = mirror_index(out_dir)

    def spare() -> list[Path]:
        return [
            d
            for d in index.dirs(item.key)
            if not any(same_place(d, w) for w in wanted)
        ]

    for target in wanted:
        here = next((d for d in index.dirs(item.key) if same_place(d, target)), None)
        if here is not None and here != target:
            # Same folder, other spelling (a title recased). Take the new one.
            try:
                here.rename(target)
            except OSError:
                pass
            index.move(item.key, here, target)
        elif here is None and not target.is_dir():
            left = spare()
            stale = next((d for d in left if d.parent == target.parent), None)
            if stale is None and exact:
                stale = left[0] if left else _trashed_folder(out_dir, item.key)
            if stale is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                stale.rename(target)
                index.move(item.key, stale, target)
            else:
                target.mkdir(parents=True, exist_ok=True)
        index.add(item.key, target)
    if exact:
        for folder in spare():
            fold_folder(folder, wanted[0])
            index.drop(item.key, folder)
    return wanted


def _trashed_folder(out_dir: Path, key: str) -> Path | None:
    """A folder for ``key`` under ``_trash/``: the item came back to the library."""
    trash = out_dir / TRASH_DIR
    if not trash.is_dir():
        return None
    index = mirror_index(trash)
    found = index.dirs(key)
    if not found:
        return None
    index.drop(key, found[0])
    return found[0]


def retire(
    out_dir: Path,
    key: str,
    state: str = "trashed",
    *,
    policy: str = "mark",
    merged_into: str | None = None,
) -> int:
    """``key`` left the library. Mark its records; under ``trash`` also move the folders.

    Nothing is deleted. Returns the number of folders touched.
    """
    touched = mark_gone(out_dir, key, state, merged_into=merged_into)
    if policy != "trash":
        return touched
    index = mirror_index(out_dir)
    for folder in index.dirs(key):
        dest = out_dir / TRASH_DIR / folder.relative_to(out_dir)
        if dest.is_dir():
            # Trashed before, restored, trashed again. Keep one folder.
            fold_folder(dest, folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(dest)
        index.drop(key, folder)
        note_folder(out_dir / TRASH_DIR, key, dest)
    return touched


def item_dirs(out_dir: Path, item: Item) -> list[Path]:
    """Folders this item has now. Named paths first, then any other folder for the key."""
    found: list[Path] = []
    for path in item.collection_paths or [UNCOLLECTED]:
        folder = out_dir / path / item_dirname(item)
        if folder.is_dir():
            found.append(folder)
    if found:
        return found
    # The title, author, or collection changed since the folder was named.
    return mirror_index(out_dir).dirs(item.key)


def load_record(out_dir: Path, key: str) -> dict[str, Any] | None:
    """The first readable ``record.json`` for ``key``."""
    for folder in mirror_index(out_dir).dirs(key):
        rec = load_json(record_path(folder))
        if rec is not None:
            return rec
    return None


def update_record(
    out_dir: Path, key: str, change: Callable[[dict[str, Any]], None]
) -> int:
    """Apply ``change`` to every folder's record for ``key``. Returns folders written."""
    written = 0
    for folder in mirror_index(out_dir).dirs(key):
        path = record_path(folder)
        rec = load_json(path)
        if rec is None:
            continue
        change(rec)
        write_json(path, rec)
        written += 1
    return written


GONE_STATES = frozenset({"trashed", "gone"})


def library_state(record: dict[str, Any]) -> str:
    """``present`` unless the record says the item left the library."""
    block = record.get("library")
    if isinstance(block, dict) and block.get("state"):
        return str(block["state"])
    return "present"


def mark_gone(
    out_dir: Path, key: str, state: str = "trashed", *, merged_into: str | None = None
) -> int:
    """Record that ``key`` left the library. The folder and its files stay."""
    block: dict[str, Any] = {
        "state": state,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if merged_into:
        block["merged_into"] = merged_into
    return update_record(out_dir, key, lambda rec: rec.__setitem__("library", block))


def record_pdf(item_dir: Path, record: dict[str, Any] | None = None) -> Path | None:
    """The PDF in an item folder. The fetched file wins when several are present."""
    fetch = (record or {}).get("fetch")
    named = fetch.get("pdf") if isinstance(fetch, dict) else None
    if named:
        candidate = item_dir / str(named)
        if candidate.is_file():
            return candidate
    pdfs = sorted(p for p in item_dir.glob("*.pdf") if p.is_file())
    return pdfs[0] if pdfs else None


def _attachment_flags(record: dict[str, Any]) -> tuple[bool, bool]:
    """``(stored PDF, linked-URL PDF only)`` from the record's attachment rows."""
    rows = [r for r in (record.get("attachments") or []) if isinstance(r, dict)]
    stored = any(is_pdf_attachment(r) for r in rows)
    linked = any(is_linked_url_pdf(r) for r in rows)
    return stored, linked and not stored


def _record_paths(
    record: dict[str, Any], folder_collection: str, selected: set[str] | None
) -> list[str]:
    rows = [r for r in (record.get("collections") or []) if isinstance(r, dict)]
    if selected is not None and any(r.get("key") for r in rows):
        paths = [str(r["path"]) for r in rows if r.get("key") in selected and r.get("path")]
        return sorted(paths) or [UNCOLLECTED]
    paths = record.get("collection_paths")
    if isinstance(paths, list) and any(paths):
        return sorted(str(p) for p in paths if p)
    return [folder_collection] if folder_collection else []


def item_from_record(
    record: dict[str, Any],
    item_dir: Path,
    out_dir: Path,
    *,
    selected: set[str] | None = None,
) -> Item | None:
    """The same ``Item`` a live listing gives, built from ``record.json``.

    ``selected`` limits ``collection_paths`` to those collection keys, as a
    collection-scoped listing does.
    """
    key = str(record.get("item_key") or item_key_from_dirname(item_dir.name) or "")
    if not key:
        return None
    fields = record.get("fields")
    data: dict[str, Any] = dict(fields) if isinstance(fields, dict) else {}
    creators = record.get("creators")
    data.update(
        {
            "itemType": record.get("item_type") or "document",
            "title": record.get("title") or "",
            "creators": creators if isinstance(creators, list) else [],
            "abstractNote": record.get("abstract") or "",
            "date": record.get("date") or "",
            "url": record.get("url") or "",
            "extra": record.get("extra") or "",
            "publicationTitle": record.get("publication_title") or "",
            "dateAdded": record.get("date_added") or "",
            "collections": [],
        }
    )
    stored, linked = _attachment_flags(record)
    pdf = record_pdf(item_dir, record)
    item = item_from_json(
        {"key": key, "data": data, "meta": {}},
        {},
        None,
        has_pdf=stored or pdf is not None,
        has_linked_url=linked,
    )
    # Identifier fields are stored as the listing computed them.
    year = record.get("year")
    item.year = year if isinstance(year, int) else None
    item.doi = record.get("doi") or None
    item.library_doi = record.get("library_doi") or None
    item.doi_source = str(record.get("doi_source") or "none")
    item.doi_verified = str(record.get("doi_verified") or "missing")
    item.arxiv_id = record.get("arxiv_id") or item.arxiv_id
    item.pmid = record.get("pmid") or item.pmid
    try:
        collection = item_dir.parent.relative_to(out_dir).as_posix()
    except ValueError:
        collection = ""
    item.collection_paths = _record_paths(
        record, "" if collection == "." else collection, selected
    )
    item.pdf_path = str(pdf) if pdf else None
    return item


def items_in_mirror(
    out_dir: Path, collection_prefixes: list[str] | None = None
) -> list[Item]:
    """Catalogue rows already on disk. The live manager is not required."""
    items: list[Item] = []
    seen: set[str] = set()
    for folder in iter_item_dirs(out_dir, collection_prefixes):
        record = load_json(record_path(folder))
        if record is None or library_state(record) in GONE_STATES:
            continue
        item = item_from_record(record, folder, out_dir)
        if item is None or item.key in seen:
            continue
        seen.add(item.key)
        items.append(item)
    return items


def pdf_for_key(out_dir: Path, key: str) -> Path | None:
    """A PDF in any folder the mirror has for ``key``."""
    for folder in mirror_index(out_dir).dirs(key):
        pdf = record_pdf(folder, load_json(record_path(folder)))
        if pdf is not None:
            return pdf
    return None


def pdf_for(out_dir: Path, item: Item, manifest: Manifest | None = None) -> Path | None:
    """A PDF for ``item`` that is already on this machine. Never asks the manager."""
    if item.pdf_path:
        path = Path(item.pdf_path)
        if path.is_file():
            return path
    rec = manifest.get(item.key) if manifest else None
    if rec and rec.path:
        path = resolve_pdf_path(out_dir, rec.path)
        if path is not None and path.is_file():
            return path
    for folder in item_dirs(out_dir, item):
        pdf = record_pdf(folder, load_json(record_path(folder)))
        if pdf is not None:
            return pdf
    return None
