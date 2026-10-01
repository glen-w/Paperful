"""Live progress bar helpers."""

from __future__ import annotations

import io
import sys

from rich.console import Console
from rich.progress import Progress

from paperful.progress import item_progress, pause_live, tracker


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _live_progress() -> Progress:
    console = Console(file=_TtyBuffer(), force_terminal=True)
    return item_progress(console)


def test_pause_live_stops_and_restarts():
    progress = _live_progress()
    progress.start()
    assert progress.live.is_started
    with pause_live(progress):
        assert not progress.live.is_started
    assert progress.live.is_started
    progress.stop()


def test_pause_live_noop_when_not_started_or_none():
    with pause_live(None):
        pass
    progress = _live_progress()
    assert not progress.live.is_started
    with pause_live(progress):
        assert not progress.live.is_started


def test_ensure_ezproxy_session_pauses_live_progress(monkeypatch):
    from paperful import cli
    from paperful.config import Config

    progress = _live_progress()
    progress.start()
    events: list[str] = []

    class Pipe:
        live_progress = progress
        cfg = Config()

    pipe = Pipe()

    def fake_input(prompt: str = "") -> str:
        events.append("input" if progress.live.is_started else "input-paused")
        return "n"

    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli.console, "input", fake_input)
    # Avoid headed login; decline path only needs the prompt.
    ok = cli._ensure_ezproxy_session(
        pipe.cfg,
        pipe,
        enabled=True,
        prompt="re-login? [Y/n] ",
    )
    assert ok is False
    assert events == ["input-paused"]
    assert progress.live.is_started
    progress.stop()
    # Keep Live from eating later test stdout via captured handles.
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__


def test_item_progress_disabled_never_starts_live():
    console = Console(file=_TtyBuffer(), force_terminal=True)
    with item_progress(console, disable=True) as progress:
        task_id = progress.add_task("quiet", total=2)
        progress.advance(task_id)
        assert not progress.live.is_started
    assert console.file.getvalue() == ""


def test_tracker_advances_per_row_and_names_the_row_in_hand():
    from tests.conftest import make_item

    console = Console(file=_TtyBuffer(), force_terminal=True)
    progress = item_progress(console, disable=True)
    items = [make_item(key="K1", title="First [draft]"), make_item(key="K2")]
    seen: list[tuple[str, int, str]] = []
    for item in tracker(progress, "Working")(items):
        task = progress.tasks[0]
        seen.append((item.key, int(task.completed), task.description))
    task = progress.tasks[0]
    assert [(k, n) for k, n, _ in seen] == [("K1", 0), ("K2", 1)]
    assert "First \\[draft]" in seen[0][2]
    assert (task.total, task.completed, task.description) == (2, 2, "Working")


def test_tracker_stops_short_when_the_loop_breaks():
    console = Console(file=_TtyBuffer(), force_terminal=True)
    progress = item_progress(console, disable=True)
    for row in tracker(progress, "Working")(["a", "b", "c"]):
        if row == "b":
            break
    assert progress.tasks[0].completed == 1
