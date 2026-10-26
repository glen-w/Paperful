"""Cookie dump / EZProxy probe helpers (no live browser)."""

from __future__ import annotations

from types import SimpleNamespace

from paperful.session import _cdp_cookies_from_context, _probe_and_collect_cookies


class _Context:
    def __init__(self, cookies=None, cdp=None, fail_cdp=False, fail_cookies=False):
        self.pages = [SimpleNamespace()]
        self._cookies = cookies or []
        self._cdp = cdp
        self._fail_cdp = fail_cdp
        self._fail_cookies = fail_cookies

    def new_page(self):
        return SimpleNamespace()

    def new_cdp_session(self, _page):
        if self._fail_cdp:
            raise RuntimeError("no cdp")
        return SimpleNamespace(send=lambda _cmd: self._cdp)

    def cookies(self):
        if self._fail_cookies:
            raise RuntimeError("no cookies")
        return list(self._cookies)


def test_cdp_cookies_maps_samesite_and_expires():
    raw = {
        "cookies": [
            {"name": ""},
            {
                "name": "sid",
                "value": "1",
                "domain": ".ex.org",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "none",
                "expires": 1_700_000_000,
            },
            {
                "name": "lax",
                "value": "2",
                "sameSite": "strict",
                "expires": "nope",
            },
            {
                "name": "plain",
                "value": "3",
                "sameSite": "Lax",
            },
        ]
    }
    out = _cdp_cookies_from_context(_Context(cdp=raw))
    names = {c["name"]: c for c in out}
    assert names["sid"]["sameSite"] == "None"
    assert names["sid"]["expires"] == 1_700_000_000
    assert names["lax"]["sameSite"] == "Strict"
    assert "expires" not in names["lax"]
    assert names["plain"]["sameSite"] == "Lax"


def test_cdp_falls_back_to_context_cookies():
    ctx = _Context(cookies=[{"name": "a", "value": "1"}], fail_cdp=True)
    assert _cdp_cookies_from_context(ctx)[0]["name"] == "a"
    empty = _Context(fail_cdp=True, fail_cookies=True)
    assert _cdp_cookies_from_context(empty) == []


def test_probe_collects_on_ezproxy_nav_warning(cfg, monkeypatch):
    notes = []
    page = SimpleNamespace(
        url="https://login.ex.org/cas",
        goto=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("nav")),
        wait_for_load_state=lambda *_a, **_k: None,
        content=lambda: "<html>login</html>",
    )
    ctx = SimpleNamespace(
        pages=[page],
        new_page=lambda: page,
        new_cdp_session=lambda _p: (_ for _ in ()).throw(RuntimeError("cdp")),
        cookies=lambda: [{"name": "ezproxy", "value": "ticket"}],
    )
    monkeypatch.setattr("paperful.session.login_url_for", lambda *_a, **_k: "https://ez.example/start")
    cookies = _probe_and_collect_cookies(
        ctx, cfg, "ezproxy", on_note=notes.append
    )
    assert cookies[0]["name"] == "ezproxy"
    assert any("warning" in n.lower() for n in notes)
