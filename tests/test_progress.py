"""Live progress bar helpers."""

from __future__ import annotations

import io
import sys

from rich.console import Console
from rich.progress import Progress

from paperful.progress import item_progress, pause_live


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
