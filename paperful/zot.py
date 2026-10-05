"""Read-side access to the running Zotero client via its local API (pyzotero, local=True)."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from urllib.parse import unquote, urlparse

from pyzotero import zotero

from .resolve import extract_arxiv_id, extract_doi, extract_pmid, normalize_doi

SKIP_TYPES = {"attachment", "note", "annotation"}
UNCOLLECTED = "_uncollected"
_PATH_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
_ZOTERO_PORT = 23119
# Rows per request for a whole-library read. The local API has no page cap.
LISTING_PAGE = 2000

# Regular (non-attachment) Zotero item types from the CSL/Zotero schema.
ITEM_TYPES: frozenset[str] = frozenset(
    {
        "artwork",
        "audioRecording",
        "bill",
        "blogPost",
        "book",
        "bookSection",
        "case",
        "computerProgram",
        "conferencePaper",
        "dataset",
        "dictionaryEntry",
        "document",
        "email",
        "encyclopediaArticle",
        "film",
        "forumPost",
        "hearing",
        "instantMessage",
        "interview",
        "journalArticle",
        "letter",
        "magazineArticle",
        "manuscript",
        "map",
        "newspaperArticle",
        "patent",
        "podcast",
        "preprint",
        "presentation",
        "radioBroadcast",
        "report",
        "standard",
        "statute",
        "thesis",
        "tvBroadcast",
        "videoRecording",
        "webpage",
    }
)
_ITEM_TYPE_BY_NORM = {t.lower(): t for t in ITEM_TYPES}


def zotero_local_host() -> str:
    """Host for the Zotero local API (override with PAPERFUL_ZOTERO_HOST for Docker).

    ``.env.example`` sets ``host.docker.internal`` so Compose can reach Zotero on
    the host. The CLI also loads that file. Outside a container the name often
    does not resolve, so use localhost unless this process is in Docker.
    """
    host = (os.environ.get("PAPERFUL_ZOTERO_HOST") or "localhost").strip() or "localhost"
    if host == "host.docker.internal" and not Path("/.dockerenv").exists():
        return "localhost"
    return host


def zotero_local_endpoint() -> str:
    return f"http://{zotero_local_host()}:{_ZOTERO_PORT}/api"


def zotero_local_label() -> str:
    """Human-readable address for errors and doctor output."""
    return f"{zotero_local_host()}:{_ZOTERO_PORT}"


def zotero_supports_write(version: str | None, server_id: str | None) -> bool:
    """Local writes exist on Zotero 10+. Server-ID is the usual signal; the version is enough."""
    if server_id:
        return True
    major = (version or "").split(".", 1)[0]
    try:
        return int(major) >= 10
    except ValueError:
        return False


# Zotero's local server rejects requests unless Host is exactly localhost:23119
# (even when reached via host.docker.internal from a container).
_ZOTERO_LOCAL_HOST_HEADER = f"localhost:{_ZOTERO_PORT}"


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
    doi_source: str = "none"  # field | extra | url | crossref | pubmed | none
    library_doi: str | None = None  # DOI as stored in the manager at read time
    pmid: str | None = None
    extra: str = ""
    publication_title: str | None = None
    book_title: str | None = None
    series_title: str | None = None
    pages: str | None = None
    date: str | None = None
    doi_verified: str = "missing"  # ok | suspect | swapped | unknown | missing
    pdf_path: str | None = None
    has_pdf: bool = False
    has_linked_url: bool = False  # PDF attachment is a linked URL, not a stored file
    date_added: str | None = None  # Zotero dateAdded; older wins keep ties
    creator_count: int = 0
    abstract: str | None = None
    creator_surnames: list[str] = field(default_factory=list)
    isbn: str | None = None
    report_number: str | None = None
    pdf_tier: str = ""  # native | snapshot | "" (no stored PDF)

    @property
    def label(self) -> str:
        who = self.first_author or "Unknown"
        yr = str(self.year) if self.year else "n.d."
        return f"{who} ({yr}) {self.title[:70]}"


class ZoteroLocal:
    """Thin wrapper over pyzotero pointed at the Zotero local API (:23119)."""

    def __init__(self, local_api_key: str | None = None):
        self.zot = zotero.Zotero(0, "user", local=True, local_api_key=local_api_key)
        # pyzotero hardcodes localhost; Docker Desktop needs host.docker.internal.
        self.zot.endpoint = zotero_local_endpoint()
        # httpx omits Host from client.headers; set it on every request. Zotero's
        # local API requires Host: localhost:23119 even via host.docker.internal.
        self.zot.client.event_hooks.setdefault("request", []).append(
            _force_zotero_local_host_header
        )
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
        version = resp.headers.get("X-Zotero-Version")
        server_id = resp.headers.get("Zotero-Server-ID")
        return {
            "zotero_version": version,
            "api_version": resp.headers.get("Zotero-API-Version"),
            "server_id": server_id,
            "schema_version": resp.headers.get("Zotero-Schema-Version"),
            "supports_write": zotero_supports_write(version, server_id),
        }

    # ---- whole listings (mirror refresh) ---------------------------------
    def get(self, path: str, **params: Any) -> Any:
        """One GET under the library root. Raises on anything but 200."""
        resp = self.zot.client.get(
            f"{self.zot.endpoint}/users/0{path}", params=params or None
        )
        resp.raise_for_status()
        return resp

    def listing(
        self, path: str, *, page: int = LISTING_PAGE, **params: Any
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Every row of a JSON listing, and the library version it was read at.

        Pages by ``start``. A write that lands between pages changes the
        version header; the read starts again so the rows are one state.
        """
        for _attempt in range(3):
            rows: list[dict[str, Any]] = []
            version: int | None = None
            moved = False
            start = 0
            while True:
                resp = self.get(path, limit=page, start=start, **params)
                seen = _header_int(resp, "Last-Modified-Version")
                if version is None:
                    version = seen
                elif seen is not None and seen != version:
                    moved = True
                    break
                batch = resp.json()
                rows.extend(row for row in batch if isinstance(row, dict))
                if len(batch) < page:
                    break
                start += page
            if not moved:
                return rows, version
        raise ConnectionError("the library kept changing while it was being read")

    def file_path(self, key: str) -> Path | None:
        """Where Zotero keeps a stored attachment's file, if this machine can see it.

        The local API answers a file request with a redirect to a ``file://``
        path. Asking for the redirect moves no bytes. ``None`` means no path
        was given, or the path is on a filesystem this process cannot see
        (Zotero on the host, Paperful in a container).
        """
        resp = self.zot.client.get(
            f"{self.zot.endpoint}/users/0/items/{key}/file", follow_redirects=False
        )
        location = resp.headers.get("Location") or ""
        if resp.status_code not in (301, 302, 303, 307) or not location.startswith("file:"):
            return None
        path = Path(unquote(urlparse(location).path))
        # storage/<key>/<file>: with no storage/ here, the path says nothing.
        return path if path.parent.parent.is_dir() else None

    def keys(self, path: str, **params: Any) -> set[str]:
        """Item keys of a listing. One request, no paging."""
        return set(self.get(path, format="keys", **params).text.split())

    # ---- collections --------------------------------------------------
    def collections(self) -> dict[str, Collection]:
        if self._collections is None:
            raw = self.zot.everything(self.zot.collections())
            self._collections = build_collection_tree(raw)
        return self._collections

    def resolve_collection(self, spec: str) -> Collection:
        """Resolve 'BBNJ/not undermine', a unique collection name, or a collection key."""
        return resolve_collection_in(self.collections(), spec)

    def subtree_keys(self, root: Collection) -> list[str]:
        return subtree_keys_in(self.collections(), root)

    def collection_counts(self) -> dict[str, tuple[int, int]]:
        """Per collection key: (top-level items, items lacking PDF), counting subcollections."""
        cols = self.collections()
        imported, _linked, _snapshot = self._pdf_parent_sets()
        pdf_parents = imported
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
    def _pdf_parent_sets(
        self, *, status: Callable[[str], None] | None = None
    ) -> tuple[set[str], set[str], set[str]]:
        """Imported PDF parents, linked-URL-only parents, and snapshot-only parents.

        Snapshot-only means every imported PDF note is an htmlpdf page print.
        A native PDF on the same parent drops it from that set.
        """
        from .greyid import is_snapshot_note

        tick = status or (lambda _msg: None)
        tick("Fetching PDF attachments from Zotero…")
        attachments = self.zot.everything(self.zot.items(itemType="attachment"))
        native: set[str] = set()
        snapshot: set[str] = set()
        linked_url: set[str] = set()
        for a in attachments:
            data = a["data"]
            parent = data.get("parentItem")
            if not parent:
                continue
            if is_pdf_attachment(data):
                if is_snapshot_note(data.get("note")):
                    snapshot.add(parent)
                else:
                    native.add(parent)
            elif is_linked_url_pdf(data):
                linked_url.add(parent)
        imported = native | snapshot
        linked_url -= imported
        return imported, linked_url, snapshot - native

    def _pdf_parent_keys(self) -> set[str]:
        """Keys of parent items that already have an imported PDF attachment."""
        return self._pdf_parent_sets()[0]

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        """Items in scope that only have a linked PDF URL (skipped unless --upgrade-linked)."""
        return linked_url_only_count(
            self.items_in_scope(collection_keys),
            skip_empty_paths=collection_keys is not None,
        )

    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]:
        """Top-level regular items in the selected collections (or library) without a PDF child."""
        return items_without_stored_pdf(
            self.items_in_scope(collection_keys), upgrade_linked=upgrade_linked
        )

    def items_in_scope(
        self,
        collection_keys: list[str] | None,
        *,
        status: Callable[[str], None] | None = None,
    ) -> list[Item]:
        """All top-level regular items in the selected collections (or library)."""
        tick = status or (lambda _msg: None)
        tick("Reading collection tree…")
        cols = self.collections()
        imported, linked_only, snapshot_only = self._pdf_parent_sets(status=status)
        if collection_keys is None:
            tick("Fetching top-level library items…")
            raw = self.zot.everything(self.zot.top())
            selected: set[str] | None = None
        else:
            tick(
                f"Fetching items from {len(collection_keys)} collection subtree(s)…"
            )
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
            key = it["key"]
            items.append(
                item_from_json(
                    it,
                    cols,
                    selected,
                    has_pdf=key in imported,
                    has_linked_url=key in linked_only,
                    pdf_tier="snapshot" if key in snapshot_only else ("native" if key in imported else ""),
                )
            )
        items.sort(
            key=lambda i: (
                i.collection_paths[0] if i.collection_paths else "~",
                i.label.lower(),
            )
        )
        tick(f"Loaded {len(items)} parent items")
        return items

    def item_exists(self, key: str) -> bool:
        """True if a top-level or child item with this key is in the local library."""
        try:
            self.zot.item(key)
            return True
        except Exception:
            return False

    def find_top_item_key(
        self, *, doi: str | None = None, title: str | None = None
    ) -> str | None:
        """Resolve a live parent key after sync remapped keys (DOI first, then title)."""
        want_doi = normalize_doi(doi)
        want_title = (title or "").strip().lower()
        if not want_doi and not want_title:
            return None
        items = self.items_in_scope(None)
        if want_doi:
            for it in items:
                if it.doi and normalize_doi(it.doi) == want_doi:
                    return it.key
        if want_title:
            for it in items:
                if (it.title or "").strip().lower() == want_title:
                    return it.key
        return None


def _header_int(resp: Any, name: str) -> int | None:
    try:
        return int(resp.headers.get(name))
    except (TypeError, ValueError):
        return None


def item_from_rows(
    raw: dict[str, Any],
    children: Iterable[dict[str, Any]],
    cols: dict[str, Collection],
    selected: set[str] | None = None,
) -> Item:
    """The listing's ``Item`` from a parent payload and its child rows. No request."""
    has_pdf, has_linked, pdf_tier = pdf_flags(children)
    return item_from_json(
        raw,
        cols,
        selected,
        has_pdf=has_pdf,
        has_linked_url=has_linked,
        pdf_tier=pdf_tier,
    )


def _force_zotero_local_host_header(request: Any) -> None:
    request.headers["Host"] = _ZOTERO_LOCAL_HOST_HEADER


# ---- pure helpers (testable without Zotero) -------------------------------


def is_pdf_attachment(data: dict[str, Any]) -> bool:
    if data.get("contentType") != "application/pdf":
        return False
    return data.get("linkMode") in {"imported_file", "imported_url", "linked_file"}


def is_linked_url_pdf(data: dict[str, Any]) -> bool:
    return (
        data.get("contentType") == "application/pdf"
        and data.get("linkMode") == "linked_url"
    )


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
            key=key,
            name=name,
            parent=parent,
            path=path_of(key, True),
            raw_path=path_of(key, False),
        )
    return out


def resolve_collection_in(cols: dict[str, Collection], spec: str) -> Collection:
    """Resolve 'BBNJ/not undermine', a unique collection name, or a collection key."""
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
        raise LookupError(
            f"Collection name '{spec}' is ambiguous; use a path: {paths}"
        )
    raise LookupError(f"No collection matching '{spec}'")


def subtree_keys_in(cols: dict[str, Collection], root: Collection) -> list[str]:
    out = [root.key]
    frontier = [root.key]
    while frontier:
        parent = frontier.pop()
        for c in cols.values():
            if c.parent == parent:
                out.append(c.key)
                frontier.append(c.key)
    return out


def _squash(s: str) -> str:
    """Comparison form: lowercase, whitespace collapsed, slashes/underscores treated alike."""
    s = re.sub(r"\s+", " ", s.strip().strip("/").lower())
    return re.sub(r"\s*[/_]\s*", "/", s)


def pdf_flags(children: Iterable[dict[str, Any]]) -> tuple[bool, bool, str]:
    """``(has stored PDF, linked-URL only, tier)`` from child rows.

    Tier is ``snapshot`` only when every stored PDF is an htmlpdf print.
    """
    from .greyid import is_snapshot_note

    native = False
    snapshot = False
    linked = False
    for ch in children:
        data = ch.get("data") or {}
        if is_pdf_attachment(data):
            if is_snapshot_note(data.get("note")):
                snapshot = True
            else:
                native = True
        elif is_linked_url_pdf(data):
            linked = True
    has_pdf = native or snapshot
    if native:
        tier = "native"
    elif snapshot:
        tier = "snapshot"
    else:
        tier = ""
    return has_pdf, linked and not has_pdf, tier


def item_from_json(
    it: dict[str, Any],
    cols: dict[str, Collection],
    selected: set[str] | None,
    has_pdf: bool = False,
    has_linked_url: bool = False,
    pdf_tier: str = "",
) -> Item:
    data = it["data"]
    meta = it.get("meta", {})
    extra = data.get("extra") or ""
    doi, doi_source = None, "none"
    if data.get("DOI"):
        doi, doi_source = normalize_doi(data["DOI"]), "field"
    if not doi and extra:
        doi = extract_doi(extra)
        doi_source = "extra" if doi else doi_source
    if not doi and data.get("url"):
        doi = extract_doi(data["url"])
        doi_source = "url" if doi else doi_source
    if not doi:
        doi_source = "none"
    arxiv_id = extract_arxiv_id(data.get("url")) or extract_arxiv_id(extra)
    pmid = extract_pmid(extra)
    paths = []
    for ck in data.get("collections", []):
        if ck in cols and (selected is None or ck in selected):
            paths.append(cols[ck].path)
    if not paths:
        paths = [UNCOLLECTED]
    pub = (data.get("publicationTitle") or "").strip() or None
    book_title = (data.get("bookTitle") or "").strip() or None
    series_title = (data.get("seriesTitle") or "").strip() or None
    pages = (data.get("pages") or "").strip() or None
    date = (data.get("date") or "").strip() or None
    creators = data.get("creators") or []
    surnames = [
        str(c.get("lastName") or c.get("name") or "").strip()
        for c in creators
        if isinstance(c, dict)
    ]
    surnames = [s for s in surnames if s]
    abstract = (data.get("abstractNote") or "").strip() or None
    date_added = (data.get("dateAdded") or "").strip() or None
    from .greyid import normalize_isbn, normalize_report_number

    isbn = normalize_isbn(data.get("ISBN") or "") or None
    report_number = normalize_report_number(data.get("reportNumber") or "") or None
    return Item(
        key=it["key"],
        item_type=data.get("itemType", "document"),
        title=(data.get("title") or "").strip() or "(untitled)",
        doi=doi,
        arxiv_id=arxiv_id,
        url=(data.get("url") or "").strip() or None,
        year=parse_year(meta.get("parsedDate") or data.get("date")),
        first_author=first_author(creators),
        collection_paths=sorted(paths),
        doi_source=doi_source,
        library_doi=doi,
        pmid=pmid,
        extra=extra,
        publication_title=pub,
        book_title=book_title,
        series_title=series_title,
        pages=pages,
        date=date,
        has_pdf=has_pdf,
        has_linked_url=has_linked_url and not has_pdf,
        date_added=date_added,
        creator_count=len(creators),
        abstract=abstract,
        creator_surnames=surnames,
        isbn=isbn,
        report_number=report_number,
        pdf_tier=pdf_tier if has_pdf else "",
    )


def parse_year(date: str | None) -> int | None:
    if not date:
        return None
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date)
    return int(m.group(1)) if m else None


def filter_items_by_year(
    items: list[Item],
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[Item]:
    """Keep items whose parsed year is in ``[year_from, year_to]`` (inclusive).

    Open ends are allowed (only ``year_from`` or only ``year_to``). Items with
    no year are excluded whenever either bound is set.
    """
    if year_from is None and year_to is None:
        return list(items)
    out: list[Item] = []
    for it in items:
        if it.year is None:
            continue
        if year_from is not None and it.year < year_from:
            continue
        if year_to is not None and it.year > year_to:
            continue
        out.append(it)
    return out


def normalize_item_type(spec: str) -> str | None:
    """Map a user type string to a canonical Zotero ``itemType`` id.

    Accepts camelCase ids (``journalArticle``), spaced labels
    (``Journal Article``), and hyphen/underscore forms. Case-insensitive.
    """
    token = re.sub(r"[\s_\-]+", "", (spec or "").strip()).lower()
    if not token:
        return None
    return _ITEM_TYPE_BY_NORM.get(token)


def resolve_item_types(specs: list[str]) -> frozenset[str] | None:
    """Parse repeatable/comma-separated type specs into a frozenset of ids.

    Returns ``None`` when ``specs`` is empty (no type filter). Raises
    ``ValueError`` listing unknown tokens.
    """
    if not specs:
        return None
    wanted: set[str] = set()
    unknown: list[str] = []
    for raw in specs:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            canon = normalize_item_type(part)
            if canon is None:
                unknown.append(part)
            else:
                wanted.add(canon)
    if unknown:
        hint = ", ".join(sorted(ITEM_TYPES)[:8]) + ", …"
        raise ValueError(
            f"Unknown item type(s): {', '.join(unknown)}. "
            f"Use Zotero types such as: {hint}"
        )
    return frozenset(wanted) if wanted else None


def filter_items_by_type(
    items: list[Item], types: frozenset[str] | set[str] | None
) -> list[Item]:
    """Keep items whose ``item_type`` is in ``types``. ``None`` keeps all."""
    if not types:
        return list(items)
    return [it for it in items if it.item_type in types]


def items_without_stored_pdf(
    items: list[Item],
    *,
    upgrade_linked: bool = False,
    upgrade_snapshot: bool = False,
) -> list[Item]:
    """Items with no native PDF.

    Linked-URL-only rows drop unless ``upgrade_linked``. Snapshot-only htmlpdf
    prints drop unless ``upgrade_snapshot`` (they are not a native PDF).
    """
    out: list[Item] = []
    for it in items:
        snapshot_only = it.pdf_tier == "snapshot"
        if it.has_pdf and not (upgrade_snapshot and snapshot_only):
            continue
        if it.has_linked_url and not it.has_pdf and not upgrade_linked:
            continue
        out.append(it)
    return out


def linked_url_only_count(items: list[Item], *, skip_empty_paths: bool = False) -> int:
    """Items whose only PDF is a linked URL.

    When ``skip_empty_paths`` is set, rows with no collection path are ignored.
    That matches a collection-scoped count against the local API.
    """
    n = 0
    for it in items:
        if it.has_pdf or not it.has_linked_url:
            continue
        if skip_empty_paths and not it.collection_paths:
            continue
        n += 1
    return n


def first_author(creators: list[dict[str, Any]]) -> str | None:
    authors = [c for c in creators if c.get("creatorType") == "author"]
    editors = [c for c in creators if c.get("creatorType") == "editor"]
    for c in authors or editors or creators:
        if c.get("lastName"):
            return c["lastName"].strip()
        if c.get("name"):
            return c["name"].strip()
    return None
