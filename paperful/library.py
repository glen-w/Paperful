"""Reference-manager adapters. Core work stays on disk; managers only read/write."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pyzotero import errors as ze

from .attach import AttachResult, Attacher
from .config import Config
from .zot import (
    Collection,
    Item,
    ZoteroLocal,
    build_collection_tree,
    is_pdf_attachment,
    item_from_rows,
)


class LibraryError(Exception):
    pass


class LibraryReadError(LibraryError):
    """The manager could not be read. Never the same as "nothing there"."""


def note_payload(html: str, tag: str, parent_item: str) -> dict[str, Any]:
    """A child note as the Zotero write API expects it (no /items/new template)."""
    return {
        "itemType": "note",
        "note": html,
        "parentItem": parent_item,
        "tags": [{"tag": tag}],
        "collections": [],
        "relations": {},
    }


def collection_note_payload(
    html: str, tags: list[str], collection_key: str
) -> dict[str, Any]:
    """A top-level note filed in one collection (no parent item)."""
    return {
        "itemType": "note",
        "note": html,
        "tags": [{"tag": tag} for tag in tags],
        "collections": [collection_key],
        "relations": {},
    }


def created_item_key(result: Any) -> str:
    """Pull the new item key out of a Zotero write-API create_items response."""
    if not result:
        return ""
    if isinstance(result, list):
        if not result:
            return ""
        first = result[0]
        if isinstance(first, dict):
            return str(first.get("key") or (first.get("data") or {}).get("key") or "")
        return str(first)
    if isinstance(result, dict):
        for bucket in ("success", "successful", "unchanged"):
            val = result.get(bucket)
            if isinstance(val, dict) and val:
                first = next(iter(val.values()))
                if isinstance(first, dict):
                    return str(
                        first.get("key") or (first.get("data") or {}).get("key") or ""
                    )
                return str(first)
            if isinstance(val, list) and val:
                first = val[0]
                if isinstance(first, dict):
                    return str(first.get("key") or "")
                return str(first)
    return ""


class LibraryBackend(Protocol):
    def ping(self) -> dict[str, Any]: ...
    def collections(self) -> dict[str, Collection]: ...
    def collection_counts(self) -> dict[str, tuple[int, int]]: ...
    def resolve_collection(self, spec: str) -> Collection: ...
    def subtree_keys(self, root: Collection) -> list[str]: ...
    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]: ...
    def items_in_scope(self, collection_keys: list[str] | None) -> list[Item]: ...
    def count_linked_url_only(self, collection_keys: list[str] | None) -> int: ...
    def get_item(self, key: str) -> Item | None: ...
    def raw_item(self, key: str) -> dict[str, Any] | None: ...
    def children(self, key: str) -> list[dict[str, Any]]: ...
    def export_pdf(self, item: Item, dest: Path) -> Path | None: ...
    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None: ...
    def relate_items(self, left_key: str, right_key: str) -> None: ...
    def trash_item(self, item_key: str) -> None: ...
    def trash_note(self, note_key: str, *, parent_key: str = "") -> None: ...
    def merge_into(self, keep_key: str, drop_key: str) -> dict[str, Any]: ...
    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]: ...
    def read_child_note(self, item_key: str, tag: str) -> str | None: ...
    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str: ...
    def replace_prefixed_tag(self, item_key: str, prefix: str, tag: str) -> None: ...
    def find_collection_note_keys(self, collection_key: str, tag: str) -> list[str]: ...
    def create_or_update_collection_note(
        self, collection_key: str, html: str, tags: list[str]
    ) -> str: ...
    def supports_write(self) -> bool: ...
    def ensure_collection_path(self, path: str) -> str: ...
    def create_parent(self, data: dict[str, Any]) -> str: ...
    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult: ...
    def flush_writes(self) -> Path | None: ...


def get_backend(cfg: Config, zl: ZoteroLocal | None = None) -> LibraryBackend:
    manager = (cfg.manager or "zotero").strip().lower()
    if manager == "mendeley":
        from .mendeley import MendeleyBackend

        return MendeleyBackend(cfg)
    if manager == "endnote":
        from .endnote import EndNoteBackend

        return EndNoteBackend(cfg)
    if manager != "zotero":
        raise LibraryError(
            f"Unknown manager {manager!r}. Known: zotero, mendeley, endnote."
        )
    return ZoteroBackend(cfg, zl)


@dataclass
class ChangeSet:
    """What the manager says changed. Facts only; the sync engine decides what to write."""

    version: int | None  # library version these rows were read at
    full: bool  # ``rows`` is the whole library, not a delta
    rows: list[dict[str, Any]]  # raw items of every type, trashed ones excluded
    top_keys: set[str]  # every top-level key now in the library
    all_keys: set[str]  # every item key now in the library, children included
    trashed: list[dict[str, Any]]  # raw rows in the manager's trash
    collections: dict[str, Collection]
    library_id: str = ""  # changes when the manager is pointed at another database


def mirrored(cfg: Config, backend: LibraryBackend) -> LibraryBackend:
    """``backend`` with write-through to the mirror under ``cfg.out_dir``."""
    if isinstance(backend, MirroredBackend):
        return backend
    return MirroredBackend(cfg, backend)  # type: ignore[return-value]


class MirroredBackend:
    """Write-through. A write to the manager is followed by a re-read of that item
    into ``out/``, so the mirror does not wait for the next snapshot to be true.

    Reads and anything not named here go straight to the wrapped backend. A
    failed re-read never fails the write: the key is kept in ``unrefreshed``.
    """

    def __init__(self, cfg: Config, inner: Any):
        self._cfg = cfg
        self._inner = inner
        self.unrefreshed: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or "_inner" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self._inner, name)

    # ---- mirror side ---------------------------------------------------
    def refresh(self, key: str) -> bool:
        """Re-read one parent item and rewrite its folders. Two requests."""
        from .snapshot import append_index, write_item

        if not key or not callable(getattr(self._inner, "raw_item", None)):
            return False
        try:
            raw = self._inner.raw_item(key)
            if not isinstance(raw, dict):
                raise LibraryReadError(f"item {key} could not be read")
            data = raw.get("data") or {}
            if data.get("parentItem") or data.get("itemType") in {
                "attachment",
                "note",
                "annotation",
            }:
                return False
            children = self._inner.children(key)
            build = getattr(self._inner, "item_from_raw", None)
            item = build(raw, children) if callable(build) else self._inner.get_item(key)
            if item is None:
                raise LibraryReadError(f"item {key} could not be read")
            *_counts, row = write_item(
                self._cfg.out_dir,
                item,
                raw,
                children,
                self._inner.collections(),
                self._cfg.summaries_dir,
                "none",
            )
            append_index(self._cfg.out_dir, row)
        except Exception:
            # The manager already holds the write. The next refresh of the
            # mirror picks this item up; do not report the write as failed.
            if key not in self.unrefreshed:
                self.unrefreshed.append(key)
            return False
        if key in self.unrefreshed:
            self.unrefreshed.remove(key)
        return True

    def _gone(self, key: str, *, merged_into: str | None = None) -> None:
        from .mirror import retire

        try:
            retire(
                self._cfg.out_dir,
                key,
                "trashed",
                policy=self._cfg.mirror_gone,
                merged_into=merged_into,
            )
        except OSError:
            if key not in self.unrefreshed:
                self.unrefreshed.append(key)

    # ---- writes ----------------------------------------------------------
    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None:
        self._inner.apply_patch(item_key, fields)
        self.refresh(item_key)

    def relate_items(self, left_key: str, right_key: str) -> None:
        self._inner.relate_items(left_key, right_key)
        self.refresh(left_key)
        self.refresh(right_key)

    def replace_prefixed_tag(self, item_key: str, prefix: str, tag: str) -> None:
        self._inner.replace_prefixed_tag(item_key, prefix, tag)
        self.refresh(item_key)

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        key = self._inner.create_or_update_note(item_key, html, tag)
        self.refresh(item_key)
        return key

    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult:
        result = self._inner.attach(item_key, pdf_path, title, note=note)
        if getattr(result, "ok", False):
            self.refresh(item_key)
        return result

    def create_linked_file(self, parent_key: str, pdf_path: Path) -> str:
        key = self._inner.create_linked_file(parent_key, pdf_path)
        self.refresh(parent_key)
        return key

    def create_parent(self, data: dict[str, Any]) -> str:
        key = self._inner.create_parent(data)
        self.refresh(key)
        return key

    def ensure_collection_path(self, path: str) -> str:
        from .snapshot import write_collections

        key = self._inner.ensure_collection_path(path)
        try:
            write_collections(self._cfg.out_dir, self._inner.collections())
        except Exception:
            pass  # the tree is rewritten whole on the next refresh
        return key

    def trash_item(self, item_key: str) -> None:
        self._inner.trash_item(item_key)
        self._gone(item_key)

    def trash_note(self, note_key: str, *, parent_key: str = "") -> None:
        self._inner.trash_note(note_key, parent_key=parent_key)
        if parent_key:
            self.refresh(parent_key)

    def merge_into(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        result = self._inner.merge_into(keep_key, drop_key)
        self._gone(drop_key, merged_into=keep_key)
        self.refresh(keep_key)
        return result


class ZoteroBackend:
    """Zotero local API adapter. PDF extract/lint never call this except to export files."""

    def __init__(self, cfg: Config, zl: ZoteroLocal | None = None):
        self.cfg = cfg
        self.zl = zl or ZoteroLocal()
        self._attacher: Attacher | None = None

    def _read(self, what: str, fn: Callable[..., Any], *args: Any) -> Any:
        """One manager read. A missing key is ``None``; any other failure raises."""
        try:
            return fn(*args)
        except ze.ResourceNotFoundError:
            return None
        except Exception as exc:
            raise LibraryReadError(
                f"Zotero read failed ({what}): {type(exc).__name__}: {exc}"
            ) from exc

    def ping(self) -> dict[str, Any]:
        return self.zl.ping()

    def changes(self, since: int | None) -> ChangeSet:
        """Rows changed after library version ``since`` (all rows when ``None``).

        Six requests when nothing changed. The local API leaves trashed items
        out of every listing and has no ``/deleted``, so removals are read as
        key sets: what is in the library now, and what is in the trash.
        """

        def read() -> ChangeSet:
            params = {} if since is None else {"since": since}
            rows, version = self.zl.listing("/items", **params)
            cols_raw, _ = self.zl.listing("/collections")
            trashed, _ = self.zl.listing("/items/trash")
            return ChangeSet(
                version=version,
                full=since is None,
                rows=rows,
                top_keys=self.zl.keys("/items/top"),
                all_keys=self.zl.keys("/items"),
                trashed=trashed,
                collections=build_collection_tree(cols_raw),
                library_id=str(self.zl.ping().get("server_id") or ""),
            )

        changes = self._read("library changes", read)
        self.zl._collections = changes.collections
        return changes

    def collections(self) -> dict[str, Collection]:
        return self.zl.collections()

    def collection_counts(self) -> dict[str, tuple[int, int]]:
        return self.zl.collection_counts()

    def resolve_collection(self, spec: str) -> Collection:
        return self.zl.resolve_collection(spec)

    def subtree_keys(self, root: Collection) -> list[str]:
        return self.zl.subtree_keys(root)

    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]:
        return self.zl.items_lacking_pdf(collection_keys, upgrade_linked=upgrade_linked)

    def items_in_scope(
        self,
        collection_keys: list[str] | None,
        *,
        status: Callable[[str], None] | None = None,
    ) -> list[Item]:
        if status is not None:
            try:
                return self.zl.items_in_scope(collection_keys, status=status)
            except TypeError:
                status("Loading items from library…")
                return self.zl.items_in_scope(collection_keys)
        return self.zl.items_in_scope(collection_keys)

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        return self.zl.count_linked_url_only(collection_keys)

    def supports_write(self) -> bool:
        return bool(self.ping().get("supports_write"))

    @property
    def library_type(self) -> str:
        """Personal library. Group libraries are not this adapter."""
        return "user"

    def attachment_has_bytes(self, key: str) -> bool:
        """True when the local API returns a non-empty file for this attachment.

        Asks where the file is and looks there: no bytes move. When the path
        is not visible from here, falls back to pyzotero's file fetch. (A raw
        client stream misses the local API transport and reports every stored
        PDF as missing.)
        """
        locate = getattr(self.zl, "file_path", None)
        if callable(locate):
            try:
                path = locate(key)
            except Exception:
                path = None
            if path is not None:
                return path.is_file() and path.stat().st_size > 0
        try:
            payload = self.zl.zot.file(key)
        except Exception:
            return False
        if isinstance(payload, (bytes, bytearray)):
            return len(payload) > 0
        if isinstance(payload, str):
            return bool(payload)
        return False

    def relink_file(self, attachment_key: str, pdf_path: Path) -> None:
        """Point a linked attachment at a file. Does not delete the file."""
        self._ensure_write()
        if not pdf_path.is_file():
            raise LibraryError(f"file missing: {pdf_path}")
        raw = self.zl.zot.item(attachment_key)
        data = raw["data"]
        data["linkMode"] = "linked_file"
        data["path"] = str(pdf_path)
        data["filename"] = pdf_path.name
        self.zl.zot.update_item(raw)

    def create_linked_file(self, parent_key: str, pdf_path: Path) -> str:
        """Create a linked_file child. Does not delete the stored copy or the file."""
        self._ensure_write()
        if not pdf_path.is_file():
            raise LibraryError(f"file missing: {pdf_path}")
        payload = {
            "itemType": "attachment",
            "parentItem": parent_key,
            "linkMode": "linked_file",
            "title": "Full Text PDF",
            "path": str(pdf_path),
            "filename": pdf_path.name,
            "contentType": "application/pdf",
            "charset": "",
            "accessDate": "",
            "note": "",
            "tags": [],
            "relations": {},
        }
        try:
            created = self.zl.zot.create_items([payload])
        except Exception as exc:
            raise LibraryError(f"Zotero did not create linked file: {exc}") from exc
        key = created_item_key(created)
        if not key:
            raise LibraryError("Zotero did not create linked file")
        return key

    def trash_attachment(self, attachment_key: str) -> None:
        """Trash one attachment child. Does not delete the file under out/."""
        self.trash_item(attachment_key)

    def _ensure_write(self) -> None:
        if self._attacher is None:
            self._attacher = Attacher(self.cfg, self.zl)
        if not self._attacher.supports_write():
            raise LibraryError(self._attacher.write_block_reason())
        if not self.zl.zot.local_api_key:
            if not self._attacher.authorize():
                raise LibraryError("write authorisation denied in Zotero")

    def ensure_collection_path(self, path: str) -> str:
        """Return the key for ``path``, creating missing segments. Does not rename."""
        self._ensure_write()
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            raise LibraryError(f"empty collection path {path!r}")
        parent: str | None = None
        built: list[str] = []
        for part in parts:
            built.append(part)
            sofar = "/".join(built)
            self.zl._collections = None
            found = next(
                (c for c in self.collections().values() if c.path == sofar), None
            )
            if found is not None:
                parent = found.key
                continue
            payload: dict[str, Any] = {"name": part}
            if parent:
                payload["parentCollection"] = parent
            result = self.zl.zot.create_collections([payload])
            parent = created_item_key(result)
            if not parent:
                raise LibraryError(
                    f"Zotero did not return a key for collection {sofar}"
                )
            self.zl._collections = None
        if parent is None:
            raise LibraryError(f"could not resolve collection {path!r}")
        return parent

    def create_parent(self, data: dict[str, Any]) -> str:
        """Create a top-level bibliographic item. Returns the new key."""
        self._ensure_write()
        result = self.zl.zot.create_items([data])
        key = created_item_key(result)
        if not key:
            raise LibraryError("Zotero did not return a key for the new item")
        return key

    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult:
        self._ensure_write()
        assert self._attacher is not None
        return self._attacher.attach(item_key, pdf_path, title, note=note)

    def flush_writes(self) -> Path | None:
        return None

    def item_from_raw(
        self, raw: dict[str, Any], children: list[dict[str, Any]]
    ) -> Item:
        """The listing's ``Item`` from payloads already read. No request."""
        return item_from_rows(raw, children, self.collections())

    def get_item(self, key: str) -> Item | None:
        raw = self.raw_item(key)
        if raw is None:
            return None
        return self.item_from_raw(raw, self.children(key))

    def raw_item(self, key: str) -> dict[str, Any] | None:
        raw = self._read(f"item {key}", self.zl.zot.item, key)
        return raw if isinstance(raw, dict) else None

    def children(self, key: str) -> list[dict[str, Any]]:
        kids = self._read(f"children of {key}", self.zl.zot.children, key)
        return [ch for ch in kids or [] if isinstance(ch, dict)]

    def export_pdf(self, item: Item, dest: Path) -> Path | None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        for ch in self.children(item.key):
            data = ch.get("data") or {}
            if not is_pdf_attachment(data):
                continue
            key = ch.get("key")
            if not key:
                continue
            try:
                locate = getattr(self.zl, "file_path", None)
                path = locate(key) if callable(locate) else None
                if path is not None and path.is_file():
                    # Same disk: copy the file Zotero pointed at, not a download of it.
                    shutil.copyfile(path, dest)
                    return dest
                self.zl.zot.dump(key, dest.name, str(dest.parent))
            except Exception:
                # A row whose bytes never arrived (a ghost) fails here.
                return None
            dumped = dest.parent / dest.name
            if dumped.exists():
                if dumped != dest:
                    dumped.replace(dest)
                return dest
        return None

    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None:
        self._ensure_write()
        mapping = {
            "doi": "DOI",
            "title": "title",
            "date": "date",
            "publicationTitle": "publicationTitle",
            "bookTitle": "bookTitle",
            "seriesTitle": "seriesTitle",
            "pages": "pages",
        }
        raw = self.zl.zot.item(item_key)
        data = raw["data"]
        for name, value in fields.items():
            data[mapping.get(name, name)] = value
        self.zl.zot.update_item(raw)

    def relate_items(self, left_key: str, right_key: str) -> None:
        """Record ``dc:relation`` both ways so the preprint stays a version of the work."""
        self._ensure_write()
        self._add_relation(left_key, right_key)
        self._add_relation(right_key, left_key)

    def _add_relation(self, item_key: str, other_key: str) -> None:
        raw = self.zl.zot.item(item_key)
        data = raw["data"]
        relations = data.setdefault("relations", {})
        uri = f"http://zotero.org/users/0/items/{other_key}"
        current = relations.get("dc:relation")
        if current is None or current == "":
            relations["dc:relation"] = uri
        elif isinstance(current, list):
            if uri not in current:
                current.append(uri)
        elif current != uri:
            relations["dc:relation"] = [current, uri]
        self.zl.zot.update_item(raw)

    def _delete_zotero_item(self, item_key: str) -> None:
        """Trash one Zotero item via the local write API (Zotero 10+)."""
        raw = self.zl.zot.item(item_key)
        self.zl.zot.delete_item(raw)

    def trash_item(self, item_key: str) -> None:
        """Move a parent item to the Zotero trash. Does not delete files under out/."""
        self._ensure_write()
        self._delete_zotero_item(item_key)

    def trash_note(self, note_key: str, *, parent_key: str = "") -> None:
        """Trash a child or standalone note. Refuses parent items and attachments."""
        del parent_key
        self._ensure_write()
        raw = self.zl.zot.item(note_key)
        data = raw.get("data") or {}
        if data.get("itemType") != "note":
            raise LibraryError(
                f"{note_key} is a {data.get('itemType') or 'item'}, not a note."
            )
        self.zl.zot.delete_item(raw)

    def preview_merge(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        """What ``merge_into`` would copy. Empty when either item is missing."""
        from .dedupe import merge_parent_patch, plan_child_moves

        keep_raw = self.raw_item(keep_key)
        drop_raw = self.raw_item(drop_key)
        if not keep_raw or not drop_raw:
            return {"drop": drop_key, "fields": [], "move": []}
        keep_kids = self.children(keep_key)
        drop_kids = self.children(drop_key)
        patch = merge_parent_patch(
            keep_raw.get("data") or {}, drop_raw.get("data") or {}
        )
        moves = plan_child_moves(
            keep_kids, drop_kids, self._annotation_counts(keep_kids + drop_kids)
        )
        return {
            "drop": drop_key,
            "fields": sorted(patch["fields"]),
            "move": moves,
        }

    def merge_into(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        """Move children and better fields onto ``keep_key``, then trash ``drop_key``.

        A failed child update leaves the donor in place. Does not touch ``out/``.
        """
        from .dedupe import merge_parent_patch, plan_child_moves

        self._ensure_write()
        keep_raw = self.zl.zot.item(keep_key)
        drop_raw = self.zl.zot.item(drop_key)
        keep_kids = self.children(keep_key)
        drop_kids = self.children(drop_key)
        moves = plan_child_moves(
            keep_kids, drop_kids, self._annotation_counts(keep_kids + drop_kids)
        )
        moved: list[str] = []
        trashed_children: list[str] = []
        for move in moves:
            raw = self.zl.zot.item(move["key"])
            if move["action"] == "reparent":
                raw["data"]["parentItem"] = keep_key
                self.zl.zot.update_item(raw)
                moved.append(move["key"])
            elif move["action"] == "trash":
                self._delete_zotero_item(move["key"])
                trashed_children.append(move["key"])
            else:
                continue
        patch = merge_parent_patch(
            keep_raw.get("data") or {}, drop_raw.get("data") or {}
        )
        fresh = self.zl.zot.item(keep_key)
        data = fresh["data"]
        for name, value in patch["fields"].items():
            data[name] = value
        if patch["collections"] is not None:
            data["collections"] = patch["collections"]
        if patch["tags"] is not None:
            data["tags"] = patch["tags"]
        if patch["relations"] is not None:
            data["relations"] = patch["relations"]
        previous_added = data.get("dateAdded")
        if patch["date_added"]:
            data["dateAdded"] = patch["date_added"]
        try:
            self.zl.zot.update_item(fresh)
        except Exception:
            if patch["date_added"] and data.get("dateAdded") == patch["date_added"]:
                if previous_added is None:
                    data.pop("dateAdded", None)
                else:
                    data["dateAdded"] = previous_added
                self.zl.zot.update_item(fresh)
            else:
                raise
        self.trash_item(drop_key)
        return {
            "moved": moved,
            "fields": sorted(patch["fields"]),
            "trashed_children": trashed_children,
        }

    def _annotation_counts(self, children: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for child in children:
            data = child.get("data") or {}
            if data.get("itemType") != "attachment":
                continue
            key = str(child.get("key") or data.get("key") or "")
            if not key:
                continue
            counts[key] = sum(
                1
                for note in self.children(key)
                if (note.get("data") or {}).get("itemType") == "annotation"
            )
        return counts

    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]:
        want = tag.strip().lower()
        out: list[str] = []
        for ch in self.children(item_key):
            data = ch.get("data") or {}
            if data.get("itemType") != "note":
                continue
            tags = [t.get("tag", "").lower() for t in data.get("tags") or []]
            if want in tags:
                key = ch.get("key")
                if key:
                    out.append(key)
        return out

    def read_child_note(self, item_key: str, tag: str) -> str | None:
        keys = self.find_child_note_keys(item_key, tag)
        if not keys:
            return None
        raw = self.raw_item(keys[0])
        if raw is None:
            return None
        return str((raw.get("data") or {}).get("note") or "") or None

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        self._ensure_write()
        existing = self.find_child_note_keys(item_key, tag)
        if existing:
            key = existing[0]
            raw = self.zl.zot.item(key)
            raw["data"]["note"] = html
            self.zl.zot.update_item(raw)
            return key
        # item_template() hits /items/new, which the local API does not serve.
        payload = note_payload(html, tag, item_key)
        try:
            created = self.zl.zot.create_items([payload])
        except Exception as exc:
            raise LibraryError(f"Zotero did not create note: {exc}") from exc
        key = created_item_key(created)
        if not key:
            failed = ""
            if isinstance(created, dict):
                failed = str(created.get("failed") or created.get("failure") or "")
            raise LibraryError(
                f"Zotero did not create note{': ' + failed if failed else ''}"
            )
        return key

    def replace_prefixed_tag(self, item_key: str, prefix: str, tag: str) -> None:
        """Replace parent tags that start with ``prefix``. Other tags stay."""
        self._ensure_write()
        raw = self.zl.zot.item(item_key)
        data = raw.setdefault("data", {})
        want = prefix.strip().lower()
        kept: list[dict[str, str]] = []
        for row in data.get("tags") or []:
            text = str(row.get("tag") or "") if isinstance(row, dict) else str(row)
            if text.strip().lower().startswith(want):
                continue
            kept.append({"tag": text} if text else row)
        kept.append({"tag": tag})
        data["tags"] = [row for row in kept if row.get("tag")]
        self.zl.zot.update_item(raw)

    def find_collection_note_keys(self, collection_key: str, tag: str) -> list[str]:
        """Top-level notes in a collection that carry ``tag``.

        ``items_in_scope`` skips notes, so a report note never enters run/lint/gaps.
        """
        want = tag.strip().lower()
        out: list[str] = []
        items = self._read(
            f"collection {collection_key}",
            lambda: self.zl.zot.everything(
                self.zl.zot.collection_items_top(collection_key)
            ),
        )
        for it in items or []:
            data = it.get("data") or {}
            if data.get("itemType") != "note" or data.get("parentItem"):
                continue
            tags = [t.get("tag", "").lower() for t in data.get("tags") or []]
            if want in tags:
                key = it.get("key")
                if key:
                    out.append(key)
        return out

    def create_or_update_collection_note(
        self, collection_key: str, html: str, tags: list[str]
    ) -> str:
        """Create or update a standalone note. The last tag is the idempotency key."""
        self._ensure_write()
        lookup = tags[-1] if tags else "paperful-report"
        existing = self.find_collection_note_keys(collection_key, lookup)
        if existing:
            key = existing[0]
            raw = self.zl.zot.item(key)
            raw["data"]["note"] = html
            raw["data"]["tags"] = [{"tag": tag} for tag in tags]
            self.zl.zot.update_item(raw)
            return key
        payload = collection_note_payload(html, tags, collection_key)
        try:
            created = self.zl.zot.create_items([payload])
        except Exception as exc:
            raise LibraryError(f"Zotero did not create note: {exc}") from exc
        key = created_item_key(created)
        if not key:
            failed = ""
            if isinstance(created, dict):
                failed = str(created.get("failed") or created.get("failure") or "")
            raise LibraryError(
                f"Zotero did not create note{': ' + failed if failed else ''}"
            )
        return key
