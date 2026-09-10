"""Reference-manager adapters. Core work stays on disk; managers only read/write."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .attach import Attacher
from .config import Config
from .zot import Collection, Item, ZoteroLocal, is_pdf_attachment


class LibraryError(Exception):
    pass


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
    def export_pdf(self, item: Item, dest: Path) -> Path | None: ...
    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None: ...
    def supports_write(self) -> bool: ...


def get_backend(cfg: Config, zl: ZoteroLocal | None = None) -> LibraryBackend:
    manager = (cfg.manager or "zotero").strip().lower()
    if manager == "mendeley":
        raise LibraryError('Mendeley is not implemented yet. Set manager = "zotero".')
    if manager != "zotero":
        raise LibraryError(
            f"Unknown manager {manager!r}. Known: zotero (mendeley later)."
        )
    return ZoteroBackend(cfg, zl)


class ZoteroBackend:
    """Zotero local API adapter. PDF extract/lint never call this except to export files."""

    def __init__(self, cfg: Config, zl: ZoteroLocal | None = None):
        self.cfg = cfg
        self.zl = zl or ZoteroLocal()
        self._attacher: Attacher | None = None

    def ping(self) -> dict[str, Any]:
        return self.zl.ping()

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

    def items_in_scope(self, collection_keys: list[str] | None) -> list[Item]:
        return self.zl.items_in_scope(collection_keys)

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        return self.zl.count_linked_url_only(collection_keys)

    def supports_write(self) -> bool:
        return bool(self.ping().get("supports_write"))

    def _ensure_write(self) -> None:
        if self._attacher is None:
            self._attacher = Attacher(self.cfg, self.zl)
        if not self._attacher.supports_write():
            raise LibraryError(
                "Zotero local API has no write support (needs Zotero 10+)"
            )
        if not self.zl.zot.local_api_key:
            if not self._attacher.authorize():
                raise LibraryError("write authorisation denied in Zotero")

    def export_pdf(self, item: Item, dest: Path) -> Path | None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            children = self.zl.zot.children(item.key)
        except Exception:
            return None
        for ch in children:
            data = ch.get("data") or {}
            if not is_pdf_attachment(data):
                continue
            key = ch.get("key")
            if not key:
                continue
            try:
                self.zl.zot.dump(key, dest.name, str(dest.parent))
            except Exception:
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
        }
        raw = self.zl.zot.item(item_key)
        data = raw["data"]
        for name, value in fields.items():
            data[mapping.get(name, name)] = value
        self.zl.zot.update_item(raw)
