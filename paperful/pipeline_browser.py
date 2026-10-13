"""Browser-agent handoff for :class:`paperful.pipeline.Pipeline`.

The batch order stays in the pipeline. These helpers only release Playwright
and decide whether recover lanes (``camofox`` / ``browser_agent``) may run.
"""

from __future__ import annotations

from typing import Any

from .routing import BROWSER_LANES, browser_lane_failed
from .zot import Item

_RECOVER_LANES = frozenset({"camofox", "browser_agent"})


def release_browser_for_agent(pipe: Any) -> None:
    """Drop Playwright so browser-use can own the vault Chromium profile."""
    if pipe.browser is None:
        return
    pipe.browser.close()
    pipe.browser = None
    pipe.ctx.browser = None


def skip_recover_without_lane_failure(
    pipe: Any, name: str, item: Item, attempts: list[str]
) -> bool:
    """Hold recover lanes on mixed runs until a vault lane has failed.

    Manual ``paperful recover`` uses ``sources=["browser_agent"]`` only, so
    the gate does not apply. ``camofox`` uses the same vault-miss gate.
    """
    if name not in _RECOVER_LANES:
        return False
    if not any(s in BROWSER_LANES for s in pipe.sources):
        return False
    if browser_lane_failed(attempts):
        return False
    attempts.append(f"{name}:skipped(no browser-lane failure)")
    with pipe._stats_lock:
        pipe.stats.note_source(name, "skipped")
    pipe._log_item(item, f"{name}: [dim]skipped[/] (no browser-lane failure)")
    return True
