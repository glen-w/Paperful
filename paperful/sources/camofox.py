"""Opt-in Camoufox recover lane via external camofox-browser REST server.

Not a default ``run`` source. Requires ``[camofox].enabled`` and a reachable
server at ``[camofox].base_url``. Runs after vault Playwright lanes and before
``browser_agent``. Does not reuse the vault Chromium SSO profile.
"""

from __future__ import annotations

from ..browser_agent import recover_start_url
from ..camofox_recover import run_camofox_recover
from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "camofox"


def find(item: Item, ctx: Context) -> Candidate:
    cfg = ctx.config
    if not cfg.camofox_enabled:
        return Candidate.miss(NAME, Outcome.SKIPPED, "camofox.enabled is false")
    if not (cfg.camofox_base_url or "").strip():
        return Candidate.miss(NAME, Outcome.SKIPPED, "camofox.base_url empty")
    url = recover_start_url(item)
    if not url:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI or URL")
    try:
        result = run_camofox_recover(cfg, item, url)
    except Exception as exc:
        return Candidate.miss(NAME, Outcome.ERROR, type(exc).__name__)
    if result.captcha:
        return Candidate.miss(NAME, Outcome.CAPTCHA, result.note or "captcha")
    if result.pdf_bytes:
        return Candidate(
            url=result.final_url or url,
            source=NAME,
            note=result.note or "camofox",
            content=result.pdf_bytes,
        )
    note = result.note or "not found"
    if note in {"camofox server unreachable", "camofox.base_url empty"}:
        return Candidate.miss(NAME, Outcome.SKIPPED, note)
    return Candidate.miss(NAME, Outcome.NOT_FOUND, note)
