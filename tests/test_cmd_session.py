"""``paperful session`` / ``ezproxy`` / ``scholar`` decision tree (browser, vault and network stubbed)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from paperful import cli, cli_runtime
from paperful import session as sess
from paperful import session_cmd
from paperful.mendeley import MendeleyAuthError, MendeleyClient

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(cli, "console", Console(highlight=False, width=250, height=100))
    monkeypatch.setattr(cli_runtime, "console", cli.console)


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )
    return p


def _with_ezproxy(cfg_file):
    cfg_file.write_text(
        cfg_file.read_text() + '\nezproxy_base = "https://lib.idm.oclc.org/login?url="\n'
    )


def _ladder_spy(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(cli_runtime, "_print_exit_ladder", lambda *a, **k: calls.append(1))
    return calls


# --- session login --------------------------------------------------------------------


def test_login_unknown_slot_and_engine_are_exit_1(cfg_file):
    res = runner.invoke(cli.app, ["session", "login", "orcid", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "Unknown slot" in res.output
    res = runner.invoke(cli.app, ["session", "login", "scholar", "--engine", "firefox", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "--engine must be" in res.output


def test_login_mendeley_success_and_failure(cfg_file, monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr(MendeleyClient, "login", lambda self, **k: called.append(True) or {})
    ok = runner.invoke(cli.app, ["session", "login", "mendeley", "-c", str(cfg_file)])
    assert ok.exit_code == 0 and called and "Mendeley authorised" in ok.output
    assert "mendeley-oauth.json" in ok.output and "0600" in ok.output

    def boom(self, **k):
        raise MendeleyAuthError("client_id missing")

    monkeypatch.setattr(MendeleyClient, "login", boom)
    bad = runner.invoke(cli.app, ["session", "login", "mendeley", "-c", str(cfg_file)])
    assert bad.exit_code == 2 and "client_id missing" in bad.output


def test_login_scholar_saves_session(cfg_file, monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(sess, "login_url_for", lambda cfg, slot: f"https://login.test/{slot}")

    def fake_login(cfg, key, *, confirm, on_note, engine):
        seen.update(key=key, engine=engine)
        on_note("starting")
        return [tmp_path / "vault" / "cookies.json"]

    monkeypatch.setattr(sess, "login_headed", fake_login)
    res = runner.invoke(cli.app, ["session", "login", "Scholar", "--engine", "CHROME", "-c", str(cfg_file)])
    assert res.exit_code == 0, res.output
    assert seen == {"key": "scholar", "engine": "chrome"}
    assert "Opening: https://login.test/scholar" in res.output
    assert "Wrote" in res.output and "Session saved" in res.output
    assert "proxy-host ticket" not in res.output  # only EZProxy mentions the ticket


def test_login_ezproxy_mentions_ticket_probe(cfg_file, monkeypatch):
    monkeypatch.setattr(sess, "login_url_for", lambda cfg, slot: "https://x.test/")
    monkeypatch.setattr(sess, "login_headed", lambda *a, **k: [])
    res = runner.invoke(cli.app, ["session", "login", "ezproxy", "-c", str(cfg_file)])
    assert res.exit_code == 0 and "proxy-host ticket" in res.output


def test_login_errors_map_to_exit_codes(cfg_file, monkeypatch):
    def bad_url(cfg, slot):
        raise sess.SessionError("ezproxy_base is empty")

    monkeypatch.setattr(sess, "login_url_for", bad_url)
    res = runner.invoke(cli.app, ["session", "login", "ezproxy", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "ezproxy_base is empty" in res.output

    monkeypatch.setattr(sess, "login_url_for", lambda cfg, slot: "https://x.test/")

    def bad_login(*a, **k):
        raise sess.SessionError("Chrome would not start")

    monkeypatch.setattr(sess, "login_headed", bad_login)
    res = runner.invoke(cli.app, ["session", "login", "ezproxy", "-c", str(cfg_file)])
    assert res.exit_code == 2 and "Chrome would not start" in res.output


def test_confirm_prompt_tolerates_closed_stdin(monkeypatch):
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(EOFError()))
    session_cmd._confirm_session_login(Console(file=buf, highlight=False))
    assert "press Enter" in buf.getvalue()


# --- session status -------------------------------------------------------------------


def test_status_lists_vault_without_probe(cfg_file):
    res = runner.invoke(cli.app, ["session", "status", "-c", str(cfg_file)])
    assert res.exit_code == 0, res.output
    for label in ("Vault:", "Chromium:", "Ready:", "storage_state:  no", "Vault cookies:  no", "EZProxy file:  no", "Scholar file:   no"):
        assert label in res.output
    assert "No login slots recorded" in res.output
    assert "EZProxy cookies" not in res.output  # no ezproxy_base configured


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("proxy_ticket", "proxy-host ticket present"),
        ("cas_only", "CAS/IdP only"),
        ("empty", "none"),
    ],
)
def test_status_reports_ezproxy_cookie_state(cfg_file, monkeypatch, status, expected):
    _with_ezproxy(cfg_file)
    monkeypatch.setattr(sess, "load_vault_cookies", lambda cfg: [])
    monkeypatch.setattr("paperful.cookies.ezproxy_cookie_status", lambda cookies, base: status)
    res = runner.invoke(cli.app, ["session", "status", "-c", str(cfg_file)])
    assert res.exit_code == 0 and "EZProxy cookies:" in res.output and expected in res.output


def test_status_prints_recorded_slots(cfg_file, monkeypatch):
    monkeypatch.setattr(sess, "load_meta", lambda cfg: {"slots": {"scholar": {"at": "2026-01-01"}}})
    res = runner.invoke(cli.app, ["session", "status", "-c", str(cfg_file)])
    assert "scholar: {'at': '2026-01-01'}" in res.output
    assert "No login slots" not in res.output


def test_status_probe_runs_configured_slots_only(cfg_file, monkeypatch):
    probed: list[str] = []
    monkeypatch.setattr(session_cmd, "_probe_slot", lambda console, cfg, slot: probed.append(slot))
    runner.invoke(cli.app, ["session", "status", "--probe", "-c", str(cfg_file)])
    assert probed == []  # neither ezproxy_base nor scholar configured
    _with_ezproxy(cfg_file)
    cfg_file.write_text(cfg_file.read_text() + '\nsources = ["unpaywall", "scholar"]\n')
    runner.invoke(cli.app, ["session", "status", "--probe", "-c", str(cfg_file)])
    assert probed == ["ezproxy", "scholar"]


def test_session_export(cfg_file, monkeypatch, tmp_path):
    monkeypatch.setattr(sess, "dump_profile_cookies", lambda cfg: [tmp_path / "a.json", tmp_path / "b.txt"])
    ok = runner.invoke(cli.app, ["session", "export", "-c", str(cfg_file)])
    assert ok.exit_code == 0 and ok.output.count("Wrote") == 2

    def fail(cfg):
        raise sess.SessionError("no profile yet")

    monkeypatch.setattr(sess, "dump_profile_cookies", fail)
    bad = runner.invoke(cli.app, ["session", "export", "-c", str(cfg_file)])
    assert bad.exit_code == 2 and "no profile yet" in bad.output


# --- _probe_slot ----------------------------------------------------------------------


class _FakeBrowser:
    inject_warning = None

    def __init__(self, cfg):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def probe_env(monkeypatch):
    browsers: list[_FakeBrowser] = []

    def make(cfg):
        b = _FakeBrowser(cfg)
        browsers.append(b)
        return b

    monkeypatch.setattr(sess, "BrowserSession", make)
    monkeypatch.setattr(session_cmd, "make_client", lambda cfg: __import__("httpx").Client())
    monkeypatch.setattr(sess, "profile_ready", lambda cfg: False)
    monkeypatch.setattr(sess, "load_vault_cookies", lambda cfg: [])
    return browsers


def _probe(cfg_file, slot):
    cfg = cli_runtime._cfg(cfg_file)
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    code = 0
    try:
        session_cmd._probe_slot(Console(file=buf, highlight=False, width=200), cfg, slot)
    except Exception as exc:  # typer.Exit
        code = getattr(exc, "exit_code", getattr(exc, "code", 1))
    return code, buf.getvalue()


def test_probe_ezproxy_without_any_session_files_prints_fallback_hint(cfg_file, probe_env, monkeypatch):
    _with_ezproxy(cfg_file)
    ladder = _ladder_spy(monkeypatch)
    code, out = _probe(cfg_file, "ezproxy")
    assert code == 2 and "No session yet" in out and "cookies.txt" in out and "idm.oclc.org" in out
    assert ladder and probe_env[0].closed  # the browser is always closed


@pytest.mark.parametrize(
    ("ticket", "message"),
    [("cas_only", "CAS/IdP cookies only"), ("empty", "no campus proxy cookies")],
)
def test_probe_ezproxy_rejects_sessions_without_a_proxy_ticket(cfg_file, probe_env, monkeypatch, ticket, message):
    _with_ezproxy(cfg_file)
    _ladder_spy(monkeypatch)
    cfg = cli_runtime._cfg(cfg_file)
    cfg.ezproxy_cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.ezproxy_cookie_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr("paperful.cookies.ezproxy_cookie_status", lambda cookies, base: ticket)
    code, out = _probe(cfg_file, "ezproxy")
    assert code == 2 and message in out and "session login ezproxy" in out


def test_probe_ezproxy_ok_and_not_ok(cfg_file, probe_env, monkeypatch):
    _with_ezproxy(cfg_file)
    _ladder_spy(monkeypatch)
    cfg = cli_runtime._cfg(cfg_file)
    cfg.ezproxy_cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.ezproxy_cookie_path.write_text("x", encoding="utf-8")
    monkeypatch.setattr("paperful.cookies.ezproxy_cookie_status", lambda cookies, base: "proxy_ticket")
    from paperful.sources import ezproxy as ez

    monkeypatch.setattr(ez, "session_ok", lambda ctx: (True, "HTTP 200"))
    code, out = _probe(cfg_file, "ezproxy")
    assert code == 0 and "Session OK" in out and "proxy-host ticket present in vault" in out

    monkeypatch.setattr(ez, "session_ok", lambda ctx: (False, "login page"))
    code, out = _probe(cfg_file, "ezproxy")
    assert code == 2 and "Session not ready" in out and "login page" in out


def test_probe_scholar_hint_ok_and_captcha_advice(cfg_file, probe_env, monkeypatch):
    ladder = _ladder_spy(monkeypatch)
    code, out = _probe(cfg_file, "scholar")
    assert code == 2 and "scholar.google.com" in out and ladder

    cfg = cli_runtime._cfg(cfg_file)
    cfg.scholar_cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.scholar_cookie_path.write_text("x", encoding="utf-8")
    from paperful.sources import scholar as gs

    monkeypatch.setattr(gs, "session_ok", lambda ctx: (True, "results page"))
    code, out = _probe(cfg_file, "scholar")
    assert code == 0 and "Session OK" in out and "results page" in out

    monkeypatch.setattr(gs, "session_ok", lambda ctx: (False, "CAPTCHA"))
    code, out = _probe(cfg_file, "scholar")
    assert code == 2 and "CAPTCHA" in out and "tight loop" in out


def test_probe_surfaces_browser_injection_warning(cfg_file, probe_env, monkeypatch):
    cfg = cli_runtime._cfg(cfg_file)
    cfg.scholar_cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.scholar_cookie_path.write_text("x", encoding="utf-8")
    from paperful.sources import scholar as gs

    monkeypatch.setattr(gs, "session_ok", lambda ctx: (True, "ok"))
    monkeypatch.setattr(_FakeBrowser, "inject_warning", "cookies were not injected", raising=False)
    code, out = _probe(cfg_file, "scholar")
    assert code == 0 and "cookies were not injected" in out


# --- ezproxy / scholar wrappers ---------------------------------------------------------


def test_ezproxy_requires_base_then_routes(cfg_file, monkeypatch):
    res = runner.invoke(cli.app, ["ezproxy", "-c", str(cfg_file)])
    assert res.exit_code == 1 and "ezproxy_base is empty" in res.output

    _with_ezproxy(cfg_file)
    probed: list[str] = []
    monkeypatch.setattr(session_cmd, "_probe_slot", lambda console, cfg, slot: probed.append(slot))
    res = runner.invoke(cli.app, ["ezproxy", "--no-open", "-c", str(cfg_file)])
    assert res.exit_code == 0 and probed == ["ezproxy"]

    logins: list[str] = []
    monkeypatch.setattr(sess, "playwright_available", lambda: True)
    monkeypatch.setattr(session_cmd, "run_session_login", lambda console, **kw: logins.append(kw["slot"]))
    res = runner.invoke(cli.app, ["ezproxy", "-c", str(cfg_file)])
    assert res.exit_code == 0 and logins == ["ezproxy"]


def test_ezproxy_and_scholar_without_playwright_open_system_browser(cfg_file, monkeypatch):
    _with_ezproxy(cfg_file)
    opened: list[str] = []
    monkeypatch.setattr(sess, "playwright_available", lambda: False)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    res = runner.invoke(cli.app, ["ezproxy", "-c", str(cfg_file)])
    assert res.exit_code == 2 and "ezproxy --no-open" in res.output
    assert opened and "sciencedirect.com" in opened[0]
    res = runner.invoke(cli.app, ["scholar", "-c", str(cfg_file)])
    assert res.exit_code == 2 and "scholar --no-open" in res.output
    assert opened[-1] == sess.SCHOLAR_URL


def test_scholar_routes(cfg_file, monkeypatch):
    probed: list[str] = []
    monkeypatch.setattr(session_cmd, "_probe_slot", lambda console, cfg, slot: probed.append(slot))
    assert runner.invoke(cli.app, ["scholar", "--no-open", "-c", str(cfg_file)]).exit_code == 0
    assert probed == ["scholar"]
    logins: list[str] = []
    monkeypatch.setattr(sess, "playwright_available", lambda: True)
    monkeypatch.setattr(session_cmd, "run_session_login", lambda console, **kw: logins.append(kw["slot"]))
    assert runner.invoke(cli.app, ["scholar", "-c", str(cfg_file)]).exit_code == 0
    assert logins == ["scholar"]
