"""Is OSF Preprints worth a fetch source? Count recent misses that point at osf.io.

Reads the local manifest only (no network). A thin OSF source ships only when
this signal is meaningful: at least ``MIN_OSF_MISSES`` recent misses and at
least ``MIN_SHARE`` of all recent misses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .store import STATUS_ATTACHED, STATUS_OK, Manifest

MIN_OSF_MISSES = 10
MIN_SHARE = 0.05
RECENT_DAYS = 90
_HOSTS = ("osf.io", "psyarxiv.com", "socarxiv.org", "engrxiv.org", "edarxiv.org")


@dataclass(frozen=True)
class OsfSignal:
    misses: int
    osf: int

    @property
    def share(self) -> float:
        return self.osf / self.misses if self.misses else 0.0

    @property
    def meaningful(self) -> bool:
        return self.osf >= MIN_OSF_MISSES and self.share >= MIN_SHARE


def _mentions_osf(text: str) -> bool:
    low = text.lower()
    return any(host in low for host in _HOSTS)


def osf_signal(manifest: Manifest, *, days: int = RECENT_DAYS, now: float | None = None) -> OsfSignal:
    cutoff = (now if now is not None else time.time()) - days * 86400
    misses = osf = 0
    for rec in manifest.records.values():
        if rec.status in {STATUS_OK, STATUS_ATTACHED} or rec.ts < cutoff:
            continue
        misses += 1
        if _mentions_osf(" ".join([rec.url or "", *rec.attempts])):
            osf += 1
    return OsfSignal(misses=misses, osf=osf)
