"""Shared live progress bar. It stays under scrolling logs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


def item_progress(
    console: Console, *, disable: bool = False, transient: bool = False
) -> Progress:
    """Live bar that stays below scrolling per-item logs.

    ``disable`` keeps the same call shape but draws nothing (``--json``, pipes).
    ``transient`` clears the bar when it stops (a spinner for one slow call).
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=transient,
        disable=disable,
    )


# A worker loop takes one of these and writes ``for x in track(xs):``.
Track = Callable[[Iterable[Any]], Iterator[Any]]


def _label_of(row: Any) -> str:
    """Short name for the row being worked on, or '' when it has none."""
    label = getattr(row, "label", None)
    return label[:48] if isinstance(label, str) else ""


def tracker(
    progress: Progress,
    description: str,
    *,
    label: Callable[[Any], str] = _label_of,
) -> Track:
    """Wrap a worker's loop in one bar task.

    The description names the row in hand, so a slow row is visible. The bar
    advances when the loop asks for the next row; ``break`` or an exception
    leaves it short, which is the truth.
    """

    def track(rows: Iterable[Any]) -> Iterator[Any]:
        todo = list(rows)
        task_id = progress.add_task(description, total=len(todo))
        for row in todo:
            name = label(row)
            if name:
                progress.update(
                    task_id, description=f"{description} [dim]· {escape(name)}[/]"
                )
            yield row
            progress.advance(task_id)
        progress.update(task_id, description=description)

    return track


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
