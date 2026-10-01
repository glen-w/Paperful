"""The library as commands see it: read from the mirror, write to the manager.

``open_library`` refreshes ``out/`` from the manager when it can be reached,
then hands back a backend whose reads never leave this machine. A manager
that is closed costs write-back, not the read work. See
``docs/architecture.md`` (Mirror first).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .attach import AttachResult
from .config import Config
from .library import (
    LibraryBackend,
    LibraryError,
    get_backend,
    mirrored,
)
from .mirror import (
    GONE_STATES,
    item_from_record,
    iter_item_dirs,
    library_state,
    load_record,
    mirror_index,
    pdf_for,
)
from .store import is_item_dirname, load_json, record_path
from .zot import (
    Collection,
    Item,
    build_collection_tree,
    items_without_stored_pdf,
    linked_url_only_count,
    resolve_collection_in,
    subtree_keys_in,
)


class MirrorCatalogue:
    """The read half of ``LibraryBackend``, served from ``out/``. No requests."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self._collections: dict[str, Collection] | None = None

    # ---- state ------------------------------------------------------------
    def state(self) -> dict[str, Any] | None:
        from .sync import sync_state

        return sync_state(self.out_dir)

    def usable(self) -> bool:
        """There is something here to work from."""
        if self.state() is not None or (self.out_dir / "_collections.json").is_file():
            return True
        return next(iter_item_dirs(self.out_dir), None) is not None

    def age_line(self) -> str:
        state = self.state()
        if state and state.get("synced_at"):
            return f"the mirror as of {state['synced_at']}"
        return "the mirror (never refreshed with paperful sync)"

    # ---- collections --------------------------------------------------------
    def collections(self) -> dict[str, Collection]:
        if self._collections is None:
            body = load_json(self.out_dir / "_collections.json") or {}
            rows = [
                {
                    "data": {
                        "key": row.get("key"),
                        "name": row.get("name") or "",
                        "parentCollection": row.get("parent") or False,
                    }
                }
                for row in body.get("collections") or []
                if isinstance(row, dict) and row.get("key")
            ]
            self._collections = build_collection_tree(rows)
        return self._collections

    def forget(self) -> None:
        """Drop what was read from disk. Call after the mirror was refreshed."""
        self._collections = None

    def resolve_collection(self, spec: str) -> Collection:
        return resolve_collection_in(self.collections(), spec)

    def subtree_keys(self, root: Collection) -> list[str]:
        return subtree_keys_in(self.collections(), root)

    # ---- items ----------------------------------------------------------------
    def _folders(self, collection_keys: list[str] | None) -> list[Path]:
        if collection_keys is None:
            return list(iter_item_dirs(self.out_dir))
        cols = self.collections()
        found: list[Path] = []
        for key in collection_keys:
            col = cols.get(key)
            folder = self.out_dir / col.path if col is not None else None
            if folder is None or not folder.is_dir():
                continue
            found.extend(
                sorted(
                    d for d in folder.iterdir() if d.is_dir() and is_item_dirname(d.name)
                )
            )
        return found

    def items_in_scope(
        self,
        collection_keys: list[str] | None,
        *,
        status: Callable[[str], None] | None = None,
    ) -> list[Item]:
        """Top-level items in the selected collections (or the library). Gone items are left out."""
        if status:
            status("Reading the mirror…")
        selected = None if collection_keys is None else set(collection_keys)
        items: dict[str, Item] = {}
        for folder in self._folders(collection_keys):
            record = load_json(record_path(folder))
            if record is None or library_state(record) in GONE_STATES:
                continue
            item = item_from_record(record, folder, self.out_dir, selected=selected)
            if item is not None and item.key not in items:
                items[item.key] = item
        rows = list(items.values())
        rows.sort(
            key=lambda i: (
                i.collection_paths[0] if i.collection_paths else "~",
                i.label.lower(),
            )
        )
        if status:
            status(f"Loaded {len(rows)} parent items")
        return rows

    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]:
        return items_without_stored_pdf(
            self.items_in_scope(collection_keys), upgrade_linked=upgrade_linked
        )

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        return linked_url_only_count(
            self.items_in_scope(collection_keys),
            skip_empty_paths=collection_keys is not None,
        )

    def collection_counts(self) -> dict[str, tuple[int, int]]:
        """Per collection key: (items, items with no stored PDF), counting subcollections."""
        cols = self.collections()
        direct: dict[str, dict[str, bool]] = {key: {} for key in cols}
        by_path = {col.path: key for key, col in cols.items()}
        for folder in iter_item_dirs(self.out_dir):
            key = by_path.get(folder.parent.relative_to(self.out_dir).as_posix())
            if key is None:
                continue
            record = load_json(record_path(folder))
            if record is None or library_state(record) in GONE_STATES:
                continue
            item = item_from_record(record, folder, self.out_dir)
            if item is not None:
                direct[key][item.key] = item.has_pdf
        counts: dict[str, tuple[int, int]] = {}
        for key, col in cols.items():
            seen: dict[str, bool] = {}
            for sub in subtree_keys_in(cols, col):
                seen.update(direct.get(sub, {}))
            counts[key] = (len(seen), sum(1 for has in seen.values() if not has))
        return counts

    def _record(self, key: str) -> tuple[dict[str, Any], Path] | None:
        for folder in mirror_index(self.out_dir).dirs(key):
            record = load_json(record_path(folder))
            if record is not None:
                return record, folder
        return None

    def get_item(self, key: str) -> Item | None:
        found = self._record(key)
        if found is None or library_state(found[0]) in GONE_STATES:
            return None
        return item_from_record(found[0], found[1], self.out_dir)

    def raw_item(self, key: str) -> dict[str, Any] | None:
        """The manager's payload for ``key``, rebuilt from the record."""
        record = load_record(self.out_dir, key)
        if record is None:
            return None
        fields = record.get("fields")
        data: dict[str, Any] = dict(fields) if isinstance(fields, dict) else {}
        data.update(
            {
                "key": key,
                "itemType": record.get("item_type") or "document",
                "title": record.get("title") or "",
                "creators": record.get("creators") or [],
                "abstractNote": record.get("abstract") or "",
                "date": record.get("date") or "",
                "url": record.get("url") or "",
                "extra": record.get("extra") or "",
                "publicationTitle": record.get("publication_title") or "",
                "tags": list(record.get("tags") or []),
                "relations": dict(record.get("relations") or {}),
                "collections": [
                    row["key"]
                    for row in record.get("collections") or []
                    if isinstance(row, dict) and row.get("key")
                ],
                "dateAdded": record.get("date_added") or "",
                "dateModified": record.get("date_modified") or "",
            }
        )
        if "DOI" not in data and record.get("doi_source") == "field":
            data["DOI"] = record.get("library_doi") or record.get("doi") or ""
        return {"key": key, "version": record.get("version"), "data": data, "meta": {}}

    def children(self, key: str) -> list[dict[str, Any]]:
        """Attachment and note rows for ``key``, in the manager's shape."""
        found = self._record(key)
        if found is None:
            return []
        record, folder = found
        rows: list[dict[str, Any]] = []
        for row in record.get("attachments") or []:
            if not isinstance(row, dict) or not row.get("key"):
                continue
            data = {k: v for k, v in row.items() if k not in {"key", "origin"}}
            data.update({"itemType": "attachment", "parentItem": key})
            rows.append({"key": row["key"], "data": data})
        for note in record.get("notes") or []:
            if not isinstance(note, dict) or not note.get("key"):
                continue
            path = folder / "notes" / str(note.get("file") or "")
            html = path.read_text(encoding="utf-8") if path.is_file() else ""
            tags = note.get("tags") or ([note["tag"]] if note.get("tag") else [])
            rows.append(
                {
                    "key": note["key"],
                    "data": {
                        "itemType": "note",
                        "parentItem": key,
                        "note": html,
                        "tags": [{"tag": str(tag)} for tag in tags],
                    },
                }
            )
        return rows

    def annotation_counts(self, key: str) -> dict[str, int]:
        """Annotations per attachment key, from ``annotations.json``."""
        found = self._record(key)
        counts: dict[str, int] = {}
        if found is None:
            return counts
        body = load_json(found[1] / "annotations.json") or {}
        for row in body.get("annotations") or []:
            parent = str((row or {}).get("parentItem") or "")
            if parent:
                counts[parent] = counts.get(parent, 0) + 1
        return counts

    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]:
        want = tag.strip().lower()
        out: list[str] = []
        for ch in self.children(item_key):
            data = ch["data"]
            if data.get("itemType") != "note":
                continue
            if want in [t.get("tag", "").lower() for t in data.get("tags") or []]:
                out.append(ch["key"])
        return out

    def read_child_note(self, item_key: str, tag: str) -> str | None:
        keys = self.find_child_note_keys(item_key, tag)
        if not keys:
            return None
        for ch in self.children(item_key):
            if ch["key"] == keys[0]:
                return str(ch["data"].get("note") or "") or None
        return None


class MirrorFirstBackend:
    """Reads come from the mirror. Writes go to the manager, through its write-through.

    ``live`` is ``None`` when the manager is not reachable: reads still work,
    writes raise ``LibraryError``.
    """

    def __init__(self, cfg: Config, catalogue: MirrorCatalogue, live: Any | None):
        self._cfg = cfg
        self.catalogue = catalogue
        self.live = live

    def __getattr__(self, name: str) -> Any:
        # Optional adapter calls (probed with getattr) belong to the manager.
        live = self.__dict__.get("live")
        if name.startswith("__") or live is None:
            raise AttributeError(name)
        return getattr(live, name)

    def _need_live(self) -> Any:
        if self.live is None:
            manager = (self._cfg.manager or "zotero").strip().lower()
            raise LibraryError(
                f"{manager} is not reachable, so nothing can be written to it. "
                "The mirror was read; start the manager and run the command again."
            )
        return self.live

    # ---- reads: the mirror --------------------------------------------------
    def collections(self) -> dict[str, Collection]:
        return self.catalogue.collections()

    def collection_counts(self) -> dict[str, tuple[int, int]]:
        return self.catalogue.collection_counts()

    def resolve_collection(self, spec: str) -> Collection:
        return self.catalogue.resolve_collection(spec)

    def subtree_keys(self, root: Collection) -> list[str]:
        return self.catalogue.subtree_keys(root)

    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]:
        return self.catalogue.items_lacking_pdf(collection_keys, upgrade_linked)

    def items_in_scope(
        self,
        collection_keys: list[str] | None,
        *,
        status: Callable[[str], None] | None = None,
    ) -> list[Item]:
        return self.catalogue.items_in_scope(collection_keys, status=status)

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        return self.catalogue.count_linked_url_only(collection_keys)

    def get_item(self, key: str) -> Item | None:
        return self.catalogue.get_item(key)

    def raw_item(self, key: str) -> dict[str, Any] | None:
        return self.catalogue.raw_item(key)

    def children(self, key: str) -> list[dict[str, Any]]:
        return self.catalogue.children(key)

    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]:
        return self.catalogue.find_child_note_keys(item_key, tag)

    def read_child_note(self, item_key: str, tag: str) -> str | None:
        return self.catalogue.read_child_note(item_key, tag)

    def preview_merge(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        """What ``merge_into`` would copy, worked out from the mirror."""
        from .dedupe import merge_parent_patch, plan_child_moves

        keep_raw = self.catalogue.raw_item(keep_key)
        drop_raw = self.catalogue.raw_item(drop_key)
        if not keep_raw or not drop_raw:
            return {"drop": drop_key, "fields": [], "move": []}
        counts = self.catalogue.annotation_counts(keep_key)
        counts.update(self.catalogue.annotation_counts(drop_key))
        patch = merge_parent_patch(keep_raw["data"], drop_raw["data"])
        moves = plan_child_moves(
            self.catalogue.children(keep_key), self.catalogue.children(drop_key), counts
        )
        return {"drop": drop_key, "fields": sorted(patch["fields"]), "move": moves}

    def export_pdf(self, item: Item, dest: Path) -> Path | None:
        """A copy of the item's PDF at ``dest``: from the mirror, else from the manager."""
        local = pdf_for(self._cfg.out_dir, item)
        if local is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if local.resolve() != dest.resolve():
                shutil.copyfile(local, dest)
            return dest
        if self.live is None:
            return None
        return self.live.export_pdf(item, dest)

    # ---- the manager ---------------------------------------------------------
    def ping(self) -> dict[str, Any]:
        if self.live is None:
            return {"offline": True, "supports_write": False}
        return self.live.ping()

    def supports_write(self) -> bool:
        return self.live is not None and bool(self.live.supports_write())

    @property
    def library_type(self) -> str:
        return str(getattr(self.live, "library_type", "user"))

    @property
    def unrefreshed(self) -> list[str]:
        return list(getattr(self.live, "unrefreshed", None) or [])

    def flush_writes(self) -> Path | None:
        if self.live is None:
            return None
        fn = getattr(self.live, "flush_writes", None)
        return fn() if callable(fn) else None

    def find_collection_note_keys(self, collection_key: str, tag: str) -> list[str]:
        # Standalone notes are not in the mirror.
        return self._need_live().find_collection_note_keys(collection_key, tag)

    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None:
        self._need_live().apply_patch(item_key, fields)

    def relate_items(self, left_key: str, right_key: str) -> None:
        self._need_live().relate_items(left_key, right_key)

    def trash_item(self, item_key: str) -> None:
        self._need_live().trash_item(item_key)

    def merge_into(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        return self._need_live().merge_into(keep_key, drop_key)

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        return self._need_live().create_or_update_note(item_key, html, tag)

    def replace_prefixed_tag(self, item_key: str, prefix: str, tag: str) -> None:
        self._need_live().replace_prefixed_tag(item_key, prefix, tag)

    def create_or_update_collection_note(
        self, collection_key: str, html: str, tags: list[str]
    ) -> str:
        return self._need_live().create_or_update_collection_note(
            collection_key, html, tags
        )

    def ensure_collection_path(self, path: str) -> str:
        key = self._need_live().ensure_collection_path(path)
        self.catalogue.forget()
        return key

    def create_parent(self, data: dict[str, Any]) -> str:
        return self._need_live().create_parent(data)

    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult:
        return self._need_live().attach(item_key, pdf_path, title, note=note)


def has_change_feed(backend: Any) -> bool:
    """The manager can say what changed, so the mirror can stand in for it."""
    return callable(getattr(backend, "changes", None))


def open_library(
    cfg: Config,
    *,
    live: Any | None = None,
    offline: bool = False,
    status: Callable[[str], None] | None = None,
) -> LibraryBackend:
    """The library for a command: the mirror, refreshed when the manager answers.

    ``live`` is a manager backend that already answered a ping; ``None`` means
    try to reach one. ``offline`` skips the manager altogether. Raises
    ``LibraryError`` when there is neither a manager nor a mirror.
    """
    from .sync import run_sync

    say = status or (lambda _msg: None)
    reason = "offline was asked for"
    if offline:
        live = None
    elif live is None:
        try:
            live = get_backend(cfg)
            live.ping()
        except Exception as exc:
            live, reason = None, str(exc)
    if live is not None:
        live = mirrored(cfg, live)
        if not has_change_feed(live):
            # No change feed on this manager: its reads stay with the manager.
            return live
    catalogue = MirrorCatalogue(cfg.out_dir)
    if live is None:
        if not catalogue.usable():
            raise LibraryError(reason)
        say(f"Library not reachable ({reason}). Working from {catalogue.age_line()}.")
        return MirrorFirstBackend(cfg, catalogue, None)  # type: ignore[return-value]
    if cfg.mirror_refresh == "auto":
        if catalogue.state() is None:
            say("First refresh of the mirror: reading the whole library once.")
        try:
            run_sync(cfg, live, backfill=False, status=status)
        except LibraryError as exc:
            if not catalogue.usable():
                raise
            say(f"Could not refresh ({exc}). Working from {catalogue.age_line()}.")
    elif not catalogue.usable():
        raise LibraryError("The mirror is empty. Run paperful sync.")
    return MirrorFirstBackend(cfg, catalogue, live)  # type: ignore[return-value]
