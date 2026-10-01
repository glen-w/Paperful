"""Shared offline fixtures: a config rooted in tmp_path and an httpx client backed by MockTransport."""

from __future__ import annotations

import importlib
from collections.abc import Callable

import httpx
import pytest

from paperful.config import Config
from paperful.sources.base import Context
from paperful.zot import Item

PDF_BYTES = b"%PDF-1.4\n" + b"x" * 20_000 + b"\n%%EOF"


@pytest.fixture(autouse=True)
def _no_real_zotero(monkeypatch):
    """Tests never talk to a Zotero that happens to be running on this machine.

    A real client gets a transport that refuses every request, which is what
    CI sees. A test that wants a library supplies a stub.
    """
    from paperful.zot import ZoteroLocal

    real_init = ZoteroLocal.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        client = getattr(self.zot, "client", None)
        if not hasattr(client, "_transport"):  # a test's fake client is left alone
            return
        # pyzotero brings its own httpx; use the one the client was built from.
        lib = importlib.import_module(type(client).__module__.split(".")[0])
        if isinstance(client._transport, lib.MockTransport):
            return  # the test already answers for Zotero

        def refuse(request):
            raise lib.ConnectError("no Zotero in tests", request=request)

        client._transport = lib.MockTransport(refuse)
        client._mounts = {}

    monkeypatch.setattr(ZoteroLocal, "__init__", init)
    monkeypatch.delenv("PAPERFUL_OFFLINE", raising=False)


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        email="test@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        scihub_mirrors=["m1.test", "m2.test"],
        delay_scihub_s=(0.0, 0.0),
        concurrency_oa=2,
        min_pdf_bytes=1000,
        mirror_failures_before_skip=2,
    )


def make_item(**overrides) -> Item:
    base = dict(
        key="ITEM0001",
        item_type="journalArticle",
        title="A sufficiently long test title about marine governance",
        doi="10.1000/test.doi",
        arxiv_id=None,
        url="https://example.org/paper",
        year=2019,
        first_author="Smith",
        collection_paths=["Col"],
    )
    base.update(overrides)
    return Item(**base)


@pytest.fixture
def item() -> Item:
    return make_item()


Handler = Callable[[httpx.Request], httpx.Response]


def mock_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture
def ctx_factory(cfg):
    def _make(handler: Handler) -> Context:
        return Context(config=cfg, client=mock_client(handler))

    return _make


class NoChildrenZot:
    """The per-item reads the adapter makes, for a library with nothing behind its rows."""

    local_api_key = "k"

    def children(self, key):
        return []

    def item(self, key):
        from pyzotero import errors as ze

        raise ze.ResourceNotFoundError(key)


class FakeListing:
    """Gives a stub Zotero client the whole-library reads a mirror refresh makes.

    Mix into a stub that defines ``items_in_scope(keys)``. The rows are built
    from those ``Item`` objects each time, so a test that changes what the stub
    lists changes what the mirror holds after the next command.
    """

    _listing_version = 0
    zot = NoChildrenZot()

    def _stub_collections(self) -> dict:
        from paperful.zot import Collection

        cols = dict(self.collections()) if hasattr(self, "collections") else {}
        by_path = {c.path: k for k, c in cols.items()}
        for item in self.items_in_scope(None):
            for path in self._stub_paths(item):
                parent = None
                built = []
                for part in path.split("/"):
                    built.append(part)
                    sofar = "/".join(built)
                    if sofar not in by_path:
                        key = f"C{len(by_path):07d}"
                        cols[key] = Collection(key, part, parent, sofar, sofar)
                        by_path[sofar] = key
                    parent = by_path[sofar]
        return cols

    def _stub_paths(self, item) -> list[str]:
        return list(item.collection_paths)

    def _stub_rows(self) -> list[dict]:
        by_path = {c.path: k for k, c in self._stub_collections().items()}
        rows: list[dict] = []
        for item in self.items_in_scope(None):
            surnames = item.creator_surnames or (
                [item.first_author] if item.first_author else []
            )
            extra = item.extra or ""
            if item.pmid and "PMID" not in extra:
                extra = f"{extra}\nPMID: {item.pmid}".strip()
            if item.arxiv_id and item.arxiv_id not in f"{item.url} {extra}":
                extra = f"{extra}\narXiv: {item.arxiv_id}".strip()
            data = {
                "itemType": item.item_type,
                "title": item.title,
                "creators": [{"creatorType": "author", "lastName": s} for s in surnames],
                "date": item.date or (str(item.year) if item.year else ""),
                "url": item.url or "",
                "extra": extra,
                "abstractNote": item.abstract or "",
                "publicationTitle": item.publication_title or "",
                "dateAdded": item.date_added or "",
                "collections": [by_path[p] for p in self._stub_paths(item) if p in by_path],
            }
            for name, value in (
                ("bookTitle", item.book_title),
                ("seriesTitle", item.series_title),
                ("pages", item.pages),
            ):
                if value:
                    data[name] = value
            if item.doi and item.doi_source in ("field", "none"):
                data["DOI"] = item.doi
            kids = []
            if item.has_pdf:
                kids.append(("P", "imported_file"))
            if item.has_linked_url:
                kids.append(("L", "linked_url"))
            rows.append(
                {
                    "key": item.key,
                    "version": 1,
                    "data": data,
                    "meta": {"numChildren": len(kids)},
                }
            )
            for suffix, mode in kids:
                rows.append(
                    {
                        "key": f"{item.key}{suffix}",
                        "version": 1,
                        "data": {
                            "itemType": "attachment",
                            "parentItem": item.key,
                            "linkMode": mode,
                            "contentType": "application/pdf",
                            "title": "Full Text PDF",
                        },
                    }
                )
        return rows

    def listing(self, path, **params):
        type(self)._listing_version += 1
        version = type(self)._listing_version
        if path == "/collections":
            rows = [
                {"data": {"key": c.key, "name": c.name, "parentCollection": c.parent or False}}
                for c in self._stub_collections().values()
            ]
            return rows, version
        if path == "/items/trash":
            return [], version
        return self._stub_rows(), version

    def keys(self, path, **params):
        rows = self._stub_rows()
        if path == "/items/top":
            return {r["key"] for r in rows if not r["data"].get("parentItem")}
        return {r["key"] for r in rows}


class FakeListingOneCollection(FakeListing):
    """For a stub that answers every scope with the same items: one collection holds them all."""

    def collections(self) -> dict:
        root = self.resolve_collection("")
        return {root.key: root}

    def _stub_paths(self, item) -> list[str]:
        return [self.resolve_collection("").path]


@pytest.fixture
def mock_ollama(monkeypatch):
    """Route every httpx.Client the LLM layer creates through a handler."""
    import paperful.llm.client as mod

    state = {"handler": None, "requests": []}
    orig = httpx.Client

    class _Client(orig):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(state["handler"])
            super().__init__(*a, **kw)

    monkeypatch.setattr(mod.httpx, "Client", _Client)

    def install(handler):
        def wrapped(req):
            state["requests"].append(req)
            return handler(req)

        state["handler"] = wrapped
        return state["requests"]

    return install
