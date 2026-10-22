"""``paperful session`` / ``ezproxy`` / ``scholar`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .config import Config
from .pipeline import make_client
from .sources import Context
def _confirm_session_login(console: Console) -> None:
    console.print("Complete login or CAPTCHA in the browser window, then press Enter.")
    try:
        input()
    except EOFError:
        pass


def _netscape_fallback_hint(console: Console, cookie_path: Path, *, scholar: bool) -> None:
    extra = (
        "Include [bold].google.com[/] and [bold]scholar.google.com[/]. "
        if scholar
        else "Include your EZProxy host (e.g. [bold]*.idm.oclc.org[/]). "
    )
    console.print(
        f"\n[yellow]No session yet.[/] Preferred: [bold]paperful session login "
        f"{'scholar' if scholar else 'ezproxy'}[/] "
        f"(needs [bold]paperful[htmlpdf][/]).\n"
        f"Or export a Netscape cookies.txt ({extra}) to:\n"
        f"  {cookie_path}\n"
        f"If an extension saved to your Desktop:\n"
        f"  mv ~/Desktop/cookies.txt {cookie_path}\n"
        f"  chmod 600 {cookie_path}\n"
        "Firefox: addons.mozilla.org → cookies.txt · Chrome: Get cookies.txt LOCALLY\n"
    )


def _probe_slot(console: Console, cfg: Config, slot: str) -> None:
    from . import cli_runtime as cli_mod

    from .cookies import cookie_domains, ezproxy_cookie_status
    from .session import (
        BrowserSession,
        load_vault_cookies,
        profile_ready,
        storage_state_path,
        vault_cookies_path,
    )
    from .sources import ezproxy as ez
    from .sources import scholar as gs

    browser = BrowserSession(cfg)
    ctx = Context(config=cfg, client=make_client(cfg), browser=browser)
    try:
        if slot == "ezproxy":
            cookie_path = cfg.ezproxy_cookie_path
            if (
                not cookie_path.is_file()
                and not vault_cookies_path(cfg).is_file()
                and not storage_state_path(cfg).is_file()
                and not profile_ready(cfg)
            ):
                _netscape_fallback_hint(console, cookie_path, scholar=False)
                cli_mod._print_exit_ladder()
                raise typer.Exit(2)
            ticket = ezproxy_cookie_status(load_vault_cookies(cfg), cfg.ezproxy_base)
            if ticket == "cas_only":
                console.print(
                    "[red]Session not ready:[/] CAS/IdP cookies only — "
                    "no EZProxy proxy-host ticket"
                )
                console.print(
                    "Run [bold]paperful session login ezproxy[/] and wait until a "
                    "publisher page loads through the proxy "
                    "(URL should include your idm.oclc.org host), then press Enter."
                )
                cli_mod._print_exit_ladder()
                raise typer.Exit(2)
            if ticket != "proxy_ticket":
                console.print(
                    "[red]Session not ready:[/] no campus proxy cookies in the vault"
                )
                console.print("Run [bold]paperful session login ezproxy[/] and retry.")
                cli_mod._print_exit_ladder()
                raise typer.Exit(2)
            ok, detail = ez.session_ok(ctx)
        else:
            cookie_path = cfg.scholar_cookie_path
            gs_domains = sorted(
                d
                for d in cookie_domains(ctx.client.cookies)
                if "google" in (d or "").lower()
            )
            if gs_domains:
                console.print(f"Loaded domains: {', '.join(gs_domains)}")
            if (
                not cookie_path.is_file()
                and not vault_cookies_path(cfg).is_file()
                and not profile_ready(cfg)
            ):
                _netscape_fallback_hint(console, cookie_path, scholar=True)
                cli_mod._print_exit_ladder()
                raise typer.Exit(2)
            ok, detail = gs.session_ok(ctx)
    finally:
        browser.close()
    if ok:
        console.print(f"[green]Session OK[/] — {detail}")
        if slot == "ezproxy":
            console.print("[dim]proxy-host ticket present in vault[/]")
        warn = getattr(browser, "inject_warning", None)
        if warn:
            console.print(f"[yellow]{warn}[/]")
        return
    console.print(f"[red]Session not ready:[/] {detail}")
    if slot == "scholar":
        console.print(
            "Solve the CAPTCHA in [bold]paperful session login scholar[/] "
            "(the same Chromium profile used during [bold]run[/]).\n"
            "A cookie file can still fail: Google often keys the pass to the browser, "
            "not cookies alone. Do not retry in a tight loop."
        )
    else:
        console.print("Run [bold]paperful session login ezproxy[/] and retry.")
    cli_mod._print_exit_ladder()
    raise typer.Exit(2)


def run_session_login(
    console: Console,
    *,
    slot: str,
    config: Path | None,
    engine: str,
) -> None:
    from . import session as sess

    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    key = slot.strip().lower()
    if key == "mendeley":
        from .mendeley import MendeleyAuthError, MendeleyClient

        console.print(
            "Opening Mendeley / Elsevier authorization in your browser.\n"
            "[dim]Redirect URI must match the app at "
            f"{cfg.mendeley_redirect_uri}[/]"
        )
        try:
            MendeleyClient(cfg).login()
        except MendeleyAuthError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2)
        console.print(
            "[green]Mendeley authorised.[/] Tokens in "
            f"{cfg.state_dir / 'mendeley-oauth.json'} (mode 0600)."
        )
        return
    if key not in sess.SLOTS:
        console.print(
            f"[red]Unknown slot {slot!r}.[/] Use scholar, ezproxy, or mendeley."
        )
        raise typer.Exit(1)
    eng = engine.strip().lower()
    if eng not in ("auto", "chrome", "playwright"):
        console.print("[red]--engine must be auto, chrome, or playwright.[/]")
        raise typer.Exit(1)
    console.print(f"Vault: {sess.sessions_dir(cfg)}")
    try:
        url = sess.login_url_for(cfg, key)
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"Opening: {url}")
    try:
        written = sess.login_headed(
            cfg,
            key,
            confirm=lambda: _confirm_session_login(console),
            on_note=lambda msg: console.print(f"[dim]{msg}[/]"),
            engine=eng,  # type: ignore[arg-type]
        )
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    for path in written:
        console.print(f"Wrote {path}")
    console.print(
        "[green]Session saved.[/] Probe with [bold]paperful session status --probe[/]."
    )
    if key == "ezproxy":
        console.print(
            "[dim]storage_state + Netscape include a proxy-host ticket "
            "(login probed a proxied publisher URL before saving).[/]"
        )


def run_session_status(
    console: Console,
    *,
    config: Path | None,
    probe: bool,
) -> None:
    from . import session as sess

    from .cookies import ezproxy_cookie_status

    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    console.print(f"Vault:     {sess.sessions_dir(cfg)}")
    console.print(f"Chromium:  {sess.chromium_dir(cfg)}")
    console.print(f"Ready:     {sess.profile_ready(cfg)}")
    meta = sess.load_meta(cfg)
    slots = meta.get("slots") or {}
    if slots:
        for name, info in slots.items():
            console.print(f"  {name}: {info}")
    else:
        console.print("[dim]No login slots recorded. Run paperful session login.[/]")
    vault = sess.vault_cookies_path(cfg)
    state = sess.storage_state_path(cfg)
    ez_path = cfg.ezproxy_cookie_path
    gs_path = cfg.scholar_cookie_path
    console.print(f"storage_state:  {'yes' if state.is_file() else 'no'} ({state})")
    console.print(f"Vault cookies:  {'yes' if vault.is_file() else 'no'} ({vault})")
    console.print(f"EZProxy file:  {'yes' if ez_path.is_file() else 'no'} ({ez_path})")
    console.print(f"Scholar file:   {'yes' if gs_path.is_file() else 'no'} ({gs_path})")
    if cfg.ezproxy_base:
        status = ezproxy_cookie_status(sess.load_vault_cookies(cfg), cfg.ezproxy_base)
        if status == "proxy_ticket":
            console.print("EZProxy cookies: [green]proxy-host ticket present[/]")
        elif status == "cas_only":
            console.print(
                "EZProxy cookies: [yellow]CAS/IdP only — no proxy ticket[/] "
                "(run [bold]paperful session login ezproxy[/] and wait for the publisher page)"
            )
        else:
            console.print(
                "EZProxy cookies: [yellow]none[/] "
                "(run [bold]paperful session login ezproxy[/])"
            )
    if not probe:
        return
    if cfg.ezproxy_base:
        _probe_slot(console, cfg, "ezproxy")
    if "scholar" in cfg.sources:
        _probe_slot(console, cfg, "scholar")


def run_session_export(console: Console, *, config: Path | None) -> None:
    from . import session as sess

    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    try:
        written = sess.dump_profile_cookies(cfg)
    except sess.SessionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    for path in written:
        console.print(f"Wrote {path}")


def run_ezproxy(
    console: Console,
    *,
    config: Path | None,
    open_browser: bool,
) -> None:
    from . import session as sess

    from .sources import ezproxy as ez

    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    cookie_path = cfg.ezproxy_cookie_path
    if not cfg.ezproxy_base:
        console.print("[red]ezproxy_base is empty in config.toml[/]")
        console.print(
            "Set it to your library EZProxy prefix, e.g. https://PREFIX.idm.oclc.org/login?url="
        )
        raise typer.Exit(1)

    console.print(f"Proxy:   {cfg.ezproxy_base}")
    console.print(f"Cookies: {cookie_path}")
    login_url = ez.proxify("https://www.sciencedirect.com/", cfg.ezproxy_base)
    if open_browser:
        if sess.playwright_available():
            run_session_login(console, slot="ezproxy", config=config, engine="auto")
            return
        import webbrowser

        console.print(f"Opening login: {login_url}")
        webbrowser.open(login_url)
        _netscape_fallback_hint(console, cookie_path, scholar=False)
        console.print("Then re-run: [bold]uv run paperful ezproxy --no-open[/]")
        raise typer.Exit(2)
    _probe_slot(console, cfg, "ezproxy")


def run_scholar(
    console: Console,
    *,
    config: Path | None,
    open_browser: bool,
) -> None:
    from . import session as sess

    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    cookie_path = cfg.scholar_cookie_path
    console.print(f"Scholar: {sess.SCHOLAR_URL}")
    console.print(f"Cookies: {cookie_path}")
    if open_browser:
        if sess.playwright_available():
            run_session_login(console, slot="scholar", config=config, engine="auto")
            return
        import webbrowser

        console.print(f"Opening: {sess.SCHOLAR_URL}")
        webbrowser.open(sess.SCHOLAR_URL)
        _netscape_fallback_hint(console, cookie_path, scholar=True)
        console.print("Then re-run: [bold]uv run paperful scholar --no-open[/]")
        raise typer.Exit(2)
    _probe_slot(console, cfg, "scholar")
