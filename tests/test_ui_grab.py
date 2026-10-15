"""Preview, Grab (fetch-only), and Attach review paths."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.store import Manifest, Record, STATUS_OK
from paperful.ui import commands, jobs
from paperful.ui.pages import scope_fingerprint


class _Item:
    def __init__(self, key: str, doi: str):
        self.key = key
        self.title = key
        self.doi = doi
        self.has_pdf = False
        self.arxiv_id = None
        self.url = ""


def test_grab_stale_token_and_fetch_only(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    items = [_Item("K1", "10.1/a"), _Item("K2", "10.2/b")]
    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(
            itemKey="K1",
            status=STATUS_OK,
            doi="10.1/a",
            pdf_doi="10.1/a",
            source="unpaywall",
            path="a.pdf",
        )
    )
    fp = scope_fingerprint(items, manifest)

    attached: list[str] = []
    fetch_calls: list[dict] = []

    def fake_run(*args, **kwargs):
        fetch_calls.append(kwargs)
        return None

    def fake_attach(cfg, keys=None):
        attached.extend(keys or [])

    jobs.run_fetch_fn = fake_run
    jobs.attach_fn = fake_attach
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))

    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="BBNJ",
        preset="oa",
        keys=["K1", "K2"],
        fingerprint=fp,
        command_id="abc",
    )
    ok, _ = jobs.grab_run(cfg, token=token)
    assert ok
    assert attached == []
    assert fetch_calls and set(fetch_calls[0].get("item_keys") or []) == {"K1", "K2"}

    ok2, msg2 = jobs.grab_run(cfg, token=token)
    assert not ok2
    assert "token" in msg2.lower()

    token2 = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="BBNJ",
        preset="oa",
        keys=["K1"],
        fingerprint="wrong",
        command_id="def",
    )
    ok3, msg3 = jobs.grab_run(cfg, token=token2)
    assert not ok3
    jobs.run_fetch_fn = None
    jobs.attach_fn = None


def test_grab_production_passes_item_keys(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    items = [_Item("K1", "10.1/a"), _Item("K2", "10.2/b")]
    manifest = Manifest(cfg.manifest_path)
    selected = [items[0]]
    fp = scope_fingerprint(selected, manifest)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    jobs.run_fetch_fn = None

    captured: dict = {}

    def fake_run_fetch(console, cfg, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("paperful.run_cmd.run_fetch", fake_run_fetch)

    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="BBNJ",
        preset="oa",
        keys=["K1"],
        fingerprint=fp,
        command_id="keys",
    )
    ok, msg = jobs.grab_run(cfg, token=token)
    assert ok, msg
    assert captured.get("item_keys") == ["K1"]
    assert captured.get("no_attach") is True


def test_preview_all_uses_missing_list_only(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    have = _Item("HAVE", "10.1/have")
    have.has_pdf = True
    miss = _Item("MISS", "10.1/miss")
    manifest = Manifest(cfg.manifest_path)
    manifest.write(
        Record(
            itemKey="HAVE",
            status=STATUS_OK,
            doi="10.1/have",
            pdf_doi="10.1/have",
            source="unpaywall",
            path="have.pdf",
        )
    )
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: ([have, miss], manifest))
    commands.write_command(
        cfg,
        {"id": "prev", "verb": "preview_run", "status": "running", "created": 1},
    )
    jobs.preview_run(cfg, "prev", collection="BBNJ", preset="oa", keys=None, flags={})
    rec = commands.read_command(cfg, "prev") or {}
    review = commands.load_review(cfg, rec["review_token"])
    assert review is not None
    assert review["keys"] == ["MISS"]


def test_grab_rejects_non_preview_token(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    items = [_Item("K1", "10.1/a")]
    manifest = Manifest(cfg.manifest_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    called: list[str] = []
    jobs.run_fetch_fn = lambda *args, **kwargs: called.append("fetch")
    token = commands.create_review_token(
        cfg,
        verb="attach",
        collection="BBNJ",
        preset="oa",
        keys=["K1"],
        fingerprint="x",
        command_id="att",
    )
    ok, msg = jobs.grab_run(cfg, token=token)
    assert not ok
    assert "preview" in msg.lower()
    assert called == []
    jobs.run_fetch_fn = None


def test_matching_preview_ignores_newer_attach_token(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    miss = _Item("MISS", "10.1/miss")
    manifest = Manifest(cfg.manifest_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: ([miss], manifest))
    commands.write_command(
        cfg,
        {"id": "prev", "verb": "preview_run", "status": "done", "created": 1},
    )
    jobs.preview_run(cfg, "prev", collection="BBNJ", preset="oa", keys=None, flags={})
    preview = commands.load_review(cfg, (commands.read_command(cfg, "prev") or {})["review_token"])
    assert preview is not None
    attach = commands.create_review_token(
        cfg,
        verb="attach",
        collection="BBNJ",
        preset="oa",
        keys=["MISS"],
        fingerprint="other",
        command_id="att",
    )
    commands.write_command(
        cfg,
        {
            "id": "att",
            "verb": "attach",
            "status": "done",
            "created": 50,
            "review_token": attach,
        },
    )
    review, err = jobs.matching_preview(
        cfg,
        collection="BBNJ",
        preset="oa",
        posted_keys=[],
        flags={},
    )
    assert err == ""
    assert review is not None
    assert review["verb"] == "preview_run"
    assert review["token"] == preview["token"]
    mismatched, why = jobs.matching_preview(
        cfg,
        collection="BBNJ",
        preset="oa",
        posted_keys=["OTHER"],
        flags={},
    )
    assert mismatched is None
    assert "ticked" in why.lower()


def test_attach_run_selected_keys(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    items = [_Item("K1", "10.1/a"), _Item("K2", "10.2/b")]
    manifest = Manifest(cfg.manifest_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))

    attached: list[str] = []

    def fake_attach(cfg, keys=None):
        attached.extend(keys or [])

    jobs.attach_fn = fake_attach
    ok, msg = jobs.attach_run(cfg, keys=["K2", "K1"], collection="BBNJ")
    assert ok
    assert msg == ""
    assert attached == ["K2", "K1"] or set(attached) == {"K1", "K2"}

    ok2, msg2 = jobs.attach_run(cfg, keys=[], collection="BBNJ")
    assert not ok2
    assert "keys" in msg2.lower()

    ok3, msg3 = jobs.attach_run(cfg, keys=["MISSING"], collection="BBNJ")
    assert not ok3
    jobs.attach_fn = None


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_wanted_grab_uses_grab_review_token(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    miss = _Item("K1", "10.1/a")
    manifest = Manifest(cfg.manifest_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: ([miss], manifest))
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [{"name": "x", "status": "green", "code": "", "detail": ""}],
    )
    grabbed: list[str] = []

    def fake_grab(cfg, *, token):
        grabbed.append(token)
        return True, ""

    monkeypatch.setattr(jobs, "grab_run", fake_grab)
    good = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="",
        preset="oa",
        keys=["K1"],
        fingerprint="fp",
        command_id="prev",
    )
    commands.create_review_token(
        cfg,
        verb="attach",
        collection="",
        preset="oa",
        keys=["K1"],
        fingerprint="fp2",
        command_id="att",
    )
    client = TestClient(create_app(cfg))
    res = client.post(
        "/wanted/grab",
        data={"grab_review_token": good, "review_token": "wrong-attach-token"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert grabbed == [good]


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_wanted_attach_route_and_button(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(
        ops,
        "doctor_payload",
        lambda _cfg, probe=False: [
            {"name": "Zotero", "status": "green", "code": "", "detail": ""}
        ],
    )
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    attached: list[str] = []

    def fake_attach_run(cfg, *, keys, collection):
        attached.extend(keys)
        return True, ""

    monkeypatch.setattr(jobs, "attach_run", fake_attach_run)
    client = TestClient(create_app(cfg))
    page = client.get("/wanted")
    assert page.status_code == 200
    assert 'formaction="/wanted/attach"' in page.text
    assert "Attach PDFs to Zotero" in page.text
    assert "Pick a collection" in page.text
    res = client.post(
        "/wanted/attach",
        content=b"keys=K1&keys=K2",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert attached == ["K1", "K2"]


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_grab_without_preview_stays_on_wanted(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: ([], Manifest(cfg.manifest_path)))
    client = TestClient(create_app(cfg))
    res = client.post("/wanted/grab", data={}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].startswith("/wanted?")
    assert "Preview" in res.headers["location"]
