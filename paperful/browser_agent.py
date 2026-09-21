"""Browser-use recovery runner (optional extra paperful[browser-agent])."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
        if host.endswith("/v1"):
            host = host[:-3]
        llm = ChatOllama(model=llm_model_for_agent(cfg), host=host)

    with tempfile.TemporaryDirectory(prefix="paperful-recover-") as tmp:
        downloads = Path(tmp)
        profile = chromium_dir(cfg)
        browser = Browser(
            user_data_dir=profile,
            downloads_path=downloads,
            auto_download_pdfs=True,
            headless=True,
        )
        task = (
            f"Open {url} and download the full-text PDF for this work: "
            f"{item.title!r}. Dismiss cookie banners if needed. "
            "If you see a CAPTCHA or robot check you cannot pass, stop immediately. "
            "Do not purchase access. When a PDF is downloaded, finish."
        )
        agent = Agent(task=task, llm=llm, browser=browser)
        try:
            await asyncio.wait_for(
                agent.run(max_steps=cfg.browser_agent_max_steps),
                timeout=cfg.browser_agent_max_wall_s,
            )
        except asyncio.TimeoutError:
            return RecoverResult(None, "timeout", captcha=False)
        except Exception as exc:
            msg = str(exc).lower()
            if "captcha" in msg:
                return RecoverResult(None, "captcha", captcha=True)
            return RecoverResult(None, type(exc).__name__, captcha=False)

        pdf_bytes = _largest_pdf_in(downloads, cfg.min_pdf_bytes)
        if pdf_bytes:
            return RecoverResult(pdf_bytes, "browser_agent download")
        return RecoverResult(None, "no PDF in download folder", captcha=False)


def _largest_pdf_in(folder: Path, min_bytes: int) -> bytes | None:
    best: bytes | None = None
    for path in folder.rglob("*.pdf"):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not looks_like_pdf(data) or len(data) < min_bytes:
            continue
        if best is None or len(data) > len(best):
            best = data
    return best
