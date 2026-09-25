"""EndNote desktop adapter: read SQLite, write an official XML+PDF import bundle.

Clarivate has no public API. Reading ``<Library>.Data/sdb/sdb.eni`` (copy if
locked) is the live catalogue. Writes never touch that database: they stage
``state/endnote-import/<stamp>/`` for File → Import inside EndNote.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import struct
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attach import AttachResult
from .config import Config
from .interop.endnote_xml import records_to_endnote_xml
from .interop.types import endnote_db_to_zotero, endnote_to_zotero, zotero_to_endnote
from .library import LibraryError
from .resolve import extract_arxiv_id, extract_doi, extract_pmid, normalize_doi
from .zot import UNCOLLECTED, Collection, Item, parse_year

_PATH_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def library_paths(enl: Path) -> tuple[Path, Path, Path]:
    """Return (.enl, .Data dir, sdb.eni). Accepts either the .enl or the .Data folder."""
    path = enl.expanduser()
    if path.suffix.lower() == ".enl":
        data = path.with_suffix(".Data")
        if not data.is_dir():
            data = path.parent / (path.stem + ".Data")
        enl_path = path
    elif path.name.endswith(".Data") or path.suffix.lower() == ".data":
        data = path
        enl_path = path.with_suffix(".enl")
        if not enl_path.is_file():
            enl_path = path.parent / (path.name[: -len(".Data")] + ".enl")
    else:
        enl_path = path
        data = path.with_suffix(".Data")
    eni = data / "sdb" / "sdb.eni"
    return enl_path, data, eni


def _prepare_sqlite(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Register EndNote's custom collations so SELECTs do not fail."""
    conn.row_factory = sqlite3.Row

    def _collate(a: object, b: object) -> int:
        sa = "" if a is None else str(a)
        sb = "" if b is None else str(b)
        la, lb = sa.casefold(), sb.casefold()
        return (la > lb) - (la < lb)

    for name in ("ENCI_Base", "ENCIN_Base"):
        try:
            conn.create_collation(name, _collate)
        except sqlite3.Error:
            pass
    return conn


def connect_readonly(eni: Path) -> sqlite3.Connection:
    """Open sdb.eni read-only. If EndNote holds a lock, copy to a temp file first."""
    if not eni.is_file():
        raise LibraryError(f"EndNote database not found: {eni}")
    uri = f"file:{eni}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        _prepare_sqlite(conn)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except sqlite3.OperationalError:
        tmp = Path(tempfile.mkdtemp(prefix="paperful-endnote-")) / "sdb.eni"
        shutil.copy2(eni, tmp)
        for suffix in ("-wal", "-shm", "-journal"):
            side = eni.with_name(eni.name + suffix)
            if side.is_file():
                shutil.copy2(side, tmp.parent / side.name)
        conn = sqlite3.connect(str(tmp))
        return _prepare_sqlite(conn)


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(r[0]) for r in rows}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}


def _fetchone(conn: sqlite3.Connection, sql: str, key: str):
    try:
        row = conn.execute(sql, (key,)).fetchone()
    except sqlite3.Error:
        row = None
    if row is None and str(key).isdigit():
        try:
            row = conn.execute(sql, (int(key),)).fetchone()
        except sqlite3.Error:
            row = None
    return row


def _fetchall(conn: sqlite3.Connection, sql: str, key: str):
    try:
        rows = conn.execute(sql, (key,)).fetchall()
    except sqlite3.Error:
        rows = []
    if not rows and str(key).isdigit():
        try:
            rows = conn.execute(sql, (int(key),)).fetchall()
        except sqlite3.Error:
            rows = []
    return rows


class EndNoteBackend:
    """Read the local EndNote library; stage XML bundles for write-back."""

    def __init__(self, cfg: Config, conn: sqlite3.Connection | None = None):
        self.cfg = cfg
        if not cfg.endnote_library:
            raise LibraryError(
                "Set [endnote] library to your .enl file (the matching .Data folder "
                "must sit beside it)."
            )
        self.enl, self.data_dir, self.eni = library_paths(Path(cfg.endnote_library))
        self._conn = conn
        self._own_conn = conn is None
        self._collections: dict[str, Collection] | None = None
        self._members_by_ref: dict[str, list[str]] | None = None
        self._pending: list[dict[str, Any]] = []
        self._pending_by_key: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect_readonly(self.eni)
        return self._conn

    def ping(self) -> dict[str, Any]:
        conn = self._db()
        n = 0
        if "refs" in _tables(conn):
            try:
                n = int(conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0])
            except sqlite3.Error:
                n = 0
        return {
            "library": str(self.enl),
            "data_dir": str(self.data_dir),
            "refs": n,
            "supports_write": True,
            "write_mode": "bundle",
        }

    def supports_write(self) -> bool:
        return True

    def collections(self) -> dict[str, Collection]:
        if self._collections is None:
            self._collections = self._load_groups()
        return self._collections

    def resolve_collection(self, spec: str) -> Collection:
        from .zot import _squash

        cols = self.collections()
        spec_norm = spec.strip().strip("/")
        if spec_norm in cols:
            return cols[spec_norm]
        wanted = _squash(spec_norm)
        for c in cols.values():
            if wanted in (_squash(c.path), _squash(c.raw_path)):
                return c
        matches = [c for c in cols.values() if c.name.lower() == spec_norm.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            paths = ", ".join(sorted(c.path for c in matches))
            raise LookupError(f"Group name '{spec}' is ambiguous; use a path: {paths}")
        raise LookupError(f"No EndNote group matching '{spec}'")

    def subtree_keys(self, root: Collection) -> list[str]:
        cols = self.collections()
        out = [root.key]
        frontier = [root.key]
        while frontier:
            parent = frontier.pop()
            for c in cols.values():
                if c.parent == parent:
                    out.append(c.key)
                    frontier.append(c.key)
        return out

    def collection_counts(self) -> dict[str, tuple[int, int]]:
        items = self.items_in_scope(None)
        by_path: dict[str, list[Item]] = {}
        for it in items:
            for p in it.collection_paths:
                by_path.setdefault(p, []).append(it)
        counts: dict[str, tuple[int, int]] = {}
        for key, col in self.collections().items():
            seen: dict[str, Item] = {}
            for sub in self.subtree_keys(col):
                subcol = self.collections().get(sub)
                if subcol is None:
                    continue
                for it in by_path.get(subcol.path, []):
                    seen[it.key] = it
            missing = sum(1 for it in seen.values() if not it.has_pdf)
            counts[key] = (len(seen), missing)
        return counts

    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]:
        del upgrade_linked
        return [it for it in self.items_in_scope(collection_keys) if not it.has_pdf]

    def items_in_scope(self, collection_keys: list[str] | None) -> list[Item]:
        cols = self.collections()
        selected = set(collection_keys) if collection_keys is not None else None
        items = [_item_from_ref(row, self) for row in self._iter_refs()]
        if selected is not None:
            allowed_paths = {
                cols[k].path for k in selected if k in cols
            }
            items = [
                it
                for it in items
                if any(p in allowed_paths for p in it.collection_paths)
                or (
                    UNCOLLECTED in it.collection_paths
                    and not allowed_paths
                )
            ]
        items.sort(
            key=lambda i: (
                i.collection_paths[0] if i.collection_paths else "~",
                i.label.lower(),
            )
        )
        return items

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        del collection_keys
        return 0

    def get_item(self, key: str) -> Item | None:
        if key in self._pending_by_key:
            return _item_from_pending(self._pending_by_key[key])
        row = self._ref_by_id(key)
        return _item_from_ref(row, self) if row else None

    def raw_item(self, key: str) -> dict[str, Any] | None:
        row = self._ref_by_id(key)
        if row is None:
            rec = self._pending_by_key.get(key)
            return _raw_from_pending(rec) if rec else None
        return _raw_from_ref(row, self)

    def children(self, key: str) -> list[dict[str, Any]]:
        rec = self._pending_by_key.get(key)
        if rec is not None:
            return _children_from_pending(rec)
        row = self._ref_by_id(key)
        if row is None:
            return []
        return _children_from_ref(row, self)

    def export_pdf(self, item: Item, dest: Path) -> Path | None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = self._pdf_for(item.key)
        if src is None or not src.is_file():
            return None
        shutil.copyfile(src, dest)
        return dest

    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult:
        del title, note
        if not pdf_path.is_file():
            return AttachResult(False, reason=f"file missing: {pdf_path}", code="other")
        rec = self._pending_by_key.get(item_key)
        if rec is None:
            rec = self._stage_from_live(item_key)
        rec.setdefault("pdfs", []).append(str(pdf_path))
        return AttachResult(True, attachment_key=pdf_path.name, reason="staged", code="success")

    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None:
        rec = self._pending_by_key.get(item_key) or self._stage_from_live(item_key)
        mapping = {
            "doi": "doi",
            "title": "title",
            "date": "date",
            "publicationTitle": "publication_title",
            "itemType": "item_type",
            "extra": "extra",
        }
        for name, value in fields.items():
            rec[mapping.get(name, name)] = value

    def merge_into(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        raise LibraryError(
            "EndNote cannot merge items through paperful. "
            "dedupe --apply needs Zotero so the PDF and notes stay on one item."
        )

    def relate_items(self, left_key: str, right_key: str) -> None:
        self.create_or_update_note(
            left_key, f"<p>paperful version of {right_key}</p>", "paperful-version"
        )
        self.create_or_update_note(
            right_key, f"<p>paperful version of {left_key}</p>", "paperful-version"
        )

    def trash_item(self, item_key: str) -> None:
        raise LibraryError(
            "EndNote cannot trash items through paperful. Delete in EndNote, or omit "
            "the reference from the next import bundle."
        )

    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]:
        want = tag.strip().lower()
        out: list[str] = []
        for ch in self.children(item_key):
            data = ch.get("data") or {}
            tags = [t.get("tag", "").lower() for t in data.get("tags") or []]
            if want in tags and ch.get("key"):
                out.append(str(ch["key"]))
        return out

    def read_child_note(self, item_key: str, tag: str) -> str | None:
        for ch in self.children(item_key):
            data = ch.get("data") or {}
            tags = [t.get("tag", "").lower() for t in data.get("tags") or []]
            if tag.strip().lower() in tags:
                return str(data.get("note") or "") or None
        return None

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        rec = self._pending_by_key.get(item_key) or self._stage_from_live(item_key)
        notes = rec.setdefault("notes", [])
        for note in notes:
            if isinstance(note, dict) and str(note.get("tag") or "").lower() == tag.lower():
                note["html"] = html
                return str(note.get("file") or tag)
        fname = f"{tag}.html"
        notes.append({"file": fname, "html": html, "tag": tag})
        return fname

    def replace_prefixed_tag(self, item_key: str, prefix: str, tag: str) -> None:
        """Replace keywords that start with ``prefix`` on the staged import record."""
        rec = self._pending_by_key.get(item_key) or self._stage_from_live(item_key)
        want = prefix.strip().lower()
        kept: list[dict[str, str]] = []
        for row in rec.get("tags") or []:
            text = str(row.get("tag") or "") if isinstance(row, dict) else str(row)
            if text.strip().lower().startswith(want):
                continue
            if text:
                kept.append({"tag": text})
        kept.append({"tag": tag})
        rec["tags"] = kept

    def find_collection_note_keys(self, collection_key: str, tag: str) -> list[str]:
        del collection_key, tag
        return []

    def create_or_update_collection_note(
        self, collection_key: str, html: str, tags: list[str]
    ) -> str:
        lookup = tags[-1] if tags else "paperful-report"
        rec = {
            "item_type": "document",
            "title": lookup,
            "creators": [],
            "notes": [{"file": f"{lookup}.html", "html": html, "tag": lookup}],
            "tags": [{"tag": t} for t in tags],
            "collection_paths": [self.collections()[collection_key].path]
            if collection_key in self.collections()
            else [],
            "pdfs": [],
        }
        return self._add_pending(rec)

    def ensure_collection_path(self, path: str) -> str:
        """Groups are not created in EndNote XML; the path is stored as the Label."""
        cols = self.collections()
        found = next((c for c in cols.values() if c.path == path), None)
        if found:
            return found.key
        key = "path:" + path
        name = path.rsplit("/", 1)[-1]
        parent_path = path.rsplit("/", 1)[0] if "/" in path else None
        parent = None
        if parent_path:
            parent = self.ensure_collection_path(parent_path)
        cols[key] = Collection(key=key, name=name, parent=parent, path=path, raw_path=path)
        return key

    def create_parent(self, data: dict[str, Any]) -> str:
        paths = []
        for ck in data.get("collections") or []:
            col = self.collections().get(str(ck))
            if col:
                paths.append(col.path)
            elif str(ck).startswith("path:"):
                paths.append(str(ck)[5:])
            elif "/" in str(ck):
                paths.append(str(ck))
        rec = {
            "item_type": data.get("itemType") or "document",
            "title": data.get("title") or "",
            "creators": data.get("creators") or [],
            "date": data.get("date") or "",
            "year": parse_year(data.get("date")),
            "publication_title": data.get("publicationTitle") or "",
            "doi": data.get("DOI") or "",
            "url": data.get("url") or "",
            "abstract": data.get("abstractNote") or "",
            "extra": data.get("extra") or "",
            "tags": data.get("tags") or [],
            "notes": [],
            "pdfs": [],
            "collection_paths": paths,
            "pmid": extract_pmid(data.get("extra") or ""),
        }
        return self._add_pending(rec)

    def flush_writes(self) -> Path | None:
        if not self._pending:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = self.cfg.state_dir / "endnote-import" / stamp
        pdf_dir = dest / "PDF"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        for rec in self._pending:
            copied: list[str] = []
            for pdf in rec.get("pdfs") or []:
                src = Path(str(pdf))
                if not src.is_file():
                    continue
                target = pdf_dir / src.name
                if not target.exists():
                    shutil.copyfile(src, target)
                rec_uri = f"internal-pdf://{target.name}"
                copied.append(rec_uri)
            rec["pdfs"] = copied or rec.get("pdfs") or []
        xml = records_to_endnote_xml(self._pending, database=self.enl.name or "paperful")
        (dest / "paperful.xml").write_text(xml, encoding="utf-8")
        (dest / "README.txt").write_text(_readme(dest), encoding="utf-8")
        self._pending = []
        self._pending_by_key = {}
        return dest

    def _add_pending(self, rec: dict[str, Any]) -> str:
        self._seq += 1
        key = str(rec.get("item_key") or f"en{self._seq}")
        rec["item_key"] = key
        self._pending.append(rec)
        self._pending_by_key[key] = rec
        return key

    def _stage_from_live(self, item_key: str) -> dict[str, Any]:
        raw = self.raw_item(item_key)
        item = self.get_item(item_key)
        if raw is None or item is None:
            raise LibraryError(f"EndNote item {item_key} not found")
        data = raw.get("data") or {}
        rec = {
            "item_key": item_key,
            "item_type": item.item_type,
            "title": item.title,
            "creators": data.get("creators") or [],
            "date": item.date or "",
            "year": item.year,
            "publication_title": item.publication_title or "",
            "doi": item.doi or "",
            "url": item.url or "",
            "abstract": item.abstract or "",
            "extra": item.extra or "",
            "tags": data.get("tags") or [],
            "notes": [],
            "pdfs": [],
            "collection_paths": [
                p for p in item.collection_paths if p != UNCOLLECTED
            ],
            "pmid": item.pmid,
        }
        pdf = self._pdf_for(item_key)
        if pdf is not None:
            rec["pdfs"].append(str(pdf))
        for ch in self.children(item_key):
            data_ch = ch.get("data") or {}
            if data_ch.get("itemType") == "note" and data_ch.get("note"):
                rec["notes"].append(
                    {
                        "file": f"{ch.get('key') or 'note'}.html",
                        "html": data_ch["note"],
                        "tag": (data_ch.get("tags") or [{}])[0].get("tag")
                        if data_ch.get("tags")
                        else "paperful-imported",
                    }
                )
        self._pending.append(rec)
        self._pending_by_key[item_key] = rec
        return rec

    def _iter_refs(self) -> list[dict[str, Any]]:
        conn = self._db()
        if "refs" not in _tables(conn):
            return []
        cols = _columns(conn, "refs")
        where = ""
        if "trash_state" in cols:
            where = " WHERE trash_state = 0 OR trash_state IS NULL"
        rows = conn.execute(f"SELECT * FROM refs{where}").fetchall()
        return [dict(r) for r in rows]

    def _ref_by_id(self, key: str) -> dict[str, Any] | None:
        conn = self._db()
        if "refs" not in _tables(conn):
            return None
        cols = _columns(conn, "refs")
        id_col = "id" if "id" in cols else ("refs_id" if "refs_id" in cols else None)
        if id_col is None:
            return None
        row = _fetchone(conn, f"SELECT * FROM refs WHERE {id_col} = ?", key)
        return dict(row) if row is not None else None

    def _pdf_for(self, key: str) -> Path | None:
        conn = self._db()
        tables = _tables(conn)
        if "file_res" in tables:
            cols = _columns(conn, "file_res")
            ref_col = "refs_id" if "refs_id" in cols else ("id" if "id" in cols else None)
            path_col = "file_path" if "file_path" in cols else (
                "path" if "path" in cols else None
            )
            if ref_col and path_col:
                rows = _fetchall(
                    conn,
                    f"SELECT * FROM file_res WHERE {ref_col} = ?",
                    key,
                )
                ranked: list[tuple[int, str]] = []
                for row in rows:
                    d = dict(row)
                    stored = d.get(path_col)
                    if not stored:
                        continue
                    ftype = d.get("file_type")
                    prefer = 0 if ftype in (1, 4, "1", "4") else 1
                    ranked.append((prefer, str(stored)))
                ranked.sort(key=lambda x: x[0])
                for _, stored in ranked:
                    found = _resolve_data_file(self.data_dir, stored)
                    if found:
                        return found
        row = self._ref_by_id(key)
        if row is None:
            return None
        for field in ("file_attachments", "urls", "url"):
            text = str(row.get(field) or "")
            m = re.search(r"internal-pdf://([^\s<>]+)", text)
            if m:
                found = _resolve_data_file(self.data_dir, m.group(1))
                if found:
                    return found
        pdf_root = self.data_dir / "PDF"
        if pdf_root.is_dir():
            hits = list(pdf_root.rglob(f"*{key}*.pdf"))
            if hits:
                return hits[0]
        return None

    def _groups_for(self, ref_id: str) -> list[str]:
        cols = self.collections()
        if not cols:
            return [UNCOLLECTED]
        keys = (self._members_by_ref or {}).get(str(ref_id), [])
        paths = [cols[k].path for k in keys if k in cols]
        return paths or [UNCOLLECTED]

    def _load_groups(self) -> dict[str, Collection]:
        conn = self._db()
        tables = _tables(conn)
        self._members_by_ref = {}
        if "groups" not in tables:
            return {}
        cols = _columns(conn, "groups")
        id_col = next((c for c in ("group_id", "id", "gid") if c in cols), None)
        if not id_col:
            return {}
        name_col = next((c for c in ("group_name", "name", "title") if c in cols), None)
        parent_col = next(
            (c for c in ("parent_id", "parent", "group_parent") if c in cols), None
        )
        type_col = next((c for c in ("group_type", "type") if c in cols), None)
        spec_col = "spec" if "spec" in cols else None
        members_col = "members" if "members" in cols else None
        rows = conn.execute("SELECT * FROM groups").fetchall()
        nodes: dict[str, tuple[str, str | None]] = {}
        blobs: dict[str, bytes] = {}
        for r in rows:
            d = dict(r)
            spec = _parse_group_spec(d.get(spec_col) if spec_col else None)
            if spec.get("skip"):
                continue
            if type_col and d.get(type_col) not in (None, 0, 1, "0", "1", 2):
                try:
                    if int(d[type_col]) > 2:
                        continue
                except (TypeError, ValueError):
                    pass
            key = str(d[id_col])
            name = ""
            if name_col:
                name = str(d.get(name_col) or "")
            if not name:
                name = str(spec.get("name") or "")
            if not name:
                name = key
            parent = d.get(parent_col) if parent_col else None
            parent_s = str(parent) if parent not in (None, 0, "0", "") else None
            nodes[key] = (name, parent_s)
            if members_col and d.get(members_col):
                raw = d[members_col]
                blobs[key] = raw if isinstance(raw, bytes) else bytes(raw)
        out: dict[str, Collection] = {}

        def path_of(key: str, depth: int = 0) -> str:
            name, parent = nodes[key]
            seg = _PATH_UNSAFE.sub("_", name).strip() or key
            if parent and parent in nodes and depth < 50:
                return f"{path_of(parent, depth + 1)}/{seg}"
            return seg

        for key, (name, parent) in nodes.items():
            out[key] = Collection(
                key=key,
                name=name,
                parent=parent,
                path=path_of(key),
                raw_path=path_of(key),
            )
        member_table = next(
            (
                n
                for n in ("group_refs", "refs_groups", "group_items", "groups_refs")
                if n in tables
            ),
            None,
        )
        if member_table:
            mcols = _columns(conn, member_table)
            ref_col = next(
                (c for c in ("refs_id", "ref_id", "id", "record_id") if c in mcols),
                None,
            )
            group_col = next(
                (c for c in ("group_id", "groups_id", "gid") if c in mcols), None
            )
            if ref_col and group_col:
                try:
                    mrows = conn.execute(
                        f"SELECT {ref_col}, {group_col} FROM {member_table}"
                    ).fetchall()
                except sqlite3.Error:
                    mrows = []
                for mrow in mrows:
                    rid, gid = str(mrow[0]), str(mrow[1])
                    if gid in out:
                        self._members_by_ref.setdefault(rid, []).append(gid)
        elif blobs:
            for gid, blob in blobs.items():
                if gid not in out:
                    continue
                for rid in _endnote_member_ids(blob):
                    self._members_by_ref.setdefault(str(rid), []).append(gid)
        return out


def _parse_group_spec(blob: object) -> dict[str, Any]:
    """Read a groups.spec XML blob. Skip EndNote online-search groups (TYPE;6)."""
    if blob in (None, "", b""):
        return {}
    if isinstance(blob, bytes):
        text = blob.decode("utf-8", errors="replace")
    else:
        text = str(blob)
    if "TYPE;6" in text:
        return {"skip": True}
    if "<" not in text:
        name = text.strip()
        return {"name": name} if name else {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    name = None
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag == "name" and el.text and not name:
            name = el.text.strip()
        if el.text and "TYPE;6" in el.text:
            return {"skip": True}
    return {"name": name} if name else {}


def _endnote_member_ids(blob: bytes) -> list[int]:
    """Decode groups.members as version + count + packed uint32 ids."""
    if not blob or len(blob) < 8:
        return []
    for endian in (">", "<"):
        _ver, count = struct.unpack_from(f"{endian}II", blob, 0)
        if count < 0 or count > 1_000_000:
            continue
        need = 8 + 4 * count
        if need != len(blob) and not (count == 0 and len(blob) == 8):
            continue
        if count == 0:
            return []
        ids = list(struct.unpack_from(f"{endian}{count}I", blob, 8))
        return [i for i in ids if i > 0]
    return []


def _resolve_data_file(data_dir: Path, stored: str) -> Path | None:
    text = stored.replace("internal-pdf://", "").replace("file://", "").lstrip("/")
    candidates = [
        data_dir / text,
        data_dir / "PDF" / text,
        data_dir / "PDF" / Path(text).name,
        Path(text),
    ]
    for c in candidates:
        if c.is_file():
            return c
    name = Path(text).name
    pdf_root = data_dir / "PDF"
    if pdf_root.is_dir() and name:
        hits = list(pdf_root.rglob(name))
        if hits:
            return hits[0]
    return None


def _ref_get(row: dict[str, Any], *names: str) -> Any:
    lower = {k.lower(): k for k in row}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        key = lower.get(name.lower())
        if key is not None and row[key] not in (None, ""):
            return row[key]
    return None


def _split_authors(raw: str) -> list[dict[str, str]]:
    text = raw.replace("\u0000", "\n")
    parts = re.split(r"[\r\n/;]+|//", text)
    out: list[dict[str, str]] = []
    for part in parts:
        name = part.strip().strip("*")
        if not name:
            continue
        if "," in name:
            last, first = [p.strip() for p in name.split(",", 1)]
        else:
            bits = name.split()
            last, first = (bits[-1], " ".join(bits[:-1])) if len(bits) >= 2 else (name, "")
        out.append({"creatorType": "author", "lastName": last, "firstName": first})
    return out


def _item_from_ref(row: dict[str, Any], backend: EndNoteBackend) -> Item:
    ref_id = str(_ref_get(row, "id", "refs_id") or "")
    title = str(_ref_get(row, "title") or "").strip() or "(untitled)"
    year = _ref_get(row, "year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    if not isinstance(year, int):
        year = parse_year(str(year) if year else None)
    authors = _split_authors(str(_ref_get(row, "author", "authors") or ""))
    first = authors[0]["lastName"] if authors else None
    doi = normalize_doi(
        str(
            _ref_get(
                row,
                "electronic_resource_number",
                "electronic_resource_num",
                "doi",
                "accession_number",
                "accession_num",
            )
            or ""
        )
    ) or extract_doi(str(_ref_get(row, "notes", "research_notes", "url") or ""))
    extra = str(_ref_get(row, "notes") or "")
    pmid = extract_pmid(extra) or extract_pmid(
        str(_ref_get(row, "accession_number", "accession_num", "accession") or "")
    )
    url = str(_ref_get(row, "url", "urls") or "").split()[0] if _ref_get(row, "url", "urls") else None
    if url and url.startswith("internal-pdf:"):
        url = None
    type_name = str(_ref_get(row, "ref_type_name", "type_name") or "")
    type_num = _ref_get(row, "reference_type", "ref_type", "type")
    try:
        type_i = int(type_num) if type_num is not None else None
    except (TypeError, ValueError):
        type_i = None
    if type_name.strip():
        item_type = endnote_to_zotero(type_name, type_i)
    else:
        item_type = endnote_db_to_zotero(type_i)
    pdf = backend._pdf_for(ref_id)
    paths = backend._groups_for(ref_id)
    return Item(
        key=ref_id,
        item_type=item_type,
        title=title,
        doi=doi,
        arxiv_id=extract_arxiv_id(url or "") or extract_arxiv_id(extra),
        url=url,
        year=year,
        first_author=first,
        collection_paths=paths,
        doi_source="field" if doi else "none",
        library_doi=doi,
        pmid=pmid,
        extra=extra,
        publication_title=str(_ref_get(row, "secondary_title", "journal", "alt_title") or "")
        or None,
        date=str(year) if year else None,
        has_pdf=pdf is not None,
        has_linked_url=False,
        date_added=None,
        creator_count=len(authors),
        abstract=str(_ref_get(row, "abstract") or "") or None,
        creator_surnames=[a["lastName"] for a in authors],
    )


def _raw_from_ref(row: dict[str, Any], backend: EndNoteBackend) -> dict[str, Any]:
    item = _item_from_ref(row, backend)
    authors = _split_authors(str(_ref_get(row, "author", "authors") or ""))
    keywords = str(_ref_get(row, "keywords", "keyword") or "")
    tags = [{"tag": k.strip()} for k in re.split(r"[;\r\n]+", keywords) if k.strip()]
    data = {
        "itemType": item.item_type,
        "title": item.title,
        "creators": authors,
        "abstractNote": item.abstract or "",
        "date": item.date or "",
        "DOI": item.doi or "",
        "url": item.url or "",
        "extra": item.extra or "",
        "publicationTitle": item.publication_title or "",
        "tags": tags,
        "collections": [],
        "key": item.key,
    }
    return {"key": item.key, "data": data}


def _children_from_ref(row: dict[str, Any], backend: EndNoteBackend) -> list[dict[str, Any]]:
    item = _item_from_ref(row, backend)
    out: list[dict[str, Any]] = []
    pdf = backend._pdf_for(item.key)
    if pdf is not None:
        out.append(
            {
                "key": f"{item.key}-pdf",
                "data": {
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                    "filename": pdf.name,
                    "md5": None,
                },
            }
        )
    research = str(_ref_get(row, "research_notes", "researchNotes") or "")
    notes = str(_ref_get(row, "notes") or "")
    if research:
        out.append(
            {
                "key": f"{item.key}-research",
                "data": {
                    "itemType": "note",
                    "note": f"<p>{_escape(research)}</p>",
                    "tags": [{"tag": "endnote-research-notes"}],
                },
            }
        )
    if notes and notes != research:
        out.append(
            {
                "key": f"{item.key}-notes",
                "data": {
                    "itemType": "note",
                    "note": f"<p>{_escape(notes)}</p>",
                    "tags": [{"tag": "endnote-notes"}],
                },
            }
        )
    return out


def _item_from_pending(rec: dict[str, Any]) -> Item:
    creators = rec.get("creators") or []
    first = None
    surnames = []
    for c in creators:
        if isinstance(c, dict) and c.get("lastName"):
            surnames.append(c["lastName"])
            if first is None:
                first = c["lastName"]
    return Item(
        key=str(rec.get("item_key") or ""),
        item_type=str(rec.get("item_type") or "document"),
        title=str(rec.get("title") or "(untitled)"),
        doi=rec.get("doi"),
        arxiv_id=None,
        url=rec.get("url"),
        year=rec.get("year") if isinstance(rec.get("year"), int) else parse_year(str(rec.get("date") or "")),
        first_author=first,
        collection_paths=list(rec.get("collection_paths") or [UNCOLLECTED]),
        doi_source="field" if rec.get("doi") else "none",
        library_doi=rec.get("doi"),
        pmid=rec.get("pmid"),
        extra=str(rec.get("extra") or ""),
        publication_title=rec.get("publication_title"),
        date=str(rec.get("date") or "") or None,
        has_pdf=bool(rec.get("pdfs")),
        creator_count=len(creators),
        abstract=rec.get("abstract"),
        creator_surnames=surnames,
    )


def _raw_from_pending(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    if rec is None:
        return None
    return {
        "key": rec.get("item_key"),
        "data": {
            "itemType": rec.get("item_type"),
            "title": rec.get("title"),
            "creators": rec.get("creators") or [],
            "abstractNote": rec.get("abstract") or "",
            "date": rec.get("date") or "",
            "DOI": rec.get("doi") or "",
            "url": rec.get("url") or "",
            "extra": rec.get("extra") or "",
            "publicationTitle": rec.get("publication_title") or "",
            "tags": rec.get("tags") or [],
            "key": rec.get("item_key"),
        },
    }


def _children_from_pending(rec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for pdf in rec.get("pdfs") or []:
        out.append(
            {
                "key": Path(str(pdf)).name,
                "data": {
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                    "filename": Path(str(pdf)).name,
                },
            }
        )
    for note in rec.get("notes") or []:
        if not isinstance(note, dict):
            continue
        out.append(
            {
                "key": note.get("file"),
                "data": {
                    "itemType": "note",
                    "note": note.get("html") or "",
                    "tags": [{"tag": note["tag"]}] if note.get("tag") else [],
                },
            }
        )
    return out


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _readme(dest: Path) -> str:
    num, name = zotero_to_endnote("journalArticle")
    del num, name
    return (
        "paperful EndNote import bundle\n"
        "==============================\n\n"
        "EndNote has no public write API. paperful never edits your .enl / .Data\n"
        "database. Import this folder through EndNote's own File menu:\n\n"
        "  1. Open EndNote.\n"
        "  2. File → Import → File…\n"
        "  3. Choose paperful.xml in this folder.\n"
        "  4. Import Option: EndNote Generated XML (or XML).\n"
        "  5. Defaults: Import all / Duplicates: discard or import into duplicates.\n\n"
        "PDFs are in PDF/ and referenced as internal-pdf:// filenames. If EndNote\n"
        "does not attach them automatically, File → Import → Folder and point at\n"
        "PDF/, or drag the files onto the matching references.\n\n"
        "Groups / group sets are not present in EndNote XML. Collection paths are\n"
        "stored in the Label field so you can rebuild groups after import.\n"
        f"Bundle path: {dest}\n"
    )
