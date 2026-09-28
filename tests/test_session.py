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
    assert cfg.scholar_cookie_path.is_file()
    assert cfg.ezproxy_cookie_path.is_file()
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
    def __init__(self, n, click=None, src=None):
        self._n = n
        self._click = click
        self._src = src
        self.first = self

    def count(self):
        return self._n

    def click(self, timeout=5000):
        if self._click:
            self._click()

    def get_attribute(self, name):
        if name == "src":
            return self._src
        return None


class _FakePage:
    def __init__(self, resp=None, goto_error=None, download=None, locators=None, html=""):
        self._resp = resp
        self._goto_error = goto_error
        self._download = download
        self._handlers: dict[str, list] = {}
        self._locators = locators or {}
        self._html = html
        self.url = resp.url if resp is not None else ""

    def on(self, event, cb):
        self._handlers.setdefault(event, []).append(cb)

    def remove_listener(self, event, cb):
        lst = self._handlers.get(event, [])
        if cb in lst:
            lst.remove(cb)

    def locator(self, selector):
        return self._locators.get(selector, _FakeLoc(0))

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def content(self):
        return self._html

    def inner_text(self, selector):
        return ""

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
    data, final, win = collect_pdf_from_page(page, "https://x.test/a.pdf")
    assert data == PDF_BYTES
    assert final.endswith("a.pdf")
    assert win == "body"


def test_collect_pdf_from_page_uses_download_when_goto_aborts(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(PDF_BYTES)
    page = _FakePage(
        goto_error=RuntimeError("Download is starting"),
        download=_FakeDownload(path, "https://x.test/a.pdf"),
    )
    data, final, win = collect_pdf_from_page(page, "https://x.test/a.pdf")
    assert data == PDF_BYTES
    assert final.endswith("a.pdf")
    assert win == "download"


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
        assert "no download control" in str(exc)


def test_collect_pdf_from_page_names_paywall():
    class Page(_FakePage):
        url = "https://www.wiley.com/doi/abs/10.1/x"

        def inner_text(self, selector):
            return "Subscribe to continue reading this article"

    try:
        collect_pdf_from_page(
            Page(
                resp=_FakeResp(b"<html>", "https://www.wiley.com/doi/abs/10.1/x")
            ),
            "https://doi.org/10.1/x",
        )
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert "paywall @wiley.com" in str(exc)


def test_collect_pdf_from_page_follows_citation_meta():
    pdf_resp = _FakeResp(
        PDF_BYTES,
        "https://www.nature.com/articles/s1.pdf",
        headers={"content-type": "application/pdf"},
    )

    class Page(_FakePage):
        def goto(self, url, **kwargs):
            self.url = url
            if url.endswith(".pdf"):
                for cb in self._handlers.get("response", []):
                    cb(pdf_resp)
                return pdf_resp
            return super().goto(url, **kwargs)

    html = (
        '<html><head><meta name="citation_pdf_url" '
        'content="https://www.nature.com/articles/s1.pdf"></head></html>'
    )
    page = Page(
        resp=_FakeResp(b"<html>", "https://www.nature.com/articles/s1"),
        html=html,
    )
    page.url = "https://www.nature.com/articles/s1"
    data, final, win = collect_pdf_from_page(page, "https://www.nature.com/articles/s1")
    assert data == PDF_BYTES
    assert final.endswith("s1.pdf")
    assert win == "meta"


def test_collect_pdf_from_page_clicks_view_pdf(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(PDF_BYTES)
    page = _FakePage(
        resp=_FakeResp(b"<html>article</html>", "https://x.test/article"),
        html="<html>article</html>",
    )

    def click():
        for cb in page._handlers.get("download", []):
            cb(_FakeDownload(path, "https://x.test/a.pdf"))

    page._locators["a:has-text('View PDF')"] = _FakeLoc(1, click=click)
    data, _final, win = collect_pdf_from_page(page, "https://x.test/article")
    assert data == PDF_BYTES
    assert win == "click:View PDF"


def test_collect_pdf_from_page_uses_viewer_iframe():
    pdf_resp = _FakeResp(
        PDF_BYTES,
        "https://x.test/viewer/a.pdf",
        headers={"content-type": "application/pdf"},
    )

    class Page(_FakePage):
        def goto(self, url, **kwargs):
            self.url = url
            if url.endswith(".pdf"):
                for cb in self._handlers.get("response", []):
                    cb(pdf_resp)
                return pdf_resp
            return super().goto(url, **kwargs)

    page = Page(
        resp=_FakeResp(b"<html></html>", "https://x.test/article"),
        html="<html></html>",
        locators={
            "iframe[src*='.pdf']": _FakeLoc(1, src="https://x.test/viewer/a.pdf")
        },
    )
    data, final, win = collect_pdf_from_page(page, "https://x.test/article")
    assert data == PDF_BYTES
    assert final.endswith("a.pdf")
    assert win == "viewer:iframe"


def test_collect_pdf_from_page_waits_out_sso():
    pdf_resp = _FakeResp(
        PDF_BYTES,
        "https://www.nature.com/articles/s1.pdf",
        headers={"content-type": "application/pdf"},
    )

    class Page(_FakePage):
        def __init__(self):
            super().__init__(
                resp=_FakeResp(
                    b"<html>login</html>",
                    "https://federation.sciences-po.fr/cas/login",
                ),
                html="<html>central authentication service</html>",
            )
            self.url = "https://federation.sciences-po.fr/cas/login"
            self._polls = 0

        def inner_text(self, selector):
            return "central authentication service"

        @property
        def url(self):
            self._polls += 1
            if self._polls > 3:
                return "https://www.nature.com/articles/s1"
            return "https://federation.sciences-po.fr/cas/login"

        @url.setter
        def url(self, value):
            self._landed = value

        def content(self):
            if "nature.com" in self.url:
                return (
                    '<html><meta name="citation_pdf_url" '
                    'content="https://www.nature.com/articles/s1.pdf"></html>'
                )
            return self._html

        def goto(self, url, **kwargs):
            if url.endswith(".pdf"):
                for cb in self._handlers.get("response", []):
                    cb(pdf_resp)
                return pdf_resp
            return super().goto(url, **kwargs)

    data, final, win = collect_pdf_from_page(
        Page(), "https://federation.sciences-po.fr/cas/login"
    )
    assert data == PDF_BYTES
    assert win == "sso+meta"
    assert "nature.com" in final


def test_collect_pdf_from_page_fails_fast_on_stuck_sso(monkeypatch):
    import paperful.session as sess

    monkeypatch.setattr(sess, "_SSO_WAIT_S", 0.05)

    class Page(_FakePage):
        def __init__(self):
            super().__init__(
                resp=_FakeResp(
                    b"<html>login</html>",
                    "https://federation.sciences-po.fr/cas/login",
                ),
                html="<html>central authentication service</html>",
            )
            self.url = "https://federation.sciences-po.fr/cas/login"

        def inner_text(self, selector):
            return "central authentication service"

        def content(self):
            return self._html

    try:
        collect_pdf_from_page(
            Page(), "https://federation.sciences-po.fr/cas/login"
        )
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert "login @federation.sciences-po.fr" in str(exc)


def test_looks_like_vault_login_miss():
    from paperful.page_signals import looks_like_vault_login_miss

    assert looks_like_vault_login_miss("login @federation.sciences-po.fr")
    assert looks_like_vault_login_miss(
        "no download control @federation.sciences-po.fr"
    )
    assert not looks_like_vault_login_miss("blocked @linkinghub.elsevier.com")
    assert not looks_like_vault_login_miss("no download control @wiley.com")


def test_collect_pdf_from_page_rewrite_miss_falls_through():
    from paperful.playbooks import GreyPlaybook

    pdf_resp = _FakeResp(
        PDF_BYTES,
        "https://x.test/real.pdf",
        headers={"content-type": "application/pdf"},
    )
    html = (
        '<html><meta name="citation_pdf_url" content="https://x.test/real.pdf"></html>'
    )

    class Page(_FakePage):
        def goto(self, url, **kwargs):
            self.url = "https://x.test/article"
            if url.endswith("real.pdf"):
                for cb in self._handlers.get("response", []):
                    cb(pdf_resp)
                return pdf_resp
            resp = _FakeResp(b"<html>not a pdf</html>", url, headers={"content-type": "text/html"})
            return resp

    page = Page(
        resp=_FakeResp(b"<html>", "https://x.test/article"),
        html=html,
    )
    page.url = "https://x.test/article"
    book = GreyPlaybook(
        name="learned-x-test-rewrite",
        kind="rewrite",
        hosts=("x.test",),
        url_re=r"https://x\.test/article(?P<code>.*)",
        pdf_template="https://x.test/miss{code}",
    )
    data, final, win = collect_pdf_from_page(
        page, "https://x.test/article", playbooks=[book]
    )
    assert data == PDF_BYTES
    assert win == "meta"
    assert final.endswith("real.pdf")


def test_collect_pdf_from_page_skips_off_host_and_search():
    html = (
        '<html><a href="https://cdn.other.test/secret.pdf">PDF</a>'
        '<a href="https://scholar.google.com/a.pdf">PDF</a></html>'
    )
    page = _FakePage(
        resp=_FakeResp(b"<html>", "https://x.test/article", headers={"content-type": "text/html"}),
        html=html,
    )
    page.url = "https://x.test/article"
    try:
        collect_pdf_from_page(page, "https://x.test/article")
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert "no download control" in str(exc)


def test_collect_pdf_from_page_caps_extract_navigations():
    links = "".join(
        f'<a href="https://x.test/n{i}.pdf">PDF</a>' for i in range(4)
    )
    seen: list[str] = []

    class Page(_FakePage):
        def goto(self, url, **kwargs):
            seen.append(url)
            if url.endswith("n3.pdf"):
                resp = _FakeResp(
                    PDF_BYTES, url, headers={"content-type": "application/pdf"}
                )
                for cb in self._handlers.get("response", []):
                    cb(resp)
                return resp
            return _FakeResp(b"<html></html>", url, headers={"content-type": "text/html"})

    page = Page(
        resp=_FakeResp(b"<html>", "https://x.test/article"),
        html=f"<html>{links}</html>",
    )
    page.url = "https://x.test/article"
    try:
        collect_pdf_from_page(page, "https://x.test/article")
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert "no download control" in str(exc)
    assert [u for u in seen if u.endswith(".pdf")] == [
        "https://x.test/n0.pdf",
        "https://x.test/n1.pdf",
        "https://x.test/n2.pdf",
    ]


def test_browser_session_runs_on_dedicated_thread(cfg):
    """OA workers share one session; Playwright sync must stay on one thread."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from paperful.session import BrowserSession

    browser = BrowserSession(cfg)
    tids: list[int] = []
    caller_tids: list[int] = []

    def fake_ensure() -> None:
        if browser._ctx is None:
            browser._ctx = object()

    class _Page:
        url = "https://x.test/"

        def goto(self, *args, **kwargs):
            tids.append(threading.get_ident())

        def wait_for_load_state(self, *args, **kwargs):
            pass

        def content(self):
            return "<html/>"

    browser._ensure = fake_ensure  # type: ignore[method-assign]
    browser._page = lambda: _Page()  # type: ignore[method-assign]
    browser.available = lambda: True  # type: ignore[method-assign]

    def call() -> str:
        caller_tids.append(threading.get_ident())
        body, _ = browser.fetch_html("https://x.test/")
        return body

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            bodies = list(pool.map(lambda _: call(), range(24)))
        assert bodies == ["<html/>"] * 24
        assert len(tids) == 24
        assert len(set(tids)) == 1
        assert tids[0] not in set(caller_tids)
        assert browser._owner_tid == tids[0]
    finally:
        browser.close()
