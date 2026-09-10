"""Local browser session vault: one Chromium profile for Scholar, EZProxy, publishers.

Requires `paperful[htmlpdf]` (Playwright). Cookies may be exported to Netscape files
for httpx; Scholar and htmlpdf prefer this persistent profile when it exists.
Never stores passwords.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config
from .cookies import split_playwright_cookies, write_netscape
from .sources.ezproxy import proxify

SLOTS = ("scholar", "ezproxy")
SCHOLAR_URL = "https://scholar.google.com/"
_META_NAME = "meta.json"
_CHROMIUM = "chromium"
_COOKIES_NAME = "cookies.txt"


class SessionError(Exception):
    """Configuration or Playwright error for the session vault."""


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


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


def login_headed(
    cfg: Config,
    slot: str,
    *,
    confirm: Callable[[], None],
) -> list[Path]:
    """Open headed Chromium on the persistent profile; dump cookies after confirm()."""
    if slot not in SLOTS:
        raise SessionError(f"unknown session slot {slot!r}")
    if not playwright_available():
        raise SessionError(
            "install paperful[htmlpdf] + playwright install chromium "
            "(or: playwright install chrome)"
        )
    url = login_url_for(cfg, slot)
    from playwright.sync_api import sync_playwright

    ensure_sessions_dir(cfg)
    user_dir = chromium_dir(cfg)
    user_dir.mkdir(parents=True, exist_ok=True)
    try:
        user_dir.chmod(0o700)
    except OSError:
        pass
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


def dump_profile_cookies(cfg: Config) -> list[Path]:
    """Headless open of the persistent profile to refresh Netscape exports."""
    if not playwright_available():
        raise SessionError("install paperful[htmlpdf] + playwright install chromium")
    if not chromium_dir(cfg).is_dir():
        raise SessionError(f"no Chromium profile yet ({chromium_dir(cfg)})")
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
