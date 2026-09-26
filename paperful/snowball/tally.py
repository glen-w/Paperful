"""Once-a-minute progress for the snowball step that is running."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

Emit = Callable[[str], None]

_LABELS = {
    "searches": "searches",
    "papers": "papers",
    "fields": "fields updated",
    "pdfs": "PDFs",
    "created": "created",
}


def step_of(stage: str) -> str:
    """Group stage labels that belong to one unit of work.

    Cited-by updates the label for every seed. Those lines are one step.
    """
    if stage.startswith("hop "):
        head = stage.split(" · ", 1)[0]
        parts = head.split()
        if len(parts) >= 3 and parts[2] in {"references", "cited-by"}:
            return " ".join(parts[:3])
        return " ".join(parts[:2]) if len(parts) >= 2 else stage
    if stage.startswith("ORCID work"):
        return "ORCID work"
    if stage.startswith("seed "):
        return "seed"
    if stage.startswith("resume cited-by"):
        return "resume cited-by"
    if stage.startswith("resume references"):
        return "resume references"
    return stage


def colour_for(stage: str) -> str:
    """One colour per kind of step, matching the rest of the CLI."""
    step = step_of(stage).lower()
    if step.startswith("creat"):
        return "green"
    if "pdf" in step:
        return "cyan"
    if step.startswith("crossref") or step.startswith("semantic") or step.startswith("europepmc"):
        return "magenta"
    if "cited-by" in step:
        return "blue"
    if step.startswith("hop ") or step.startswith("resume"):
        return "cyan"
    return "white"


def paint(message: str) -> str:
    return f"[{colour_for(message)}]{message}[/]"


def metrics_for(stage: str) -> tuple[str, ...]:
    """Counters the current step actually moves."""
    step = step_of(stage).lower()
    if step.startswith("creat"):
        return ("created",)
    if "pdf" in step:
        return ("pdfs",)
    if step.startswith("crossref") or step.startswith("semantic"):
        return ("searches", "fields")
    return ("searches", "papers")


class Tally:
    """Counts for the current step. A daemon thread prints them every ``interval_s``."""

    def __init__(self, emit: Emit, *, interval_s: float = 60.0):
        self.emit = emit
        self.interval_s = interval_s
        self._stage = ""
        self._step = ""
        self.searches = 0
        self.papers = 0
        self.fields = 0
        self.pdfs = 0
        self.created = 0
        self._base = {"searches": 0, "papers": 0, "fields": 0, "pdfs": 0, "created": 0}
        self._total: int | None = None
        self._done = 0
        self._pdfs: Callable[[], int] | None = None
        self._bar: Any = None
        self._task: Any = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def stage(self) -> str:
        return self._stage

    @stage.setter
    def stage(self, value: str) -> None:
        self._stage = value
        step = step_of(value)
        if step != self._step:
            self._step = step
            self._base = self._snapshot()
            self._total = None
            self._done = 0

    def bind_pdfs(self, pdfs: Callable[[], int]) -> None:
        self._pdfs = pdfs

    def bind_bar(self, progress: Any, task_id: Any) -> None:
        self._bar = progress
        self._task = task_id
        self.refresh()

    def track(self, total: int) -> None:
        """Known length of this step. The bar then shows done/total."""
        self._total = max(0, total)
        self._done = 0
        self.refresh()

    def advance(self, n: int = 1) -> None:
        self._done += n
        if self._total is not None:
            self._done = min(self._done, self._total)
        self.refresh()

    def description(self) -> str:
        label = paint(self._stage) if self._stage else "snowball"
        stats = self._stats()
        if not stats:
            return label
        return f"{label} [dim]{stats}[/]"

    def refresh(self) -> None:
        if self._bar is None or self._task is None:
            return
        if self._total:
            self._bar.update(
                self._task,
                description=self.description(),
                total=self._total,
                completed=min(self._done, self._total),
            )
            return
        self._bar.update(self._task, description=self.description(), total=None)

    def line(self) -> str:
        parts = [self._stage] if self._stage else []
        stats = self._stats()
        if stats:
            parts.append(stats)
        return " · ".join(parts)

    def _stats(self) -> str:
        values = self._snapshot()
        parts: list[str] = []
        for key in metrics_for(self._stage):
            count = values[key] - self._base[key]
            parts.append(f"{count} {_LABELS[key]}")
        return " · ".join(parts)

    def report(self) -> None:
        self.emit(self.line())

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="snowball-tally", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None and self._bar is None:
            return
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1)
            self._thread = None
        self.refresh()
        if self._bar is not None:
            self._bar.stop()
            self._bar = None
            self._task = None
        self.report()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            if self._bar is None:
                self.report()

    def _pdf_count(self) -> int:
        return self._pdfs() if self._pdfs is not None else self.pdfs

    def _snapshot(self) -> dict[str, int]:
        return {
            "searches": self.searches,
            "papers": self.papers,
            "fields": self.fields,
            "pdfs": self._pdf_count(),
            "created": self.created,
        }
