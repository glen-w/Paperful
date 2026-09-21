"""LLM browser recovery: last serial lane on `run` after vault browsers fail."""

from __future__ import annotations

from ..browser_agent import (
    RecoverResult,
    RecoverRunner,
    browser_agent_extra_available,
    recover_start_url,
    run_recover,
)
from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "browser_agent"

# Set by recover CLI for tests / injection.
_active_runner: RecoverRunner | None = None


def set_runner(runner: RecoverRunner | None) -> None:
    global _active_runner
    _active_runner = runner


def find(item: Item, ctx: Context) -> Candidate:
    if not ctx.config.llm_enabled:
        return Candidate.miss(NAME, Outcome.SKIPPED, "llm.enabled is false")
    if not browser_agent_extra_available():
        return Candidate.miss(
            NAME, Outcome.SKIPPED, "install paperful[browser-agent] (Python 3.11+)"
        )
    url = recover_start_url(item)
    if not url:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI or URL")
    try:
        if _active_runner is not None:
            result = _active_runner.run(ctx.config, item, url)
        else:
            result = run_recover(ctx.config, item, url)
    except Exception as exc:
        return Candidate.miss(NAME, Outcome.ERROR, type(exc).__name__)
    return _candidate_from_result(result)


def _candidate_from_result(result: RecoverResult) -> Candidate:
    if result.captcha:
        return Candidate.miss(NAME, Outcome.CAPTCHA, result.note or "captcha")
    if result.pdf_bytes:
        return Candidate(
            url="",
            source=NAME,
            note=result.note or "browser_agent",
            content=result.pdf_bytes,
        )
    return Candidate.miss(NAME, Outcome.NOT_FOUND, result.note or "not found")
