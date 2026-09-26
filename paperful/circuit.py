"""Per-source circuit breaker for repeated blocks / CAPTCHAs within one run.

A rate limit does not open the circuit. A captcha or block page pauses the
source for ``cooldown_items``, then one probe is allowed. A clean probe
closes the circuit; another block pauses it again.
"""

from __future__ import annotations

import threading

from .routing import is_block_failure
from .sources.base import Outcome

# Long enough that a short test run stays paused, short enough that a
# multi-thousand-item fetch tries the source again later in the same process.
DEFAULT_COOLDOWN_ITEMS = 25


def is_rate_limit(outcome: Outcome, note: str = "") -> bool:
    """429 and explicit rate-limit errors back off in the HTTP client instead."""
    if outcome != "error":
        return False
    low = note.lower()
    return "429" in low or "rate limit" in low


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown_items: int = DEFAULT_COOLDOWN_ITEMS) -> None:
        self.threshold = max(1, threshold)
        self.cooldown_items = max(1, cooldown_items)
        self._counts: dict[str, int] = {}
        self._skip_left: dict[str, int] = {}
        self._half_open: set[str] = set()
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._skip_left.clear()
            self._half_open.clear()

    def tripped(self, source: str) -> bool:
        """True when this source should be skipped for the current item."""
        with self._lock:
            if source in self._half_open:
                return False
            return self._skip_left.get(source, 0) > 0

    def consume_skip(self, source: str) -> None:
        """Count one skipped item. The last skip arms a single probe."""
        with self._lock:
            left = self._skip_left.get(source, 0)
            if left <= 1:
                self._skip_left.pop(source, None)
                self._half_open.add(source)
            else:
                self._skip_left[source] = left - 1

    def note(self, source: str, outcome: Outcome, note: str = "") -> bool:
        """Record an outcome. Returns True if the circuit just opened or re-opened."""
        if is_rate_limit(outcome, note):
            return False
        with self._lock:
            if not is_block_failure(outcome, note):
                if source in self._half_open or source in self._skip_left:
                    self._half_open.discard(source)
                    self._skip_left.pop(source, None)
                    self._counts[source] = 0
                return False
            if source in self._half_open:
                self._half_open.discard(source)
                self._open(source)
                return True
            count = self._counts.get(source, 0) + 1
            self._counts[source] = count
            if count >= self.threshold:
                self._open(source)
                return True
        return False

    def _open(self, source: str) -> None:
        self._counts[source] = 0
        self._skip_left[source] = self.cooldown_items
        self._half_open.discard(source)
