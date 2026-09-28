"""Local browser session vault: one Chromium profile for Scholar, EZProxy, publishers.

Uses Playwright (core dependency). Headed `session login` prefers the system
Chrome/Edge binary (no automation flags) so Google SSO works, then attaches
over CDP to export cookies into the vault. Chromium browsers for the Playwright
fallback install on first need. Never stores passwords.
"""

from __future__ import annotations

import json
import os
import queue
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
from .download import looks_like_pdf
from .page_signals import (
    classify_page_block,
    format_miss,
    host_label,
    is_search_engine_host,
    looks_like_login_page,
    same_site,
)
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
    """True when Playwright's Chromium binary is on disk.

    Uses ``playwright install --dry-run`` instead of ``sync_playwright()``.
    Starting the sync driver solely to read ``executable_path`` leaves pending
    connection tasks; the next ``BrowserSession`` (or process exit) then prints
    ``TargetClosedError`` / "Task was destroyed" noise on ``doctor --probe``.
    """
    if not playwright_available():
        return False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in result.stdout.splitlines():
        # First location is Chromium (ffmpeg / headless shell follow).
        if "Install location:" in line:
            return Path(line.split(":", 1)[1].strip()).is_dir()
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


def _wait_cdp(
    port: int,
    *,
    timeout_s: float = 45.0,
    proc: subprocess.Popen[Any] | None = None,
    profile: Path | None = None,
) -> None:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            hint = ""
            if profile is not None:
                hint = (
                    f" Another process is likely using the Paperful profile "
                    f"({profile}) — stop other paperful run/doctor/status "
                    f"--probe jobs and retry."
                )
            raise SessionError(
                f"Chrome exited before opening a debug port on 127.0.0.1:{port}."
                + hint
            )
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if getattr(resp, "status", 200) == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.2)
    hint = ""
    if profile is not None:
        hint = (
            f" If no window appeared, close other Chrome using "
            f"{profile} and retry."
        )
    raise SessionError(
        f"Chrome did not open a debug port on 127.0.0.1:{port}"
        + (f" ({last_err})" if last_err else "")
        + hint
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
    scholar_path = cfg.scholar_cookie_path
    ez_path = cfg.ezproxy_cookie_path
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
        _wait_cdp(port, proc=proc, profile=user_dir)
        confirm()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # no_defaults skips Browser.setDownloadBehavior / focus overrides
            # that break attach on some system Chrome builds ("Browser context
            # management is not supported"). We only need cookies.
            try:
                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}",
                    no_defaults=True,
                )
            except TypeError:
                # Playwright < 1.60 has no no_defaults kwarg.
                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}"
                )
            except Exception as exc:
                raise SessionError(
                    f"Could not attach to Chrome over CDP ({exc}). "
                    "Close other Chrome windows using this profile, retry, "
                    "or use --engine playwright."
                ) from exc
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


_PDF_CLICKS = (
    ("a[href*='pdfft']", "click:pdfft"),
    ("a[href*='/pdf'][href*='download']", "click:download"),
    ("a[data-aa-name='pdf-download']", "click:pdf-download"),
    ("a#pdfLink", "click:pdfLink"),
    ("a:has-text('Download PDF')", "click:Download PDF"),
    ("button:has-text('Download PDF')", "click:Download PDF"),
    ("a:has-text('View PDF')", "click:View PDF"),
    ("button:has-text('View PDF')", "click:View PDF"),
    ("a:has-text('Full text PDF')", "click:Full text PDF"),
    ("a[href$='.pdf']", "click:.pdf"),
)
_MAX_EXTRACT_NAV = 3
_SSO_WAIT_S = 15.0
_NETWORKIDLE_MS = 8_000
_VIEWER_SELECTORS = (
    "iframe[src*='.pdf']",
    "embed[src*='.pdf']",
    "embed[type*='pdf']",
)


def _playwright_pdf_miss(page: Any, url: str, *, clicked: bool) -> str:
    """Why the click-and-download pass left without a PDF."""
    final = url
    try:
        current = getattr(page, "url", None)
        if current:
            final = str(current)
    except Exception:
        final = url
    text = ""
    try:
        text = page.inner_text("body")[:4000]
    except Exception:
        text = ""
    html = ""
    try:
        html = str(page.content() or "")[:4000]
    except Exception:
        html = ""
    if looks_like_login_page(final, text or html):
        label = "login"
    else:
        label = classify_page_block(text)
        if label is None:
            label = (
                "clicked download control, no PDF"
                if clicked
                else "no download control"
            )
    return format_miss(label, final)


def _page_url(page: Any, fallback: str) -> str:
    current = getattr(page, "url", None)
    return str(current or fallback)


def _page_text(page: Any) -> str:
    try:
        return str(page.inner_text("body") or "")[:4000]
    except Exception:
        return ""


def _page_html(page: Any) -> str:
    try:
        return str(page.content() or "")
    except Exception:
        return ""


def _followable(target: str, origin: str) -> bool:
    host = host_label(target)
    if not host or is_search_engine_host(host):
        return False
    if "idm.oclc.org" in host or "idm.oclc.org" in host_label(origin):
        return True
    return same_site(target, origin)


def collect_pdf_from_page(
    page: Any,
    url: str,
    timeout_ms: int = 60_000,
    playbooks: list[Any] | None = None,
) -> tuple[bytes, str, str]:
    """Drive a Playwright page to `url` and return PDF bytes, final URL, win kind.

    After the navigation body / download event, waits out an SSO interstitial,
    follows a playbook rewrite, then HTML PDF links, click controls, and a
    PDF viewer iframe. A rewrite that is not a PDF falls through. Raises
    SessionError if nothing looks like a PDF.
    """
    from .sources.landing import extract_pdf_urls, rewrite_known_pdf_url

    found: list[tuple[bytes, str, str]] = []
    pending = {"win": "body"}
    visited: set[str] = set()
    saw_login = False

    def _take(data: bytes, final: str, win: str | None = None) -> None:
        if found or not data or not looks_like_pdf(data):
            return
        found.append((data, final, win or pending["win"]))

    def on_download(download: Any) -> None:
        try:
            path = download.path()
            if path:
                _take(
                    Path(path).read_bytes(),
                    str(getattr(download, "url", url)),
                    pending["win"] if str(pending["win"]).startswith("click:") else "download",
                )
        except Exception:
            return

    def on_response(response: Any) -> None:
        try:
            headers = {
                str(k).lower(): str(v) for k, v in (response.headers or {}).items()
            }
            ctype = headers.get("content-type", "")
            disp = headers.get("content-disposition", "")
            if "application/pdf" not in ctype and ".pdf" not in disp.lower():
                return
            _take(response.body(), str(getattr(response, "url", url)))
        except Exception:
            return

    def _goto(target: str, win: str, *, force: bool = False) -> None:
        key = target.split("?", 1)[0]
        if key in visited:
            return
        if not force and not _followable(target, _page_url(page, url)):
            return
        visited.add(key)
        pending["win"] = win
        try:
            resp = page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            resp = None
        if found:
            return
        if resp is not None:
            try:
                _take(resp.body(), str(getattr(resp, "url", target)))
            except Exception:
                pass
        elif not found:
            deadline = time.time() + min(8.0, timeout_ms / 1000)
            while time.time() < deadline and not found:
                time.sleep(0.2)

    page.on("download", on_download)
    page.on("response", on_response)
    try:
        _goto(url, "body", force=True)
        if found:
            return found[0]
        try:
            page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_MS)
        except Exception:
            pass
        if found:
            return found[0]
        if looks_like_login_page(_page_url(page, url), _page_text(page) or _page_html(page)):
            saw_login = True
            start_host = host_label(_page_url(page, url))
            deadline = time.time() + _SSO_WAIT_S
            while time.time() < deadline and not found:
                if host_label(_page_url(page, url)) != start_host:
                    break
                time.sleep(0.2)
            if found:
                data, final, _win = found[0]
                return data, final, "sso+" + _win
            if host_label(_page_url(page, url)) == start_host:
                raise SessionError(
                    format_miss("login", _page_url(page, url))
                )
        if found:
            return found[0]
        rewritten = rewrite_known_pdf_url(_page_url(page, url), playbooks)
        if rewritten:
            _goto(rewritten, "rewrite")
            if found:
                return found[0]
        origin = _page_url(page, url)
        html = _page_html(page)
        extracted: list[str] = []
        if html:
            try:
                extracted = extract_pdf_urls(html, origin, playbooks)
            except Exception:
                extracted = []
        hopped = 0
        for candidate in extracted:
            if hopped >= _MAX_EXTRACT_NAV:
                break
            if candidate.split("?", 1)[0] in visited:
                continue
            if not _followable(candidate, origin):
                continue
            hopped += 1
            _goto(candidate, "meta")
            if found:
                data, final, win = found[0]
                if saw_login and not win.startswith("sso+"):
                    win = "sso+" + win
                return data, final, win
        clicked = False
        for selector, win in _PDF_CLICKS:
            loc = page.locator(selector)
            try:
                if loc.count() == 0:
                    continue
                pending["win"] = win
                loc.first.click(timeout=5_000)
                clicked = True
            except Exception:
                continue
            click_deadline = time.time() + 10.0
            while time.time() < click_deadline and not found:
                time.sleep(0.2)
            if found:
                return found[0]
        for selector in _VIEWER_SELECTORS:
            loc = page.locator(selector)
            try:
                if loc.count() == 0:
                    continue
                src = loc.first.get_attribute("src")
            except Exception:
                continue
            if not src:
                continue
            from urllib.parse import urljoin

            _goto(urljoin(origin, str(src)), "viewer:iframe")
            if found:
                return found[0]
        raise SessionError(_playwright_pdf_miss(page, url, clicked=clicked))
    finally:
        for event, handler in (("download", on_download), ("response", on_response)):
            try:
                page.remove_listener(event, handler)
            except Exception:
                pass


class BrowserSession:
    """Lazy persistent Chromium for Scholar fetches, htmlpdf, and publisher PDFs.

    Playwright's sync API is greenlet-bound to the thread that starts it. OA
    workers share one session via a dedicated browser thread + job queue so
    concurrent ``fetch_*`` calls never cross threads.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._closed = False
        self._pw: Any = None
        self._ctx: Any = None
        self._owner_tid: int | None = None

    def available(self) -> bool:
        return playwright_available() and profile_ready(self.cfg)

    def _ensure_thread(self) -> None:
        with self._start_lock:
            if self._closed:
                raise SessionError("browser session is closed")
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name="paperful-browser",
                daemon=True,
            )
            self._thread.start()

    def _worker(self) -> None:
        self._owner_tid = threading.get_ident()
        while True:
            job = self._jobs.get()
            if job is None:
                self._shutdown_playwright()
                return
            job()

    def _run(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` on the browser thread; re-raise its exception here."""
        self._ensure_thread()
        box: dict[str, Any] = {}
        done = threading.Event()

        def job() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 — ferry to caller
                box["error"] = exc
            finally:
                done.set()

        self._jobs.put(job)
        done.wait()
        if "error" in box:
            raise box["error"]
        return box["result"]

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

    def _shutdown_playwright(self) -> None:
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

    def fetch_html(self, url: str, timeout_ms: int = 45_000) -> tuple[str, str]:
        def _do() -> tuple[str, str]:
            self._ensure()
            page = self._page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            return page.content(), str(page.url)

        return self._run(_do)

    def fetch_pdf(self, url: str, timeout_ms: int = 60_000) -> tuple[bytes, str, str]:
        """Navigate in the vault profile and return PDF bytes, final URL, win kind.

        ScienceDirect / Wiley / T&F often 403 a cookie-only GET; the same URL
        in this profile (campus SSO cookies + a real Chromium) can download.
        """

        def _do() -> tuple[bytes, str, str]:
            self._ensure()
            return collect_pdf_from_page(
                self._page(),
                url,
                timeout_ms=timeout_ms,
                playbooks=self.cfg.grey_playbooks,
            )

        return self._run(_do)

    def render_pdf(
        self,
        url: str,
        paywall_hints: tuple[str, ...],
        timeout_ms: int = 45_000,
    ) -> tuple[bytes, str, str]:
        def _do() -> tuple[bytes, str, str]:
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

        return self._run(_do)

    def close(self) -> None:
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is None:
            return
        self._jobs.put(None)
        thread.join(timeout=60)
        self._thread = None
        self._owner_tid = None
