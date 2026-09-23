"""Browser-use recovery runner (optional extra paperful[browser-agent])."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Config
from .download import looks_like_pdf
from .llm import llm_model_for_agent
from .page_signals import classify_page_block, format_miss, host_label
from .session import chromium_dir, profile_ready
from .zot import Item


class BrowserAgentError(Exception):
    """Recover runner failed or is unavailable."""


@dataclass
class RecoverResult:
    pdf_bytes: bytes | None
    note: str
    captcha: bool = False


class RecoverRunner(Protocol):
    def run(self, cfg: Config, item: Item, url: str) -> RecoverResult: ...


def browser_agent_extra_available() -> bool:
    try:
        import browser_use  # noqa: F401
    except ImportError:
        return False
    # Importing browser-use sets the root logger to INFO. Do this after the
    # import so pyzotero's client does not print every local API call.
    _quiet_pyzotero_http_logs()
    return True


def _quiet_pyzotero_http_logs() -> None:
    """Drop pyzotero's per-request INFO lines.

    browser-use silences ``httpx`` but pyzotero vendors that client as
    ``httpx2``. Those ``INFO [httpx2] HTTP Request:`` lines show up while the
    library is listed and overwrite the fetch progress bar.
    """
    import logging

    for name in ("httpx2", "httpcore2"):
        log = logging.getLogger(name)
        log.setLevel(logging.ERROR)
        log.propagate = False


def recover_start_url(item: Item) -> str | None:
    if item.doi:
        return f"https://doi.org/{item.doi}"
    url = (item.url or "").strip()
    if url.lower().startswith(("http://", "https://")):
        return url
    return None


def default_runner() -> RecoverRunner:
    return _BrowserUseRunner()


def _browser_launch_kwargs() -> dict[str, object]:
    """Launch the same Chrome that wrote the session vault.

    ``session login`` prefers the system Chrome channel. browser-use's default
    is Playwright's bundled Chromium, which here is Chromium 120 and exits
    before the debug port opens on current macOS. ``channel="chrome"`` selects
    Google Chrome and falls back to other installed browsers if it is absent.
    Default extensions stay on. uBlock Origin Lite and the cookie-banner
    extension clear popups the agent would otherwise spend steps dismissing.
    browser-use has no per-extension switch, so Force Background Tab loads
    with them. A zero-byte cached ``.crx`` is skipped and re-downloaded.
    """
    return {"channel": "chrome", "enable_default_extensions": True}


def _drop_empty_extension_cache(cache: Path | None = None) -> None:
    """Delete zero-byte ``.crx`` files so browser-use downloads them again.

    browser-use treats any existing ``.crx`` as a finished download, including
    an empty file from a failed fetch. Those then fail extraction and the
    popup and cookie extensions never load.
    """
    if cache is None:
        try:
            from browser_use.config import CONFIG
        except ImportError:
            return
        cache = Path(CONFIG.BROWSER_USE_EXTENSIONS_DIR)
    if not cache.is_dir():
        return
    for crx in cache.glob("*.crx"):
        try:
            if crx.stat().st_size > 0:
                continue
            crx.unlink()
        except OSError:
            continue
        extracted = cache / crx.stem
        if extracted.is_dir() and not (extracted / "manifest.json").is_file():
            shutil.rmtree(extracted, ignore_errors=True)


def run_recover(
    cfg: Config,
    item: Item,
    url: str,
    *,
    runner: RecoverRunner | None = None,
) -> RecoverResult:
    if not browser_agent_extra_available():
        raise BrowserAgentError(
            "browser-use is not installed; uv sync --extra browser-agent "
            "(requires Python 3.11+)"
        )
    if not profile_ready(cfg):
        raise BrowserAgentError(
            "session vault not ready — run: paperful session login scholar"
        )
    impl = runner or default_runner()
    return impl.run(cfg, item, url)


class _BrowserUseRunner:
    def run(self, cfg: Config, item: Item, url: str) -> RecoverResult:
        return asyncio.run(_async_recover(cfg, item, url))


async def _async_recover(cfg: Config, item: Item, url: str) -> RecoverResult:
    from browser_use import Agent, Browser
    from browser_use.llm.ollama.chat import ChatOllama

    if cfg.llm_provider == "litellm":
        from browser_use.llm.litellm.chat import ChatLiteLLM

        llm = ChatLiteLLM(model=llm_model_for_agent(cfg))
    else:
        host = cfg.llm_base_url.rstrip("/")
        host = host.removesuffix("/v1")
        llm = ChatOllama(model=llm_model_for_agent(cfg), host=host)

    with tempfile.TemporaryDirectory(prefix="paperful-recover-") as tmp:
        downloads = Path(tmp)
        profile = chromium_dir(cfg)
        _drop_empty_extension_cache()
        browser = Browser(
            user_data_dir=profile,
            downloads_path=downloads,
            auto_download_pdfs=True,
            headless=True,
            **_browser_launch_kwargs(),
        )
        task = _recover_task(item, url)
        # DOM + element tree only unless [browser_agent] points at a vision tag.
        # browser-use defaults use_vision=True; text-only Ollama models 400 on
        # "Multimodal data provided".
        stop_reason: dict[str, str] = {}
        agent_ref: dict[str, Any] = {}

        async def should_stop() -> bool:
            current = agent_ref.get("agent")
            if current is None:
                return False
            miss = await _agent_abort_miss(current)
            if miss:
                stop_reason["miss"] = miss
                return True
            return False

        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            use_vision=False,
            extend_system_message=_RECOVER_SYSTEM_EXT,
            register_should_stop_callback=should_stop,
        )
        agent_ref["agent"] = agent
        try:
            await _run_until_pdf(
                agent,
                downloads,
                cfg.min_pdf_bytes,
                max_steps=cfg.browser_agent_max_steps,
                max_wall_s=cfg.browser_agent_max_wall_s,
                stop_reason=stop_reason,
            )
        except asyncio.TimeoutError:
            return _finish_recover(
                agent,
                downloads,
                cfg.min_pdf_bytes,
                "timeout",
                cfg.browser_agent_max_steps,
            )
        except InterruptedError:
            miss = stop_reason.get("miss") or "stopped"
            return _finish_recover(
                agent,
                downloads,
                cfg.min_pdf_bytes,
                miss,
                cfg.browser_agent_max_steps,
                captcha="captcha" in miss,
            )
        except Exception as exc:
            miss = "captcha" if "captcha" in str(exc).lower() else type(exc).__name__
            return _finish_recover(
                agent,
                downloads,
                cfg.min_pdf_bytes,
                miss,
                cfg.browser_agent_max_steps,
                captcha=miss == "captcha",
            )
        if stop_reason.get("miss"):
            return _finish_recover(
                agent,
                downloads,
                cfg.min_pdf_bytes,
                stop_reason["miss"],
                cfg.browser_agent_max_steps,
            )
        return _finish_recover(
            agent,
            downloads,
            cfg.min_pdf_bytes,
            "no PDF in download folder",
            cfg.browser_agent_max_steps,
        )


_WATCH_INTERVAL_S = 0.4

_RECOVER_SYSTEM_EXT = (
    "Never navigate to Google, Bing, DuckDuckGo, Scholar search, or any other "
    "search engine. If the DOI/publisher landing page has no free PDF (paywall, "
    "403, Request blocked, Cloudflare challenge, 'content not available'), call "
    "done immediately. Do not use the publisher's site search. Do not open new "
    "tabs or sites. Do not click support, contact, help, or cookie-settings links."
)

_SEARCH_ENGINE_SUFFIXES = (
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "yahoo.com",
    "baidu.com",
    "yandex.com",
    "yandex.ru",
)

# Path fragments that mean the agent left the article for a dead-end UI.
_DEAD_END_PATH_MARKERS = (
    "/support",
    "/contact",
    "/help",
    "/customer-support",
    "cookie",
    "consent",
)


def _is_search_engine_url(url: str) -> bool:
    """True for Google/Bing/etc. — agent wander that burns the step budget."""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in _SEARCH_ENGINE_SUFFIXES)


def _is_dead_end_url(url: str) -> bool:
    """True for support/help/cookie pages the agent opens instead of quitting."""
    from urllib.parse import urlparse

    path = (urlparse(url).path or "").lower()
    return any(m in path for m in _DEAD_END_PATH_MARKERS)


def _abort_miss_for_url(url: str) -> str | None:
    if _is_search_engine_url(url):
        return "left landing page (search engine)"
    if _is_dead_end_url(url):
        return "left landing page (support/help)"
    return None


def _agent_page_url_sync_probe(getter: Any) -> Any:
    """Call ``get_current_page_url``; may return a str or awaitable."""
    try:
        return getter()
    except Exception:
        return None


async def _agent_page_url(agent: Any) -> str | None:
    session = getattr(agent, "browser_session", None)
    if session is None:
        return None
    getter = getattr(session, "get_current_page_url", None)
    if getter is None:
        return None
    raw = _agent_page_url_sync_probe(getter)
    if hasattr(raw, "__await__"):
        try:
            raw = await raw
        except Exception:
            return None
    return raw if isinstance(raw, str) and raw else None


async def _agent_on_search_engine(agent: Any) -> bool:
    """Backward-compatible name: any URL that should abort recover."""
    return (await _agent_abort_miss(agent)) is not None


async def _agent_abort_miss(agent: Any) -> str | None:
    url = await _agent_page_url(agent)
    if not url:
        return None
    return _abort_miss_for_url(url)


def _recover_task(item: Item, url: str) -> str:
    """Build the browser-use task for one recover attempt.

    Keep the agent on the DOI/landing page. Searching Google after a 403 burned
    step and wall budget without PDFs in batch runs.
    """
    return (
        f"Open {url} and download the full-text PDF for this work: "
        f"{item.title!r}. Dismiss cookie banners if needed. "
        "If you see a CAPTCHA or robot check you cannot pass, stop immediately. "
        "If access is blocked (HTTP 403, 'Request blocked', Cloudflare/CloudFront "
        "error, 'content not available', or a paywall with no free PDF), stop "
        "immediately after that observation — do not keep clicking around. "
        "Never open Google, Bing, DuckDuckGo, or any search engine. "
        "Do not use the publisher site's search. Do not open new tabs. "
        "Do not click support, contact, help, or cookie-settings links. "
        "Stay on this URL's landing page (or its DOI redirect) only. "
        "Do not purchase access. When a PDF is downloaded, finish."
    )


async def _run_until_pdf(
    agent: Any,
    downloads: Path,
    min_bytes: int,
    *,
    max_steps: int,
    max_wall_s: float,
    interval_s: float = _WATCH_INTERVAL_S,
    stop_reason: dict[str, str] | None = None,
) -> None:
    """Run the agent, stopping as soon as a valid PDF is on disk.

    browser-use only checks ``state.stopped`` between steps, so a file that
    lands on click still burns the rest of the budget unless we call
    ``agent.stop()``. A watch task covers mid-step downloads; ``on_step_end``
    covers files that appear right after an action. Both wait for the file
    size to stay unchanged across two polls so a still-writing ``.pdf`` is
    not accepted early. Leaving for a search engine also stops the agent.
    """
    sizes: dict[str, int] = {}
    reasons = stop_reason if stop_reason is not None else {}

    async def on_step_end(current: Any) -> None:
        if _stable_largest_pdf(downloads, min_bytes, sizes) is not None:
            current.stop()
            return
        miss = await _agent_abort_miss(current)
        if miss:
            reasons["miss"] = miss
            current.stop()

    watch = asyncio.create_task(
        _stop_when_pdf_lands(
            agent,
            downloads,
            min_bytes,
            sizes=sizes,
            interval_s=interval_s,
            stop_reason=reasons,
        )
    )
    try:
        await asyncio.wait_for(
            agent.run(max_steps=max_steps, on_step_end=on_step_end),
            timeout=max_wall_s,
        )
    finally:
        watch.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watch


async def _stop_when_pdf_lands(
    agent: Any,
    downloads: Path,
    min_bytes: int,
    *,
    sizes: dict[str, int] | None = None,
    interval_s: float = _WATCH_INTERVAL_S,
    stop_reason: dict[str, str] | None = None,
) -> None:
    tracked = sizes if sizes is not None else {}
    reasons = stop_reason if stop_reason is not None else {}
    while True:
        if _stable_largest_pdf(downloads, min_bytes, tracked) is not None:
            agent.stop()
            return
        miss = await _agent_abort_miss(agent)
        if miss:
            reasons["miss"] = miss
            agent.stop()
            return
        await asyncio.sleep(interval_s)


def _finish_recover(
    agent: Any,
    downloads: Path,
    min_bytes: int,
    miss: str,
    max_steps: int,
    *,
    captcha: bool = False,
) -> RecoverResult:
    """Attach page, step, and download context to a generic miss or a hit."""
    result = _result_from_downloads(
        downloads, min_bytes, miss=miss, captcha=captcha
    )
    if result.pdf_bytes:
        how = _success_how(agent)
        if how:
            result.note = f"{result.note}; {how}"
        return result
    if miss not in {"no PDF in download folder", "stopped", "timeout"}:
        return result
    page_url, final_text, steps = _agent_observation(agent)
    label = classify_page_block(final_text)
    debris = _download_debris(downloads, min_bytes)
    if debris:
        base = debris
    elif label:
        base = label
    elif steps is not None and max_steps and steps >= max_steps:
        base = "step budget"
    else:
        base = "no downloadable pdf"
    result.note = format_miss(base, page_url, extra=_agent_snippet(final_text))
    if miss == "timeout":
        result.note = f"timeout; {result.note}"
    if steps is not None and max_steps:
        result.note = f"{result.note}; steps {steps}/{max_steps}"
    return result


def _agent_observation(agent: Any) -> tuple[str | None, str | None, int | None]:
    history = getattr(agent, "history", None)
    if history is None:
        return None, None, None
    final = _call(history, "final_result")
    steps = _call(history, "number_of_steps")
    urls = _call(history, "urls") or []
    page_url = None
    if isinstance(urls, list):
        for url in reversed(urls):
            if isinstance(url, str) and url:
                page_url = url
                break
    text = final if isinstance(final, str) else None
    count = steps if isinstance(steps, int) else None
    return page_url, text, count


def _call(obj: Any, name: str) -> Any:
    fn = getattr(obj, name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def _agent_snippet(text: str | None) -> str:
    if not text:
        return ""
    line = " ".join(text.split())
    return line


def _success_how(agent: Any) -> str | None:
    history = getattr(agent, "history", None)
    if history is None:
        return None
    names = _call(history, "action_names") or []
    if not isinstance(names, list) or not names:
        return None
    last = str(names[-1])
    page_url, _, _ = _agent_observation(agent)
    host = host_label(page_url)
    where = f" @{host}" if host else ""
    if any(token in last.lower() for token in ("click", "download")):
        return f"via {last}{where}"
    return None


def _download_debris(folder: Path, min_bytes: int) -> str | None:
    if not folder.is_dir():
        return None
    partial = False
    tiny = False
    try:
        paths = list(folder.iterdir())
    except OSError:
        return None
    for path in paths:
        name = path.name.lower()
        if name.endswith(".crdownload") or name.endswith(".tmp"):
            partial = True
            continue
        if not name.endswith(".pdf"):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        data = _pdf_bytes_from_path(path, min_bytes)
        if data is None and size > 0:
            tiny = True
    if partial:
        return "incomplete download"
    if tiny:
        return "download too small"
    return None


def _result_from_downloads(
    downloads: Path,
    min_bytes: int,
    *,
    miss: str,
    captcha: bool = False,
) -> RecoverResult:
    pdf_bytes = _largest_pdf_in(downloads, min_bytes)
    if pdf_bytes:
        return RecoverResult(pdf_bytes, "browser_agent download")
    return RecoverResult(None, miss, captcha=captcha)


def _pdf_bytes_from_path(path: Path, min_bytes: int) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not looks_like_pdf(data) or len(data) < min_bytes:
        return None
    return data


def _largest_pdf_in(folder: Path, min_bytes: int) -> bytes | None:
    best: bytes | None = None
    for path in folder.rglob("*.pdf"):
        data = _pdf_bytes_from_path(path, min_bytes)
        if data is None:
            continue
        if best is None or len(data) > len(best):
            best = data
    return best


def _stable_largest_pdf(
    folder: Path, min_bytes: int, sizes: dict[str, int]
) -> bytes | None:
    """Accept a PDF only after its size is unchanged across two polls.

    Chrome often writes a ``.pdf`` that is still growing; the header is
    already ``%PDF-`` so a single snapshot would stop too early.
    """
    current: dict[str, int] = {}
    best: bytes | None = None
    for path in folder.rglob("*.pdf"):
        try:
            n = path.stat().st_size
        except OSError:
            continue
        key = str(path)
        current[key] = n
        if sizes.get(key) != n:
            continue
        data = _pdf_bytes_from_path(path, min_bytes)
        if data is not None and (best is None or len(data) > len(best)):
            best = data
    sizes.clear()
    sizes.update(current)
    return best
