"""Shared live progress bar. It stays under scrolling logs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


def item_progress(console: Console) -> Progress:
    """Live bar that stays below scrolling per-item logs."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


@contextmanager
def pause_live(progress: Progress | None) -> Iterator[None]:
    """Stop a Rich live bar so stdin prompts stay visible, then resume.

    Safe when ``progress`` is None or the Live display is not running (preflight
    / after the fetch bar has closed).
    """
    if progress is None or progress.disable or not progress.live.is_started:
        yield
        return
    progress.stop()
    try:
        yield
    finally:
        progress.start()
