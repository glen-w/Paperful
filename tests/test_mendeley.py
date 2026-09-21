"""Mendeley REST adapter with a mocked api.mendeley.com."""

from __future__ import annotations

import json
import time

import httpx

from paperful.mendeley import (
    MendeleyBackend,
    MendeleyClient,
    zotero_payload_to_mendeley,
)
from paperful.xfer import apply_import
from tests.conftest import PDF_BYTES, mock_client

DOC_ID = "1137042a-8c30-3cd6-a7f6-7d5f1f6c450d"


class FakeMendeley:
    def __init__(self):
        self.folders = [{"id": "f1", "name": "BBNJ", "parent_id": None}]
        self.docs = {
            DOC_ID: {
                "id": DOC_ID,
                "title": "High seas governance",
                "type": "journal",
                "year": 2021,
                "authors": [{"last_name": "Smith", "first_name": "Jane"}],
                "identifiers": {"doi": "10.1000/test.doi"},
                "source": "Marine Policy",
                "file_attached": False,
                "tags": ["BBNJ"],
                "abstract": "An abstract.",
                "websites": ["https://example.org/p"],
                "created": "2021-01-01T00:00:00.000Z",
                "notes": "<p>library note</p>",
            }
        }
        self.membership = {"f1": [DOC_ID]}
        self.files: dict[str, list[dict]] = {DOC_ID: []}
        self.file_bytes: dict[str, bytes] = {}
        self.annotations: dict[str, list[dict]] = {DOC_ID: []}
        self.seq = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if path == "/profiles/me":
            return _json({"id": "p1", "display_name": "Ada"})
        if path == "/folders" and method == "GET":
            return _json(self.folders)
        if path == "/folders" and method == "POST":
            body = _body(request)
            self.seq += 1
            folder = {
                "id": f"f{self.seq + 1}",
                "name": body.get("name") or "New",
                "parent_id": body.get("parent_id"),
            }
            self.folders.append(folder)
            self.membership.setdefault(folder["id"], [])
            return _json(folder, 201)
        if path.startswith("/folders/") and path.endswith("/documents"):
            fid = path.split("/")[2]
            if method == "GET":
                ids = self.membership.get(fid, [])
                return _json([self.docs[i] for i in ids if i in self.docs])
            body = _body(request)
            did = str(body.get("id") or "")
            self.membership.setdefault(fid, []).append(did)
            return _json({"id": did}, 201)
        if path == "/documents" and method == "GET":
            return _json(list(self.docs.values()))
        if path == "/documents" and method == "POST":
            body = _body(request)
            self.seq += 1
            did = f"new-{self.seq}"
            doc = {
                "id": did,
                "title": body.get("title") or "",
                "type": body.get("type") or "generic",
                "year": body.get("year"),
                "authors": body.get("authors") or [],
                "identifiers": body.get("identifiers") or {},
                "source": body.get("source") or "",
                "file_attached": False,
                "tags": body.get("tags") or [],
                "abstract": body.get("abstract") or "",
                "websites": body.get("websites") or [],
            }
            self.docs[did] = doc
            self.files[did] = []
            self.annotations[did] = []
            return _json(doc, 201)
        if path.startswith("/documents/") and path.endswith("/trash") and method == "POST":
            did = path.split("/")[2]
            self.docs.pop(did, None)
            return httpx.Response(204)
        if path.startswith("/documents/") and method == "PATCH":
            did = path.split("/")[2]
            self.docs.setdefault(did, {"id": did}).update(_body(request))
            return _json(self.docs[did])
        if path.startswith("/documents/") and method == "GET":
            did = path.split("/")[2]
            doc = self.docs.get(did)
            if doc is None:
                return httpx.Response(404, text="missing")
            return _json(doc)
        if path == "/files" and method == "GET":
            did = request.url.params.get("document_id")
            return _json(self.files.get(did or "", []))
        if path == "/files" and method == "POST":
            link = request.headers.get("Link") or ""
            did = DOC_ID
            if "/documents/" in link:
                did = link.split("/documents/", 1)[1].split(">")[0]
            self.seq += 1
            fid = f"file-{self.seq}"
            row = {
                "id": fid,
                "file_name": "paper.pdf",
                "mime_type": "application/pdf",
            }
            self.files.setdefault(did, []).append(row)
            self.file_bytes[fid] = bytes(request.content)
            if did in self.docs:
                self.docs[did]["file_attached"] = True
            return _json({"id": fid}, 201)
        if path.startswith("/files/") and method == "GET":
            fid = path.split("/")[2]
            for rows in self.files.values():
                for f in rows:
                    if f["id"] == fid:
                        return httpx.Response(
                            303,
                            headers={
                                "Location": f"https://s3.example.test/objects/{fid}"
                            },
                        )
            return httpx.Response(404, text="no file")
        if (request.url.host or "") == "s3.example.test":
            if request.headers.get("Authorization"):
                return httpx.Response(403, text="bearer on s3")
            fid = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200, content=self.file_bytes.get(fid) or PDF_BYTES
            )
        if path == "/annotations" and method == "GET":
            did = request.url.params.get("document_id")
            return _json(self.annotations.get(did or "", []))
        if path == "/annotations" and method == "POST":
            body = _body(request)
            self.seq += 1
            ann = {
                "id": f"ann-{self.seq}",
                "document_id": body.get("document_id"),
                "type": body.get("type") or "note",
                "text": body.get("text") or "",
            }
            self.annotations.setdefault(str(body.get("document_id")), []).append(ann)
            return _json(ann, 201)
        if path.startswith("/annotations/") and method == "PATCH":
            aid = path.split("/")[2]
            body = _body(request)
            for rows in self.annotations.values():
                for ann in rows:
                    if ann["id"] == aid:
                        ann.update(body)
                        return _json(ann)
            return httpx.Response(404, text="no ann")
        return httpx.Response(404, text=f"unhandled {method} {path}")


def _json(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _body(request: httpx.Request) -> dict:
    raw = request.content or b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _backend(cfg, fake: FakeMendeley) -> MendeleyBackend:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "mendeley-oauth.json").write_text(
        json.dumps({"access_token": "tok", "expires_at": time.time() + 3600}),
        encoding="utf-8",
    )
    client = MendeleyClient(cfg, http=mock_client(fake.handler))
    return MendeleyBackend(cfg, client)


def test_mendeley_lists_folder_items_and_maps_types(cfg):
    backend = _backend(cfg, FakeMendeley())
    info = backend.ping()
    assert info["display_name"] == "Ada" and info["supports_write"]
    col = backend.resolve_collection("BBNJ")
    items = backend.items_in_scope(backend.subtree_keys(col))
    assert len(items) == 1
    it = items[0]
    assert it.key == DOC_ID
    assert it.item_type == "journalArticle"
    assert it.doi == "10.1000/test.doi"
    assert it.first_author == "Smith"
    assert it.collection_paths == ["BBNJ"]
    assert not it.has_pdf
    kids = backend.children(DOC_ID)
    assert any(
        "library note" in str((ch.get("data") or {}).get("note")) for ch in kids
    )


def test_mendeley_attach_note_patch_export(cfg, tmp_path):
    fake = FakeMendeley()
    backend = _backend(cfg, fake)
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(PDF_BYTES)
    res = backend.attach(DOC_ID, pdf)
    assert res.ok and res.code == "success"
    dest = tmp_path / "out.pdf"
    exported = backend.export_pdf(backend.get_item(DOC_ID), dest)
    assert exported == dest and dest.read_bytes() == PDF_BYTES
    key = backend.create_or_update_note(DOC_ID, "<p>sum</p>", "paperful-summary")
    assert key.startswith("ann-")
    html = backend.read_child_note(DOC_ID, "paperful-summary")
    assert html and "paperful-note:paperful-summary" in html
    backend.apply_patch(DOC_ID, {"doi": "10.9/new", "title": "Retitled"})
    raw = backend.raw_item(DOC_ID)
    assert raw["data"]["title"] == "Retitled"


def test_mendeley_import_creates_parent_in_folder(cfg, tmp_path):
    fake = FakeMendeley()
    backend = _backend(cfg, fake)
    pdf = tmp_path / "n.pdf"
    pdf.write_bytes(PDF_BYTES)
    done = apply_import(
        [
            {
                "item_type": "journalArticle",
                "title": "Imported",
                "creators": [
                    {"creatorType": "author", "lastName": "Ng", "firstName": "Li"}
                ],
                "year": 2019,
                "date": "2019",
                "publication_title": "Nature",
                "doi": "10.2/y",
                "tags": [{"tag": "ocean"}],
                "notes": [{"html": "<p>hi</p>", "tag": "paperful-imported"}],
                "pdfs": [str(pdf)],
                "collection_paths": ["BBNJ"],
            }
        ],
        backend,
    )
    assert done["create"] == 1 and done["attach"] == 1 and done["notes"] == 1
    assert any(d.get("title") == "Imported" for d in fake.docs.values())


def test_zotero_payload_to_mendeley_maps_journal():
    body = zotero_payload_to_mendeley(
        {
            "itemType": "journalArticle",
            "title": "T",
            "creators": [{"creatorType": "author", "lastName": "A", "firstName": "B"}],
            "DOI": "10.1000/test.doi",
            "publicationTitle": "Marine Policy",
            "date": "2020",
            "url": "https://ex.org",
            "tags": [{"tag": "BBNJ"}],
        }
    )
    assert body["type"] == "journal"
    assert body["identifiers"]["doi"] == "10.1000/test.doi"
    assert body["year"] == 2020
    assert body["authors"][0]["last_name"] == "A"


def test_mendeley_uses_folder_uuids_without_membership_get(cfg):
    fake = FakeMendeley()
    fake.docs[DOC_ID]["folder_uuids"] = ["f1"]
    fake.membership = {}
    backend = _backend(cfg, fake)
    col = backend.resolve_collection("BBNJ")
    items = backend.items_in_scope(backend.subtree_keys(col))
    assert len(items) == 1
    assert items[0].collection_paths == ["BBNJ"]


def test_mendeley_paginate_follows_next_without_replaying_params(cfg):
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        if request.url.path != "/documents":
            return httpx.Response(404, text=request.url.path)
        if request.url.params.get("marker") == "p2":
            return _json([{"id": "b"}])
        return httpx.Response(
            200,
            json=[{"id": "a"}],
            headers={
                "Link": '<https://api.mendeley.com/documents?marker=p2>; rel="next"'
            },
        )

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "mendeley-oauth.json").write_text(
        json.dumps({"access_token": "tok", "expires_at": time.time() + 3600}),
        encoding="utf-8",
    )
    client = MendeleyClient(cfg, http=mock_client(handler))
    rows = client.paginate(
        "/documents",
        accept="application/vnd.mendeley-document.1+json",
        params={"view": "all"},
    )
    assert [r["id"] for r in rows] == ["a", "b"]
    assert calls[0][1].get("view") == "all"
    assert "view" not in calls[1][1]
    assert calls[1][1].get("marker") == "p2"


def test_mendeley_duplicate_file_upload_is_unchanged(cfg, tmp_path):
    fake = FakeMendeley()
    orig = fake.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files" and request.method == "POST":
            return httpx.Response(400, text="A file with this hash already exists")
        return orig(request)

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "mendeley-oauth.json").write_text(
        json.dumps({"access_token": "tok", "expires_at": time.time() + 3600}),
        encoding="utf-8",
    )
    backend = MendeleyBackend(cfg, MendeleyClient(cfg, http=mock_client(handler)))
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(PDF_BYTES)
    res = backend.attach(DOC_ID, pdf)
    assert res.ok and res.code == "unchanged"


def test_mendeley_trash_posts_to_trash_not_delete(cfg):
    fake = FakeMendeley()
    calls: list[tuple[str, str]] = []
    orig = fake.handler

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return orig(request)

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "mendeley-oauth.json").write_text(
        json.dumps({"access_token": "tok", "expires_at": time.time() + 3600}),
        encoding="utf-8",
    )
    backend = MendeleyBackend(cfg, MendeleyClient(cfg, http=mock_client(handler)))
    backend.trash_item(DOC_ID)
    assert ("POST", f"/documents/{DOC_ID}/trash") in calls
    assert not any(method == "DELETE" for method, _ in calls)
    assert DOC_ID not in fake.docs
