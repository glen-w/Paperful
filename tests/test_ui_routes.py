"""Workbench route modules: mount_ui registers families; POST smokes stay offline."""

from __future__ import annotations

import inspect

import pytest

from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import app as ui_app


def test_index_jobs_reexported_from_jobs_module():
    from paperful.ui import index_jobs, jobs

    assert jobs.rag_ingest is index_jobs.rag_ingest
    assert jobs.summarize is index_jobs.summarize
    assert jobs.rag_ingest_fn is None


def test_shell_routes_resolve_doctor_and_collections_via_app():
    from paperful.ui import shell_routes

    src = inspect.getsource(shell_routes)
    assert "_ui_app.doctor_payload(" in src
    assert "_ui_app.collections_tree(" in src
    assert "from . import app as _ui_app" in src


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_discover_handlers_are_module_level():
    from paperful.ui import discover_routes

    assert callable(discover_routes.handle_page_discover)
    assert callable(discover_routes.handle_discover_explore)
    assert callable(discover_routes._discover_page)
    src = inspect.getsource(discover_routes.register_discover)
    assert "handle_page_discover(" in src
    assert "def _discover_page(" not in src


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
@pytest.mark.parametrize(
    "mod_name, handle, register",
    [
        ("index_routes", "handle_page_index", "register_index"),
        ("wanted_routes", "handle_page_wanted", "register_wanted"),
        ("shell_routes", "handle_page_library", "register_shell"),
        ("repair_routes", "handle_page_repair", "register_repair"),
        ("critique_routes", "handle_page_critique", "register_critique"),
    ],
)
def test_desk_handlers_are_module_level(mod_name, handle, register):
    import importlib

    mod = importlib.import_module(f"paperful.ui.{mod_name}")
    assert callable(getattr(mod, handle))
    src = inspect.getsource(getattr(mod, register))
    assert f"{handle}(" in src
    assert f"def {handle}(" not in src


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_mount_ui_has_no_inline_wanted_or_discover_routes():
    src = inspect.getsource(ui_app.mount_ui)
    assert '@app.get("/wanted"' not in src
    assert '@app.post("/discover' not in src
    assert "register_wanted" in src
    assert "register_discover" in src
    assert "register_index" in src
    assert "register_repair" in src
    assert "register_shell" in src
    assert "register_critique" in src


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_post_smokes_per_family(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    import paperful.ui.jobs as jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    doctor = lambda _cfg, probe=False: [
        {"name": "Zotero", "status": "green", "code": "", "detail": "ok"}
    ]
    monkeypatch.setattr(ops, "doctor_payload", doctor)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", doctor)
    monkeypatch.setattr(
        ops,
        "collections_tree",
        lambda _cfg: {"ok": True, "error": "", "collections": []},
    )
    monkeypatch.setattr(
        "paperful.catalogue.open_library",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("no live manager")),
    )

    # Job hooks: avoid real work
    monkeypatch.setattr(
        jobs,
        "summarize",
        lambda *a, **k: None,
    )

    client = TestClient(create_app(cfg))

    # shell: prefs collection
    res = client.post(
        "/prefs/collection",
        data={"collection": "BBNJ"},
        follow_redirects=False,
    )
    assert res.status_code in {302, 303, 200}

    # wanted: preview without token should not 500
    res = client.post("/wanted/preview", data={}, follow_redirects=False)
    assert res.status_code in {303, 302, 400, 422, 200}

    # discover: refs-gap
    res = client.post(
        "/discover/refs-gap",
        data={"collection": "BBNJ"},
        follow_redirects=False,
    )
    assert res.status_code in {303, 302, 400, 422, 200}

    # index: ingest (may redirect or error without collection; must not 500)
    res = client.post(
        "/index/ingest",
        data={"collection": ""},
        follow_redirects=False,
    )
    assert res.status_code < 500

    # repair: preview
    res = client.post(
        "/repair/preview",
        data={"collection": "BBNJ"},
        follow_redirects=False,
    )
    assert res.status_code < 500

    res = client.post("/critique", data={}, follow_redirects=False)
    assert res.status_code < 500

    res = client.post("/rewrite", data={}, follow_redirects=False)
    assert res.status_code < 500
