"""ZoteroLocal against a fake pyzotero client - collection resolution, counts, items lacking PDF, ping."""

from __future__ import annotations

import httpx
import pytest

from paperful.zot import UNCOLLECTED, ZoteroLocal, zotero_supports_write


def _col(key, name, parent=None):
    return {"data": {"key": key, "name": name, "parentCollection": parent or False}}


def _item(key, title, cols, item_type="journalArticle", **data):
    d = {
        "key": key,
        "itemType": item_type,
        "title": title,
        "collections": cols,
        "creators": [],
        "date": "2020",
    }
    d.update(data)
    return {"key": key, "data": d}


def _att(key, parent, content_type="application/pdf", link_mode="imported_file"):
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "attachment",
            "parentItem": parent,
            "contentType": content_type,
            "linkMode": link_mode,
        },
    }


class FakeZot:
    """Mimics the pyzotero surface ZoteroLocal uses. everything(x) is identity."""

    endpoint = "http://localhost:23119/api"

    def __init__(self, ping_response: httpx.Response):
        self.client = httpx.Client(
            transport=httpx.MockTransport(lambda r: ping_response)
        )
        self._cols = [
            _col("ROOT", "BBNJ"),
            _col("SUB", "EIA / SEA", "ROOT"),
            _col("OTHER", "interesting"),
            _col("D1", "Drafts", "ROOT"),
            _col("D2", "Drafts", "OTHER"),
        ]
        self._top = [
            _item("A", "Paper A", ["ROOT"], DOI="10.1000/a"),
            _item("B", "Paper B", ["SUB"]),
            _item("C", "Paper C", ["OTHER"]),
            _item("D", "Deleted paper", ["ROOT"], deleted=True),
            _item("N", "Standalone note", ["ROOT"], item_type="note"),
            _item("U", "Uncollected", []),
        ]
        self._atts = [
            _att("A1", "A"),
            _att("B1", "B", link_mode="linked_url"),
            _att("C1", "C", content_type="text/html"),
        ]

    def everything(self, x):
        return x

    def collections(self):
        return self._cols

    def top(self):
        return self._top

    def items(self, itemType=None):
        assert itemType == "attachment"
        return self._atts

    def collection_items_top(self, ck):
        return [it for it in self._top if ck in it["data"]["collections"]]


@pytest.fixture
def zl(monkeypatch):
    fake = FakeZot(
        httpx.Response(
            200,
            headers={
                "X-Zotero-Version": "10.0.1",
                "Zotero-API-Version": "3",
                "Zotero-Server-ID": "abc",
            },
        )
    )
    monkeypatch.setattr("paperful.zot.zotero.Zotero", lambda *a, **k: fake)
    return ZoteroLocal()


def test_ping_reports_version_and_write_support(zl, monkeypatch):
    info = zl.ping()
    assert info["zotero_version"] == "10.0.1" and info["supports_write"] is True
    old = FakeZot(
        httpx.Response(
            200, headers={"X-Zotero-Version": "7.0.15", "Zotero-API-Version": "3"}
        )
    )
    monkeypatch.setattr("paperful.zot.zotero.Zotero", lambda *a, **k: old)
    assert ZoteroLocal().ping()["supports_write"] is False
    ten = FakeZot(
        httpx.Response(
            200, headers={"X-Zotero-Version": "10.0.4", "Zotero-API-Version": "3"}
        )
    )
    monkeypatch.setattr("paperful.zot.zotero.Zotero", lambda *a, **k: ten)
    assert ZoteroLocal().ping()["supports_write"] is True
    assert zotero_supports_write("10.0.4", None) is True
    assert zotero_supports_write("7.0.15", None) is False
    disabled = FakeZot(httpx.Response(403))
    monkeypatch.setattr("paperful.zot.zotero.Zotero", lambda *a, **k: disabled)
    with pytest.raises(ConnectionError, match="disabled"):
        ZoteroLocal().ping()


def test_resolve_collection_by_key_path_name_and_ambiguity(zl):
    assert zl.resolve_collection("SUB").key == "SUB"
    assert zl.resolve_collection("BBNJ/EIA / SEA").key == "SUB"
    assert zl.resolve_collection("bbnj/eia _ sea/").key == "SUB"
    assert zl.resolve_collection("interesting").key == "OTHER"
    assert zl.resolve_collection("BBNJ").key == "ROOT"  # exact path match wins
    assert zl.resolve_collection("interesting/Drafts").key == "D2"
    with pytest.raises(LookupError, match="ambiguous"):
        zl.resolve_collection("Drafts")  # same name under two parents
    with pytest.raises(LookupError, match="No collection"):
        zl.resolve_collection("nope")


def test_subtree_keys_and_counts(zl):
    assert zl.subtree_keys(zl.resolve_collection("ROOT")) == ["ROOT", "SUB", "D1"]
    counts = zl.collection_counts()
    # ROOT: A (has PDF) + B via SUB (linked_url doesn't count) + D (deleted but still counted as item) -> 3 items, 2 lacking
    assert counts["ROOT"] == (3, 2)
    assert counts["SUB"] == (1, 1)
    assert counts["OTHER"] == (1, 1)  # C has only an HTML attachment


def test_items_lacking_pdf_scope_and_filters(zl):
    scoped = zl.items_lacking_pdf(["ROOT", "SUB"])
    assert scoped == []  # B only has linked_url PDF — skipped unless upgrade_linked
    upgraded = zl.items_lacking_pdf(["ROOT", "SUB"], upgrade_linked=True)
    assert [i.key for i in upgraded] == ["B"]
    assert upgraded[0].collection_paths == ["BBNJ/EIA _ SEA"]
    assert zl.count_linked_url_only(["ROOT", "SUB"]) == 1

    whole = zl.items_lacking_pdf(None)
    keys = {i.key for i in whole}
    assert keys == {"C", "U"}
    uncollected = next(i for i in whole if i.key == "U")
    assert uncollected.collection_paths == [UNCOLLECTED]
    # sorted by first collection path, then label: "_uncollected" < "interesting"
    assert [i.key for i in whole] == ["U", "C"]


def test_items_in_scope_includes_items_with_pdf(zl):
    scoped = zl.items_in_scope(["ROOT", "SUB"])
    keys = {i.key for i in scoped}
    assert keys == {"A", "B"}
    a = next(i for i in scoped if i.key == "A")
    assert a.has_pdf is True and a.library_doi == "10.1000/a"
    b = next(i for i in scoped if i.key == "B")
    assert b.has_pdf is False
    assert b.has_linked_url is True


def test_paperful_zotero_host_overrides_endpoint(monkeypatch):
    from paperful.zot import (
        ZoteroLocal,
        _ZOTERO_LOCAL_HOST_HEADER,
        zotero_local_endpoint,
        zotero_local_label,
    )

    monkeypatch.setenv("PAPERFUL_ZOTERO_HOST", "host.docker.internal")
    assert zotero_local_endpoint() == "http://host.docker.internal:23119/api"
    assert zotero_local_label() == "host.docker.internal:23119"
    zl = ZoteroLocal()
    assert zl.zot.endpoint == "http://host.docker.internal:23119/api"
    hooks = zl.zot.client.event_hooks.get("request") or []
    assert hooks, "expected Host header request hook"

    # Simulate httpx request hook mutation
    class _Req:
        def __init__(self):
            self.headers = {}

    req = _Req()
    hooks[-1](req)
    assert req.headers["Host"] == _ZOTERO_LOCAL_HOST_HEADER
    assert req.headers["Host"] == "localhost:23119"
