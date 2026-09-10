"""Session vault and Netscape export (no live browser)."""

from __future__ import annotations

from paperful import pipeline as pl
from paperful.cookies import (
    load_netscape_cookies,
    netscape_from_playwright,
    split_playwright_cookies,
    write_netscape,
)
from paperful.session import (
    SessionError,
    collect_pdf_from_page,
    export_cookies,
    load_meta,
    mark_slot,
    profile_ready,
    sessions_dir,
    vault_cookies_path,
)
from tests.conftest import PDF_BYTES


def test_netscape_from_playwright_roundtrip(tmp_path):
    cookies = [
        {
            "name": "SID",
            "value": "abc",
            "domain": ".google.com",
            "path": "/",
            "expires": 0,
            "secure": True,
            "httpOnly": True,
        },
        {
            "name": "session",
            "value": "ez",
            "domain": ".scpo.idm.oclc.org",
            "path": "/",
            "expires": 1700000000,
            "secure": True,
            "httpOnly": False,
        },
    ]
    text = netscape_from_playwright(cookies)
    assert "#HttpOnly_.google.com" in text
    assert "SID" in text
    path = tmp_path / "c.txt"
    write_netscape(path, cookies)
    loaded = load_netscape_cookies(path)
    assert any(c.name == "SID" and c.value == "abc" for c in loaded.jar)
    scholar, other = split_playwright_cookies(cookies)
    assert [c["name"] for c in scholar] == ["SID"]
    assert [c["name"] for c in other] == ["session"]


def test_export_cookies_writes_vault_and_compat(cfg, tmp_path):
    cookies = [
        {
            "name": "SID",
            "value": "g",
            "domain": ".google.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        },
        {
            "name": "proxy",
            "value": "e",
            "domain": ".idm.oclc.org",
            "path": "/",
            "secure": True,
        },
    ]
    written = export_cookies(cfg, cookies)
    assert vault_cookies_path(cfg) in written
    assert vault_cookies_path(cfg).is_file()
    assert (cfg.scholar_cookies or cfg.state_dir / "scholar-cookies.txt").is_file()
    assert (cfg.ezproxy_cookies or cfg.state_dir / "ezproxy-cookies.txt").is_file()
    client = pl.make_client(cfg)
    names = {c.name for c in client.cookies.jar}
    assert "SID" in names and "proxy" in names


def test_profile_ready_after_mark_slot(cfg, tmp_path):
    assert not profile_ready(cfg)
    sessions_dir(cfg).mkdir(parents=True)
    (sessions_dir(cfg) / "chromium").mkdir()
    mark_slot(cfg, "scholar")
    assert profile_ready(cfg)
    meta = load_meta(cfg)
    assert "scholar" in meta["slots"]
    assert "logged_in_at" in meta["slots"]["scholar"]


def test_login_url_ezproxy_requires_base(cfg):
    from paperful.session import SessionError, login_url_for

    cfg.ezproxy_base = ""
    try:
        login_url_for(cfg, "ezproxy")
        raise AssertionError("expected SessionError")
    except SessionError:
        pass
    cfg.ezproxy_base = "https://scpo.idm.oclc.org/login?url="
    assert "sciencedirect" in login_url_for(cfg, "ezproxy")


def test_ensure_sessions_dir_chmod(cfg):
    from paperful.session import dump_profile_cookies, ensure_sessions_dir, SessionError

    d = ensure_sessions_dir(cfg)
    assert d.is_dir()
    mode = d.stat().st_mode & 0o777
    assert mode == 0o700 or mode == 0o755  # umask may strip bits on some hosts
    try:
        dump_profile_cookies(cfg)
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        msg = str(exc).lower()
        assert "chromium" in msg or "htmlpdf" in msg or "not installed" in msg


class _FakeResp:
    def __init__(self, body, url, headers=None):
        self._body = body
        self.url = url
        self.headers = headers or {}

    def body(self):
        return self._body


class _FakeDownload:
    def __init__(self, path, url):
        self._path = path
        self.url = url

    def path(self):
        return self._path


class _FakeLoc:
    def __init__(self, n, click=None):
        self._n = n
        self._click = click
        self.first = self

    def count(self):
        return self._n

    def click(self, timeout=5000):
        if self._click:
            self._click()


class _FakePage:
    def __init__(self, resp=None, goto_error=None, download=None, locators=None):
        self._resp = resp
        self._goto_error = goto_error
        self._download = download
        self._handlers: dict[str, list] = {}
        self._locators = locators or {}

    def on(self, event, cb):
        self._handlers.setdefault(event, []).append(cb)

    def remove_listener(self, event, cb):
        lst = self._handlers.get(event, [])
        if cb in lst:
            lst.remove(cb)

    def locator(self, selector):
        return self._locators.get(selector, _FakeLoc(0))

    def goto(self, url, **kwargs):
        if self._download:
            for cb in self._handlers.get("download", []):
                cb(self._download)
        if self._goto_error:
            raise self._goto_error
        if self._resp is not None:
            for cb in self._handlers.get("response", []):
                cb(self._resp)
        return self._resp


def test_collect_pdf_from_page_uses_pdf_response():
    page = _FakePage(
        resp=_FakeResp(
            PDF_BYTES,
            "https://x.test/a.pdf",
            headers={"content-type": "application/pdf"},
        )
    )
    data, final = collect_pdf_from_page(page, "https://x.test/a.pdf")
    assert data == PDF_BYTES
    assert final.endswith("a.pdf")


def test_collect_pdf_from_page_uses_download_when_goto_aborts(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(PDF_BYTES)
    page = _FakePage(
        goto_error=RuntimeError("Download is starting"),
        download=_FakeDownload(path, "https://x.test/a.pdf"),
    )
    data, final = collect_pdf_from_page(page, "https://x.test/a.pdf")
    assert data == PDF_BYTES
    assert final.endswith("a.pdf")


def test_collect_pdf_from_page_raises_when_html_only():
    page = _FakePage(
        resp=_FakeResp(
            b"<html>article</html>",
            "https://x.test/article",
            headers={"content-type": "text/html"},
        )
    )
    try:
        collect_pdf_from_page(page, "https://x.test/article")
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert "PDF" in str(exc)
