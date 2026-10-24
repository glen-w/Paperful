"""Local-trust hardening: bind gate, review-token paths, CDP origins."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.config import Config
from paperful.serve import REMOTE_BIND_HINT, is_loopback_bind_host, run_server
from paperful.ui import commands


def test_is_loopback_bind_host():
    assert is_loopback_bind_host("127.0.0.1")
    assert is_loopback_bind_host("::1")
    assert is_loopback_bind_host("localhost")
    assert not is_loopback_bind_host("0.0.0.0")
    assert not is_loopback_bind_host("192.168.1.10")
    assert not is_loopback_bind_host("example.com")


def test_run_server_refuses_non_loopback_without_flag(cfg, monkeypatch):
    monkeypatch.setattr(
        "paperful.serve.fastapi_available",
        lambda: True,
    )

    def boom(*_a, **_k):
        raise AssertionError("uvicorn should not start")

    monkeypatch.setattr("uvicorn.run", boom)
    with pytest.raises(RuntimeError, match="allow-remote-bind"):
        run_server(cfg, host="0.0.0.0", port=8765, allow_remote_bind=False)


def test_run_server_allows_remote_with_flag(cfg, monkeypatch):
    monkeypatch.setattr("paperful.serve.fastapi_available", lambda: True)
    seen: dict[str, object] = {}

    def fake_run(app, *, host, port):
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr("uvicorn.run", fake_run)
    run_server(cfg, host="0.0.0.0", port=8765, allow_remote_bind=True)
    assert seen == {"host": "0.0.0.0", "port": 8765}


def test_load_review_rejects_path_traversal(cfg):
    reviews = cfg.state_dir / "gui" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    # Would escape if joined naively as reviews / f"{token}.json"
    assert commands.load_review(cfg, "../escape") is None
    assert commands.load_review(cfg, "..%2fescape") is None
    assert commands.load_review(cfg, "a/b") is None
    assert commands.load_review(cfg, "") is None


def test_load_review_accepts_urlsafe_token(cfg):
    token = commands.create_review_token(
        cfg,
        verb="grab",
        collection="C",
        preset="oa",
        keys=["K1"],
        fingerprint="fp",
        command_id="cmd-missing",
    )
    data = commands.load_review(cfg, token)
    assert data is not None
    assert data["token"] == token
    path = Path(cfg.state_dir) / "gui" / "reviews" / f"{token}.json"
    assert path.is_file()


def test_remote_bind_hint_mentions_no_auth():
    assert "no auth" in REMOTE_BIND_HINT.lower() or "No auth" in REMOTE_BIND_HINT


# --- Bind matrix ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("::1", True),
        ("localhost", True),
        ("0.0.0.0", False),
        ("::", False),
        ("10.0.0.5", False),
        ("192.168.1.10", False),
        ("example.com", False),
        ("", False),
    ],
)
def test_bind_matrix(cfg, monkeypatch, host, loopback):
    assert is_loopback_bind_host(host) is loopback
    monkeypatch.setattr("paperful.serve.fastapi_available", lambda: True)
    seen: list[str] = []
    monkeypatch.setattr("uvicorn.run", lambda app, *, host, port: seen.append(host))

    if loopback:
        run_server(cfg, host=host, port=8765, allow_remote_bind=False)
        assert seen == [host]
    else:
        with pytest.raises(RuntimeError, match="allow-remote-bind"):
            run_server(cfg, host=host, port=8765, allow_remote_bind=False)
        assert seen == []
        # The flag is the only override.
        run_server(cfg, host=host, port=8765, allow_remote_bind=True)
        assert seen == [host]


# --- Review tokens -------------------------------------------------------------


def _token(cfg, keys=("K1", "K2"), fingerprint="fp"):
    return commands.create_review_token(
        cfg,
        verb="grab",
        collection="C",
        preset="oa",
        keys=list(keys),
        fingerprint=fingerprint,
        command_id="cmd-missing",
    )


def test_review_token_is_single_use(cfg):
    token = _token(cfg)
    assert commands.consume_review(cfg, token, fingerprint="fp", keys=["K1"]) == (True, "")
    ok, msg = commands.consume_review(cfg, token, fingerprint="fp", keys=["K1"])
    assert not ok
    assert msg == "token already used"
    assert commands.load_review(cfg, token)["consumed"] is True


def test_review_token_rejects_stale_fingerprint_without_consuming(cfg):
    token = _token(cfg)
    ok, msg = commands.consume_review(cfg, token, fingerprint="changed", keys=None)
    assert (ok, msg) == (False, "library changed since preview")
    # A rejected attempt must not burn the token.
    assert commands.load_review(cfg, token)["consumed"] is False
    assert commands.consume_review(cfg, token, fingerprint="fp", keys=None)[0]


def test_review_token_rejects_keys_outside_preview(cfg):
    token = _token(cfg, keys=["K1"])
    ok, msg = commands.consume_review(cfg, token, fingerprint="fp", keys=["K1", "K9"])
    assert (ok, msg) == (False, "keys not in preview")
    assert commands.load_review(cfg, token)["consumed"] is False


def test_review_token_unknown_and_malformed(cfg):
    for bad in ("nope-nope-nope", "short", "../../etc/passwd", "a" * 129, "tok en!!", ""):
        ok, msg = commands.consume_review(cfg, bad, fingerprint="fp", keys=None)
        assert (ok, msg) == (False, "unknown token"), bad


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unavailable")
def test_review_token_symlink_escape_is_refused(cfg, tmp_path):
    reviews = cfg.state_dir / "gui" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"token": "linklinklink", "fingerprint": "fp"}', encoding="utf-8")
    try:
        (reviews / "linklinklink.json").symlink_to(outside)
    except OSError:  # pragma: no cover - platform without symlink rights
        pytest.skip("cannot create symlink")
    assert commands.load_review(cfg, "linklinklink") is None
    assert commands.consume_review(cfg, "linklinklink", fingerprint="fp", keys=None) == (
        False,
        "unknown token",
    )
    assert outside.read_text(encoding="utf-8").count("consumed") == 0


@pytest.mark.xfail(
    reason="Review tokens have no TTL today; single-use + fingerprint are the guards.",
    strict=True,
)
def test_review_token_expires(cfg):
    token = _token(cfg)
    path = cfg.state_dir / "gui" / "reviews" / f"{token}.json"
    import os

    old = path.stat().st_mtime - 7 * 24 * 3600
    os.utime(path, (old, old))
    assert commands.consume_review(cfg, token, fingerprint="fp", keys=None)[0] is False


# --- Filename / path traversal on write surfaces -------------------------------

fastapi_missing = not __import__("paperful.serve", fromlist=["x"]).fastapi_available()


def _snapshot(root: Path) -> set[Path]:
    return {p for p in root.rglob("*")} if root.exists() else set()


@pytest.fixture
def ui_client(cfg, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from paperful.serve import create_app

    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _cfg, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree",
        lambda _cfg: {"ok": True, "collections": []},
    )
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


HOSTILE_NAMES = [
    "../escape.txt",
    "../../escape.txt",
    "..\\..\\escape.txt",
    "/tmp/abs-escape.txt",
    "a/b/c.txt",
    "..",
    "name with spaces.csv",
    "x" * 300 + ".csv",
]


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
@pytest.mark.parametrize("filename", HOSTILE_NAMES)
def test_ingest_preview_upload_stays_under_uploads(ui_client, cfg, tmp_path, monkeypatch, filename):
    monkeypatch.setattr("paperful.ui.commands.enqueue", lambda *a, **k: "cmd")
    before = _snapshot(tmp_path)
    ui_client.post(
        "/discover/ingest-preview",
        files={"file": (filename, b"doi\n10.1/x\n", "text/csv")},
        follow_redirects=False,
    )
    uploads = (cfg.state_dir / "gui" / "uploads").resolve()
    for path in _snapshot(tmp_path) - before:
        if path.is_file():
            path.resolve().relative_to(uploads)
    assert not (tmp_path / "escape.txt").exists()
    assert not Path("/tmp/abs-escape.txt").exists()


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
@pytest.mark.parametrize("filename", HOSTILE_NAMES)
def test_aw_import_upload_stays_under_uploads(ui_client, cfg, tmp_path, monkeypatch, filename):
    monkeypatch.setattr("paperful.ui.jobs.authorwatch_import", lambda *a, **k: None)
    before = _snapshot(tmp_path)
    ui_client.post(
        "/discover/aw/import",
        data={"list_name": "followed", "source": "csv"},
        files={"file": (filename, b"name\nA B\n", "text/csv")},
        follow_redirects=False,
    )
    uploads = (cfg.state_dir / "gui" / "uploads").resolve()
    for path in _snapshot(tmp_path) - before:
        if path.is_file():
            path.resolve().relative_to(uploads)
    assert not (tmp_path / "escape.txt").exists()
    assert not Path("/tmp/abs-escape.txt").exists()


def test_safe_child_rejects_traversal_and_symlinks(tmp_path):
    from paperful.ui.pages import safe_child

    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.html").write_text("x", encoding="utf-8")
    secret = tmp_path / "secret.html"
    secret.write_text("s", encoding="utf-8")
    assert safe_child(root, "ok.html") is not None
    for bad in ("..", ".", "", "../secret.html", "a/b", "a\\b"):
        assert safe_child(root, bad) is None, bad
    assert safe_child(root) is None
    try:
        (root / "link.html").symlink_to(secret)
    except OSError:  # pragma: no cover
        return
    assert safe_child(root, "link.html") is None


def test_rag_form_upload_and_prompt_names_are_sanitized(cfg):
    from paperful.ui import rag_form

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    uploads = (cfg.state_dir / "gui" / "uploads").resolve()
    prompts = (cfg.state_dir / "prompts").resolve()
    for name in ("../../evil.md", "a/b.md", "evil.exe"):
        saved = rag_form._persist_upload(cfg, b"hello", name)
        if saved:
            Path(saved).resolve().relative_to(uploads)
            assert Path(saved).suffix in {".md", ".txt"}
    for name in ("../../evil", "a/b", "..\\evil"):
        try:
            path = rag_form.save_prompt_as(cfg, name, "text")
        except (ValueError, OSError):
            continue
        if path:
            Path(path).resolve().relative_to(prompts)


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
def test_run_ids_with_odd_characters_do_not_read_outside_commands(ui_client, cfg, tmp_path):
    (tmp_path / "secret.json").write_text('{"leak": true}', encoding="utf-8")
    for bad in ("..%2f..%2fsecret", "%2e%2e", "....//secret", "x" * 400):
        res = ui_client.get(f"/v1/runs/{bad}")
        assert res.status_code in {400, 404, 422}, (bad, res.status_code)
        assert "leak" not in res.text


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
def test_settings_whitelist_for_attach_mode(ui_client, cfg):
    cfg.ui_attach_mode = "manual"
    ui_client.post(
        "/settings",
        data={"attach_mode": 'auto"\n[evil]', "preset": "oa"},
        follow_redirects=False,
    )
    assert cfg.ui_attach_mode == "manual"
    ui_client.post("/settings", data={"attach_mode": "AUTO", "preset": "oa"}, follow_redirects=False)
    assert cfg.ui_attach_mode == "auto"


# --- Host header: documented absence of a Host gate ---------------------------


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
def test_foreign_host_header_is_not_gated_by_the_app(ui_client):
    """The only network guard is the loopback bind (see SECURITY.md).

    There is no TrustedHost/Origin middleware, so a foreign Host header is served
    as-is. If Host checking is added, update this test and the docs together.
    """
    res = ui_client.get("/healthz", headers={"Host": "evil.example"})
    if res.status_code == 404:
        res = ui_client.get("/wanted", headers={"Host": "evil.example"})
    assert res.status_code == 200


# --- Attach at zero ------------------------------------------------------------


def _wanted_env(cfg, monkeypatch, *, with_pending: bool):
    from paperful.store import Manifest, Record, STATUS_OK
    from paperful.ui import jobs

    class _Item:
        def __init__(self, key, doi, has_pdf):
            self.key, self.title, self.doi = key, key, doi
            self.has_pdf, self.year, self.arxiv_id, self.url = has_pdf, 2024, None, ""

    manifest = Manifest(cfg.manifest_path)
    items = [_Item("K1", "10.1/a", False)]
    if with_pending:
        manifest.write(
            Record(
                itemKey="K1",
                status=STATUS_OK,
                doi="10.1/a",
                pdf_doi="10.1/a",
                source="unpaywall",
                path="K1.pdf",
            )
        )
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))


def _attach_button(html: str) -> str:
    import re

    match = re.search(r"<button[^>]*id=\"attach-btn\"[^>]*>", html)
    assert match, "attach button missing"
    return match.group(0)


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
def test_attach_button_disabled_at_zero_and_enabled_with_pending(ui_client, cfg, monkeypatch):
    _wanted_env(cfg, monkeypatch, with_pending=False)
    ui_client.cookies.set("pf_collection", "ocean")
    zero = _attach_button(ui_client.get("/wanted").text)
    assert 'data-attach-count="0"' in zero
    assert "disabled" in zero

    _wanted_env(cfg, monkeypatch, with_pending=True)
    one = _attach_button(ui_client.get("/wanted").text)
    assert 'data-attach-count="1"' in one
    assert "disabled" not in one


@pytest.mark.skipif(fastapi_missing, reason="paperful[serve] extra missing")
def test_attach_post_at_zero_is_409_and_writes_nothing(ui_client, cfg, monkeypatch):
    from paperful.ui import jobs

    _wanted_env(cfg, monkeypatch, with_pending=False)
    wrote: list[list[str]] = []
    monkeypatch.setattr(jobs, "_attach_keys", lambda _c, keys: wrote.append(keys) or 0)
    ui_client.cookies.set("pf_collection", "ocean")
    res = ui_client.post("/wanted/attach", data={}, follow_redirects=False)
    assert res.status_code == 409
    assert "no attachable" in res.json()["error"]
    assert wrote == []
    res = ui_client.post("/wanted/attach", data={"keys": ["K1"]}, follow_redirects=False)
    assert res.status_code == 409
    assert wrote == []


# --- Grab never attaches by default -------------------------------------------


def test_grab_default_is_manual_and_does_not_attach(cfg, monkeypatch):
    from paperful.store import Manifest
    from paperful.ui import jobs
    from paperful.ui.pages import scope_fingerprint

    assert Config().ui_attach_mode == "manual"
    assert cfg.ui_attach_mode == "manual"
    assert jobs.grab_attaches(cfg) is False

    class _Item:
        key, title, doi, has_pdf, arxiv_id, url = "K1", "K1", "10.1/a", False, None, ""

    items = [_Item()]
    manifest = Manifest(cfg.manifest_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    attached: list[object] = []
    monkeypatch.setattr(jobs, "_attach_keys", lambda *_a, **_k: attached.append(1) or 0)
    captured: dict = {}
    monkeypatch.setattr("paperful.run_cmd.run_fetch", lambda console, c, **kw: captured.update(kw))
    jobs.run_fetch_fn = None
    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="C",
        preset="oa",
        keys=["K1"],
        fingerprint=scope_fingerprint(items, manifest),
        command_id="c1",
    )
    ok, msg = jobs.grab_run(cfg, token=token)
    assert ok, msg
    assert captured["no_attach"] is True
    assert captured["force_attach"] is False
    assert attached == []


def test_only_explicit_auto_mode_attaches(cfg):
    from paperful.ui import jobs

    for mode in ("manual", "", "AUTO ", "yes", "true"):
        cfg.ui_attach_mode = mode
        assert jobs.grab_attaches(cfg) is False, mode
    cfg.ui_attach_mode = "auto"
    assert jobs.grab_attaches(cfg) is True


# --- Optional lanes are never default -----------------------------------------


def test_optional_lanes_absent_from_default_source_lists():
    from paperful import config as C

    for lst in (C.DEFAULT_SOURCES, C.EOI_SOURCES, C.OA_SOURCES):
        assert "scihub" not in lst
        assert "scholar" not in lst
    for preset in C.SOURCE_PRESETS.values():
        assert "scihub" not in preset


def test_shipped_example_configs_do_not_enable_optional_lanes():
    import tomllib

    root = Path(__file__).resolve().parent.parent
    for name in ("config.example.toml", "config.minimal.toml"):
        data = tomllib.loads((root / name).read_text(encoding="utf-8"))
        sources = data.get("sources", [])
        assert sources, name
        assert "scihub" not in sources, name
        assert "scholar" not in sources, name


def test_fresh_config_has_no_scihub_source(cfg):
    assert "scihub" not in Config().sources
    assert "scihub" not in cfg.sources


def test_grab_passes_no_scihub_override(cfg, monkeypatch):
    from paperful.store import Manifest
    from paperful.ui import jobs
    from paperful.ui.pages import scope_fingerprint

    class _Item:
        key, title, doi, has_pdf, arxiv_id, url = "K1", "K1", "10.1/a", False, None, ""

    items = [_Item()]
    manifest = Manifest(cfg.manifest_path)
    monkeypatch.setattr(jobs, "_load_scope_items", lambda _c, _col: (items, manifest))
    captured: dict = {}
    monkeypatch.setattr("paperful.run_cmd.run_fetch", lambda console, c, **kw: captured.update(kw))
    jobs.run_fetch_fn = None
    token = commands.create_review_token(
        cfg,
        verb="preview_run",
        collection="C",
        preset="oa",
        keys=["K1"],
        fingerprint=scope_fingerprint(items, manifest),
        command_id="c2",
    )
    assert jobs.grab_run(cfg, token=token)[0]
    assert captured["scihub"] is None


def test_year_scope_drops_scihub_even_when_listed():
    from paperful.routing import filter_sources_for_year_scope

    assert "scihub" not in filter_sources_for_year_scope(["unpaywall", "scihub"], 2023)
    assert "scihub" in filter_sources_for_year_scope(["unpaywall", "scihub"], 2015)


# --- CDP stays on loopback ----------------------------------------------------


def test_cdp_launch_is_loopback_only(cfg, monkeypatch, tmp_path):
    from paperful import session

    launched: list[list[str]] = []

    class _Stop(Exception):
        pass

    def fake_popen(cmd, **_kw):
        launched.append(list(cmd))
        raise _Stop

    monkeypatch.setattr(session, "ensure_playwright", lambda auto_install=True: "")
    monkeypatch.setattr(session, "_prepare_profile_dir", lambda _c: tmp_path / "profile")
    monkeypatch.setattr(session, "login_url_for", lambda _c, _s: "https://example.test/login")
    monkeypatch.setattr(session.subprocess, "Popen", fake_popen)
    with pytest.raises(_Stop):
        session._login_via_system_chrome(
            cfg, "ezproxy", chrome=Path("/usr/bin/chrome"), confirm=lambda: None
        )
    cmd = launched[0]
    port_flag = next(a for a in cmd if a.startswith("--remote-debugging-port="))
    port = port_flag.split("=", 1)[1]
    assert port.isdigit()
    origins = next(a for a in cmd if a.startswith("--remote-allow-origins=")).split("=", 1)[1]
    assert set(origins.split(",")) == {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    assert "*" not in origins
    assert not any(a.startswith("--remote-debugging-address") for a in cmd)
