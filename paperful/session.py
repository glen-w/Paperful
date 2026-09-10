"""Local browser session vault: one Chromium profile for Scholar, EZProxy, publishers.

Uses Playwright (core dependency). Headed `session login` prefers the system
Chrome/Edge binary (no automation flags) so Google SSO works, then attaches
over CDP to export cookies into the vault. Chromium browsers for the Playwright
fallback install on first need. Never stores passwords.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .config import Config
from .cookies import split_playwright_cookies, write_netscape
from .sources.ezproxy import proxify

SLOTS = ("scholar", "ezproxy")
SCHOLAR_URL = "https://scholar.google.com/"
_META_NAME = "meta.json"
_CHROMIUM = "chromium"
_COOKIES_NAME = "cookies.txt"
LoginEngine = Literal["auto", "chrome", "playwright"]

_SYSTEM_CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/google-chrome-stable"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path("/usr/bin/microsoft-edge"),
    Path("/usr/bin/microsoft-edge-stable"),
)
_SYSTEM_CHROME_WHICH = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    "microsoft-edge",
)


class SessionError(Exception):
    """Configuration or Playwright error for the session vault."""


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def chromium_installed() -> bool:
    """True when Playwright's Chromium binary is on disk."""
    if not playwright_available():
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).is_file()
    except Exception:
        return False


def ensure_playwright(*, auto_install: bool = True) -> str | None:
    """Ensure the Playwright package and Chromium browser are ready.

    Returns a short note if Chromium was just installed; raises SessionError
    when the package is missing or install fails.
    """
    if not playwright_available():
        raise SessionError(
            "Playwright is missing — run: uv sync (or: pip install 'paperful[htmlpdf]')"
        )
    if chromium_installed():
        return None
    if not auto_install:
        raise SessionError(
            "Chromium not installed — run: uv run playwright install chromium"
        )
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SessionError(
            f"failed to install Chromium ({exc}). "
            "Run: uv run playwright install chromium"
        ) from exc
    if not chromium_installed():
        raise SessionError(
            "Chromium still missing after install — run: "
            "uv run playwright install chromium"
        )
    return "Installed Playwright Chromium for this environment."


def find_system_chrome() -> Path | None:
    """Path to a real Chrome/Chromium/Edge binary, if installed."""
    for path in _SYSTEM_CHROME_CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    for name in _SYSTEM_CHROME_WHICH:
        found = shutil.which(name)
        if found:
            return Path(found)
    local = os.environ.get("LOCALAPPDATA", "")
    program = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    program86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    for base in (local, program, program86):
        if not base:
            continue
        for rel in (
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        ):
            path = Path(base) / rel
            if path.is_file():
                return path
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_cdp(port: int, *, timeout_s: float = 45.0) -> None:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if getattr(resp, "status", 200) == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.2)
    raise SessionError(
        f"Chrome did not open a debug port on 127.0.0.1:{port}"
        + (f" ({last_err})" if last_err else "")
    )


def _prepare_profile_dir(cfg: Config) -> Path:
    ensure_sessions_dir(cfg)
    user_dir = chromium_dir(cfg)
    user_dir.mkdir(parents=True, exist_ok=True)
    try:
        user_dir.chmod(0o700)
    except OSError:
        pass
    return user_dir


def sessions_dir(cfg: Config) -> Path:
    return cfg.state_dir / "sessions"


def chromium_dir(cfg: Config) -> Path:
    return sessions_dir(cfg) / _CHROMIUM


def meta_path(cfg: Config) -> Path:
    return sessions_dir(cfg) / _META_NAME


def vault_cookies_path(cfg: Config) -> Path:
    return sessions_dir(cfg) / _COOKIES_NAME


def ensure_sessions_dir(cfg: Config) -> Path:
    d = sessions_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def profile_ready(cfg: Config) -> bool:
    """True after at least one `session login` wrote meta.json."""
    return meta_path(cfg).is_file() and chromium_dir(cfg).is_dir()


def load_meta(cfg: Config) -> dict[str, Any]:
    path = meta_path(cfg)
    if not path.is_file():
        return {"slots": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"slots": {}}
    if not isinstance(data, dict):
        return {"slots": {}}
    slots = data.get("slots")
    if not isinstance(slots, dict):
        data["slots"] = {}
    return data


def _write_meta(cfg: Config, data: dict[str, Any]) -> None:
    ensure_sessions_dir(cfg)
    path = meta_path(cfg)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


def mark_slot(cfg: Config, slot: str) -> None:
    if slot not in SLOTS:
        raise SessionError(f"unknown session slot {slot!r}")
    data = load_meta(cfg)
    slots = data.setdefault("slots", {})
    slots[slot] = {"logged_in_at": time.time()}
    _write_meta(cfg, data)


def login_url_for(cfg: Config, slot: str) -> str:
    if slot == "scholar":
        return SCHOLAR_URL
    if slot == "ezproxy":
        if not cfg.ezproxy_base:
            raise SessionError("ezproxy_base is empty in config.toml")
        return proxify("https://www.sciencedirect.com/", cfg.ezproxy_base)
    raise SessionError(f"unknown session slot {slot!r}")


def _launch_persistent(p: Any, user_data_dir: Path, *, headed: bool, user_agent: str):
    common: dict[str, Any] = {
        "user_data_dir": str(user_data_dir),
        "headless": not headed,
        "viewport": {"width": 1280, "height": 800},
        "user_agent": user_agent,
        "accept_downloads": True,
        # Reduce automation fingerprints when Playwright must launch the browser.
        "ignore_default_args": ["--enable-automation"],
    }
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **common)
    except Exception:
        return p.chromium.launch_persistent_context(**common)


def export_cookies(cfg: Config, cookies: list[dict[str, Any]]) -> list[Path]:
    """Write vault + compat Netscape files. Returns paths written."""
    ensure_sessions_dir(cfg)
    written: list[Path] = []
    vault = vault_cookies_path(cfg)
    write_netscape(vault, cookies)
    written.append(vault)
    scholar, other = split_playwright_cookies(cookies)
    scholar_path = cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt")
    ez_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    if scholar:
        write_netscape(scholar_path, scholar)
        written.append(scholar_path)
    if other:
        write_netscape(ez_path, other)
        written.append(ez_path)
    return written


def _login_via_system_chrome(
    cfg: Config,
    slot: str,
    *,
    chrome: Path,
    confirm: Callable[[], None],
    on_note: Callable[[str], None] | None = None,
) -> list[Path]:
    """Start system Chrome without Playwright automation flags; export via CDP."""
    note = ensure_playwright(auto_install=True)
    if note and on_note:
        on_note(note)
    url = login_url_for(cfg, slot)
    user_dir = _prepare_profile_dir(cfg)
    port = _free_port()
    cmd = [
        str(chrome),
        f"--user-data-dir={user_dir}",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    if on_note:
        on_note(
            f"Opening system browser ({chrome.name}) — Google blocks "
            "Playwright-launched Chrome; this window is your normal browser."
        )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cookies: list[dict[str, Any]] = []
    try:
        _wait_cdp(port)
        confirm()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else None
            if context is None:
                raise SessionError(
                    "Chrome opened but has no browser context yet — "
                    "complete login, leave a tab open, then press Enter again."
                )
            cookies = list(context.cookies())
            # Close via CDP only (do not also terminate the process — that race
            # prints TargetClosedError / "Task was destroyed" after success).
            browser.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    written = export_cookies(cfg, cookies)
    mark_slot(cfg, slot)
    return written


def _login_via_playwright(
    cfg: Config,
    slot: str,
    *,
    confirm: Callable[[], None],
    on_note: Callable[[str], None] | None = None,
) -> list[Path]:
    note = ensure_playwright(auto_install=True)
    if note and on_note:
        on_note(note)
    if on_note:
        on_note(
            "Using Playwright-launched Chromium — Google SSO often fails here; "
            "prefer system Chrome (default) or install Google Chrome."
        )
    url = login_url_for(cfg, slot)
    from playwright.sync_api import sync_playwright

    user_dir = _prepare_profile_dir(cfg)
    cookies: list[dict[str, Any]] = []
    with sync_playwright() as p:
        context = _launch_persistent(
            p, user_dir, headed=True, user_agent=cfg.user_agent
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            confirm()
            cookies = list(context.cookies())
        finally:
            context.close()
    written = export_cookies(cfg, cookies)
    mark_slot(cfg, slot)
    return written


def login_headed(
    cfg: Config,
    slot: str,
    *,
    confirm: Callable[[], None],
    on_note: Callable[[str], None] | None = None,
    engine: LoginEngine = "auto",
) -> list[Path]:
    """Open a headed browser on the vault profile; dump cookies after confirm()."""
    if slot not in SLOTS:
        raise SessionError(f"unknown session slot {slot!r}")
    key = engine if engine in ("auto", "chrome", "playwright") else "auto"
    chrome = find_system_chrome()
    if key == "playwright":
        return _login_via_playwright(cfg, slot, confirm=confirm, on_note=on_note)
    if key == "chrome" and chrome is None:
        raise SessionError(
            "No system Chrome/Edge found. Install Google Chrome, or use "
            "--engine playwright (Google SSO may fail)."
        )
    if chrome is not None and key in ("auto", "chrome"):
        return _login_via_system_chrome(
            cfg, slot, chrome=chrome, confirm=confirm, on_note=on_note
        )
    return _login_via_playwright(cfg, slot, confirm=confirm, on_note=on_note)


def dump_profile_cookies(cfg: Config) -> list[Path]:
    """Headless open of the persistent profile to refresh Netscape exports."""
    if not chromium_dir(cfg).is_dir():
        raise SessionError(f"no Chromium profile yet ({chromium_dir(cfg)})")
    ensure_playwright(auto_install=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = _launch_persistent(
            p, chromium_dir(cfg), headed=False, user_agent=cfg.user_agent
        )
        try:
            cookies = list(context.cookies())
        finally:
            context.close()
    return export_cookies(cfg, cookies)


class BrowserSession:
    """Lazy persistent Chromium for Scholar fetches and htmlpdf (one lock)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._pw: Any = None
        self._ctx: Any = None

    def available(self) -> bool:
        return playwright_available() and profile_ready(self.cfg)

    def _ensure(self) -> None:
        if self._ctx is not None:
            return
        if not self.available():
            raise SessionError("browser session is not available")
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._ctx = _launch_persistent(
            self._pw,
            chromium_dir(self.cfg),
            headed=False,
            user_agent=self.cfg.user_agent,
        )

    def _page(self) -> Any:
        assert self._ctx is not None
        return self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def fetch_html(self, url: str, timeout_ms: int = 45_000) -> tuple[str, str]:
        with self._lock:
            self._ensure()
            page = self._page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            return page.content(), str(page.url)

    def render_pdf(
        self,
        url: str,
        paywall_hints: tuple[str, ...],
        timeout_ms: int = 45_000,
    ) -> tuple[bytes, str, str]:
        with self._lock:
            self._ensure()
            page = self._page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            body = ""
            try:
                body = page.inner_text("body")[:4000].lower()
            except Exception:
                pass
            if any(h in body for h in paywall_hints):
                return b"", str(page.url), "paywall"
            pdf = page.pdf(
                format="A4",
                print_background=True,
                margin={
                    "top": "12mm",
                    "bottom": "12mm",
                    "left": "12mm",
                    "right": "12mm",
                },
            )
            return pdf, str(page.url), "chromium print"

    def close(self) -> None:
        with self._lock:
            if self._ctx is not None:
                try:
                    self._ctx.close()
                except Exception:
                    pass
                self._ctx = None
            if self._pw is not None:
                try:
                    self._pw.stop()
                except Exception:
                    pass
                self._pw = None
