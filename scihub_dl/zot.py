"""Read-side access to the running Zotero client via its local API (pyzotero, local=True)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from pyzotero import zotero

from .resolve import extract_arxiv_id, extract_doi, normalize_doi

SKIP_TYPES = {"attachment", "note", "annotation"}
UNCOLLECTED = "_uncollected"
_PATH_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


@dataclass
class Collection:
    key: str
    name: str
    parent: str | None
    path: str  # filesystem-safe: "BBNJ/EIA _ SEA"
    raw_path: str = ""  # names joined verbatim: "BBNJ/EIA / SEA"


@dataclass
class Item:
    key: str
    item_type: str
    title: str
    doi: str | None
    arxiv_id: str | None
    url: str | None
    year: int | None
    first_author: str | None
    collection_paths: list[str] = field(default_factory=list)
    doi_source: str = "none"  # field | extra | url | crossref | none

    @property
    def label(self) -> str:
        who = self.first_author or "Unknown"
        yr = str(self.year) if self.year else "n.d."
        return f"{who} ({yr}) {self.title[:70]}"


class ZoteroLocal:
    """Thin wrapper over pyzotero pointed at localhost:23119."""

    def __init__(self, local_api_key: str | None = None):
        self.zot = zotero.Zotero(0, "user", local=True, local_api_key=local_api_key)
        self._collections: dict[str, Collection] | None = None

    # ---- connectivity -------------------------------------------------
    def ping(self) -> dict[str, Any]:
        """Return server info; raises if the local API is disabled or Zotero is not running."""
        resp = self.zot.client.get(self.zot.endpoint + "/")
        if resp.status_code == 403:
            raise ConnectionError(
                "Zotero local API is disabled. Enable Settings > Advanced > "
                "'Allow other applications on this computer to communicate with Zotero'."
            )
        resp.raise_for_status()
        return {
            "zotero_version": resp.headers.get("X-Zotero-Version"),
            "api_version": resp.headers.get("Zotero-API-Version"),
            "server_id": resp.headers.get("Zotero-Server-ID"),
            "schema_version": resp.headers.get("Zotero-Schema-Version"),
            "supports_write": bool(resp.headers.get("Zotero-Server-ID")),
        }

    # ---- collections --------------------------------------------------
    def collections(self) -> dict[str, Collection]:
        if self._collections is None:
            raw = self.zot.everything(self.zot.collections())
            self._collections = build_collection_tree(raw)
        return self._collections

    def resolve_collection(self, spec: str) -> Collection:
        """Resolve 'BBNJ/not undermine', a unique collection name, or a collection key."""
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
            raise LookupError(f"Collection name '{spec}' is ambiguous; use a path: {paths}")
        raise LookupError(f"No collection matching '{spec}'")

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
        """Per collection key: (top-level items, items lacking PDF), counting subcollections."""
        cols = self.collections()
        pdf_parents = self._pdf_parent_keys()
        raw_items = self.zot.everything(self.zot.top())
        direct: dict[str, list[dict[str, Any]]] = {k: [] for k in cols}
        for it in raw_items:
            if it["data"].get("itemType") in SKIP_TYPES:
                continue
            for ck in it["data"].get("collections", []):
                if ck in direct:
                    direct[ck].append(it)
        counts: dict[str, tuple[int, int]] = {}
        for key, col in cols.items():
            seen: dict[str, dict[str, Any]] = {}
            for sub in self.subtree_keys(col):
                for it in direct.get(sub, []):
                    seen[it["key"]] = it
            missing = sum(1 for k in seen if k not in pdf_parents)
            counts[key] = (len(seen), missing)
        return counts

    # ---- items ----------------------------------------------------------
    def _pdf_parent_keys(self) -> set[str]:
        """Keys of parent items that already have a PDF attachment."""
        attachments = self.zot.everything(self.zot.items(itemType="attachment"))
        return {
            a["data"]["parentItem"]
            for a in attachments
            if a["data"].get("parentItem") and is_pdf_attachment(a["data"])
        }

    def items_lacking_pdf(self, collection_keys: list[str] | None) -> list[Item]:
        """Top-level regular items in the selected collections (or library) without a PDF child."""
        cols = self.collections()
        pdf_parents = self._pdf_parent_keys()
        if collection_keys is None:
            raw = self.zot.everything(self.zot.top())
            selected: set[str] | None = None
        else:
            raw_by_key: dict[str, dict[str, Any]] = {}
            for ck in collection_keys:
                for it in self.zot.everything(self.zot.collection_items_top(ck)):
                    raw_by_key[it["key"]] = it
            raw = list(raw_by_key.values())
            selected = set(collection_keys)
        items: list[Item] = []
        for it in raw:
            data = it["data"]
            if data.get("itemType") in SKIP_TYPES or data.get("deleted"):
                continue
            if it["key"] in pdf_parents:
                continue
            items.append(item_from_json(it, cols, selected))
        items.sort(key=lambda i: (i.collection_paths[0] if i.collection_paths else "~", i.label.lower()))
        return items


# ---- pure helpers (testable without Zotero) -------------------------------


def is_pdf_attachment(data: dict[str, Any]) -> bool:
    if data.get("contentType") != "application/pdf":
        return False
    return data.get("linkMode") in {"imported_file", "imported_url", "linked_file"}


def build_collection_tree(raw: Iterable[dict[str, Any]]) -> dict[str, Collection]:
    nodes: dict[str, tuple[str, str | None]] = {}
    for c in raw:
        d = c["data"]
        parent = d.get("parentCollection") or None
        nodes[d["key"]] = (d["name"], parent if parent else None)
    out: dict[str, Collection] = {}

    def path_of(key: str, safe: bool, depth: int = 0) -> str:
        name, parent = nodes[key]
        seg = (_PATH_UNSAFE.sub("_", name).strip() or key) if safe else name.strip()
        if parent and parent in nodes and depth < 50:
            return f"{path_of(parent, safe, depth + 1)}/{seg}"
        return seg

    for key, (name, parent) in nodes.items():
        out[key] = Collection(
            key=key, name=name, parent=parent, path=path_of(key, True), raw_path=path_of(key, False)
        )
    return out


def _squash(s: str) -> str:
    """Comparison form: lowercase, whitespace collapsed, slashes/underscores treated alike."""
    s = re.sub(r"\s+", " ", s.strip().strip("/").lower())
    return re.sub(r"\s*[/_]\s*", "/", s)


def item_from_json(it: dict[str, Any], cols: dict[str, Collection], selected: set[str] | None) -> Item:
    data = it["data"]
    meta = it.get("meta", {})
    doi, doi_source = None, "none"
    if data.get("DOI"):
        doi, doi_source = normalize_doi(data["DOI"]), "field"
    if not doi and data.get("extra"):
        doi = extract_doi(data["extra"])
        doi_source = "extra" if doi else doi_source
    if not doi and data.get("url"):
        doi = extract_doi(data["url"])
        doi_source = "url" if doi else doi_source
    if not doi:
        doi_source = "none"
    arxiv_id = extract_arxiv_id(data.get("url")) or extract_arxiv_id(data.get("extra"))
    paths = []
    for ck in data.get("collections", []):
        if ck in cols and (selected is None or ck in selected):
            paths.append(cols[ck].path)
    if not paths:
        paths = [UNCOLLECTED]
    return Item(
        key=it["key"],
        item_type=data.get("itemType", "document"),
        title=(data.get("title") or "").strip() or "(untitled)",
        doi=doi,
        arxiv_id=arxiv_id,
        url=(data.get("url") or "").strip() or None,
        year=parse_year(meta.get("parsedDate") or data.get("date")),
        first_author=first_author(data.get("creators") or []),
        collection_paths=sorted(paths),
        doi_source=doi_source,
    )


def parse_year(date: str | None) -> int | None:
    if not date:
        return None
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date)
    return int(m.group(1)) if m else None


def first_author(creators: list[dict[str, Any]]) -> str | None:
    authors = [c for c in creators if c.get("creatorType") == "author"]
    editors = [c for c in creators if c.get("creatorType") == "editor"]
    for c in authors or editors or creators:
        if c.get("lastName"):
            return c["lastName"].strip()
        if c.get("name"):
            return c["name"].strip()
    return None
