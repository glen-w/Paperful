"""Per-source circuit breaker for repeated blocks / CAPTCHAs within one run."""

from __future__ import annotations

import threading

from .routing import is_block_failure
from .sources.base import Outcome


class CircuitBreaker:
    def __init__(self, threshold: int) -> None:
        self.threshold = max(1, threshold)
        self._counts: dict[str, int] = {}
        self._tripped: set[str] = set()
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._tripped.clear()

    def tripped(self, source: str) -> bool:
        return source in self._tripped

    def note(self, source: str, outcome: Outcome, note: str = "") -> bool:
        """Record a block-like failure. Returns True if the circuit just opened."""
        if not is_block_failure(outcome, note):
            return False
        with self._lock:
            count = self._counts.get(source, 0) + 1
            self._counts[source] = count
            if count >= self.threshold and source not in self._tripped:
                self._tripped.add(source)
                return True
        return False
