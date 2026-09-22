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

        return True
    except ImportError:
        return False


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
        task = (
            f"Open {url} and download the full-text PDF for this work: "
            f"{item.title!r}. Dismiss cookie banners if needed. "
            "If you see a CAPTCHA or robot check you cannot pass, stop immediately. "
            "Do not purchase access. When a PDF is downloaded, finish."
        )
        # DOM + element tree only unless [browser_agent] points at a vision tag.
        # browser-use defaults use_vision=True; text-only Ollama models 400 on
        # "Multimodal data provided".
        agent = Agent(task=task, llm=llm, browser=browser, use_vision=False)
        try:
            await _run_until_pdf(
                agent,
                downloads,
                cfg.min_pdf_bytes,
                max_steps=cfg.browser_agent_max_steps,
                max_wall_s=cfg.browser_agent_max_wall_s,
            )
        except asyncio.TimeoutError:
            return _result_from_downloads(downloads, cfg.min_pdf_bytes, miss="timeout")
        except Exception as exc:
            miss = "captcha" if "captcha" in str(exc).lower() else type(exc).__name__
            return _result_from_downloads(
                downloads,
                cfg.min_pdf_bytes,
                miss=miss,
                captcha=miss == "captcha",
            )
        return _result_from_downloads(
            downloads, cfg.min_pdf_bytes, miss="no PDF in download folder"
        )


_WATCH_INTERVAL_S = 0.4


async def _run_until_pdf(
    agent: Any,
    downloads: Path,
    min_bytes: int,
    *,
    max_steps: int,
    max_wall_s: float,
    interval_s: float = _WATCH_INTERVAL_S,
) -> None:
    """Run the agent, stopping as soon as a valid PDF is on disk.

    browser-use only checks ``state.stopped`` between steps, so a file that
    lands on click still burns the rest of the budget unless we call
    ``agent.stop()``. A watch task covers mid-step downloads; ``on_step_end``
    covers files that appear right after an action. Both wait for the file
    size to stay unchanged across two polls so a still-writing ``.pdf`` is
    not accepted early.
    """
    sizes: dict[str, int] = {}

    async def on_step_end(current: Any) -> None:
        if _stable_largest_pdf(downloads, min_bytes, sizes) is not None:
            current.stop()

    watch = asyncio.create_task(
        _stop_when_pdf_lands(
            agent, downloads, min_bytes, sizes=sizes, interval_s=interval_s
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
) -> None:
    tracked = sizes if sizes is not None else {}
    while True:
        if _stable_largest_pdf(downloads, min_bytes, tracked) is not None:
            agent.stop()
            return
        await asyncio.sleep(interval_s)


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
