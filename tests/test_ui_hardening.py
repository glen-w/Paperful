"""Workbench hardening: hostile ids, refused forms, and a vanished collection."""

from __future__ import annotations

import json

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available

pytestmark = pytest.mark.skipif(
    not fastapi_available(), reason="paperful[serve] extra missing"
)

TREE = {
    "ok": True,
    "collections": [
        {"path": "ocean", "name": "ocean", "key": "C1", "items": 1, "missing_pdf": 1}
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    doctor = lambda _cfg, probe=False: []  # noqa: E731
    monkeypatch.setattr(ops, "doctor_payload", doctor)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", doctor)
    monkeypatch.setattr("paperful.ui.app.collections_tree", lambda _cfg: TREE)
    monkeypatch.setattr(
        "paperful.ui.jobs._load_scope_items", lambda *a, **k: ([], None)
    )
    test_client = TestClient(create_app(cfg), raise_server_exceptions=False)
    test_client.cfg = cfg
    return test_client


HTML = {"Origin": "http://testserver", "Accept": "text/html"}


def test_run_id_cannot_name_a_file_outside_the_commands_folder(client):
    from paperful.ui import commands

    secret = client.cfg.state_dir / "secret.json"
    secret.write_text(json.dumps({"status": "failed", "error": "LEAKED"}))
    assert commands.read_command(client.cfg, "../../secret") is None
    assert commands.read_command(client.cfg, "") is None
    assert "LEAKED" not in client.get("/activity?run=../../secret").text


def test_safe_id_keeps_run_stamps_and_drops_paths():
    from paperful.ui.discover_common import safe_id

    assert safe_id(" 20260101T120000Z ") == "20260101T120000Z"
    for bad in ("../x", "a/b", "a\\b", "..", "a..b", "", None, "x" * 200):
        assert safe_id(bad) == ""


def test_discover_keep_ignores_a_run_id_that_is_a_path(client):
    outside = client.cfg.state_dir / "candidates.jsonl"
    outside.write_text(json.dumps({"ids": {"doi": "10.1/x"}}) + "\n")
    before = outside.read_text()
    res = client.post(
        "/discover/keep",
        data={"run_id": "..", "doi": "10.1/x", "keep": "0"},
        headers=HTML,
        follow_redirects=False,
    )
    assert res.status_code < 500
    assert outside.read_text() == before


def test_a_refused_form_is_a_400_page_with_the_reason(client):
    res = client.post("/discover/aw/add", data={}, headers=HTML)
    assert res.status_code == 400
    assert "That request was not valid" in res.text
    assert "--orcid" in res.text  # the reason, not a stack trace
    assert "Something went wrong" not in res.text


def test_an_overlong_name_is_refused_not_a_filesystem_error(client):
    res = client.post(
        "/discover/aw/save",
        data={"list_name": "x" * 300, "name": "x" * 300},
        headers=HTML,
        follow_redirects=False,
    )
    assert res.status_code < 500


def test_a_vanished_collection_is_said_on_every_page(client):
    cookie = {"Cookie": "pf_collection=renamed-away"}
    client.get("/library")  # fills the collection tree cache
    for path in ("/wanted", "/library", "/discover", "/ask"):
        assert "is not in the library any more" in client.get(path, headers=cookie).text
    held = client.get("/wanted", headers={"Cookie": "pf_collection=ocean"}).text
    assert "is not in the library any more" not in held


def test_help_tips_do_not_steal_the_label(client):
    text = client.get("/settings").text
    assert "<button" not in text.split('class="help-tip')[0].rsplit("<", 1)[-1]
    assert '<span role="button" tabindex="0" class="help-tip' in text
