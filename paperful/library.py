"""Reference-manager adapters. Core work stays on disk; managers only read/write."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .attach import AttachResult, Attacher
from .config import Config
from .zot import Collection, Item, ZoteroLocal, is_pdf_attachment


class LibraryError(Exception):
    pass


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
    def trash_item(self, item_key: str) -> None: ...
    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]: ...
    def read_child_note(self, item_key: str, tag: str) -> str | None: ...
    def create_or_update_note(
        self, item_key: str, html: str, tag: str
    ) -> str: ...
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
                raise LibraryError(f"Zotero did not return a key for collection {sofar}")
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

    def get_item(self, key: str) -> Item | None:
        from .zot import item_from_json

        try:
            raw = self.zl.zot.item(key)
        except Exception:
            return None
        cols = self.collections()
        has_pdf = False
        has_linked = False
        try:
            for ch in self.zl.zot.children(key):
                data = ch.get("data") or {}
                if is_pdf_attachment(data):
                    has_pdf = True
                    if (data.get("linkMode") or "") == "linked_url":
                        has_linked = True
        except Exception:
            pass
        return item_from_json(
            raw, cols, None, has_pdf=has_pdf, has_linked_url=has_linked
        )

    def raw_item(self, key: str) -> dict[str, Any] | None:
        try:
            raw = self.zl.zot.item(key)
        except Exception:
            return None
        return raw if isinstance(raw, dict) else None

    def children(self, key: str) -> list[dict[str, Any]]:
        try:
            kids = self.zl.zot.children(key)
        except Exception:
            return []
        return [ch for ch in kids if isinstance(ch, dict)]

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

    def trash_item(self, item_key: str) -> None:
        """Move a parent item to the Zotero trash. Does not delete files under out/."""
        self._ensure_write()
        raw = self.zl.zot.item(item_key)
        raw["data"]["deleted"] = True
        self.zl.zot.update_item(raw)

    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]:
        want = tag.strip().lower()
        out: list[str] = []
        try:
            children = self.zl.zot.children(item_key)
        except Exception:
            return out
        for ch in children:
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
        try:
            raw = self.zl.zot.item(keys[0])
        except Exception:
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

    def find_collection_note_keys(self, collection_key: str, tag: str) -> list[str]:
        """Top-level notes in a collection that carry ``tag``.

        ``items_in_scope`` skips notes, so a report note never enters run/lint/gaps.
        """
        want = tag.strip().lower()
        out: list[str] = []
        try:
            items = self.zl.zot.everything(
                self.zl.zot.collection_items_top(collection_key)
            )
        except Exception:
            return out
        for it in items:
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
