"""Index what a command just landed in the mirror (``[rag].auto_ingest``)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..config import Config
from ..store import STATUS_ATTACHED, STATUS_OK, Manifest, mirror_entries
from .ingest import IngestBatch, ingest_entries


def affected_keys(cfg: Config, since: float, keys: Iterable[str] = ()) -> set[str]:
    """Items named by the caller, plus every item whose PDF the manifest logged since ``since``.

    Fetch, attach, inbox and OCR all write the manifest when a PDF lands, so
    the timestamp is enough for them. Snapshot exports do not, and pass keys.
    """
    wanted = {key for key in keys if key}
    manifest = Manifest(cfg.manifest_path)
    for record in manifest.records.values():
        if (
            record.ts >= since
            and record.path
            and record.status in (STATUS_OK, STATUS_ATTACHED)
        ):
            wanted.add(record.itemKey)
    return wanted


def auto_ingest(
    cfg: Config, *, since: float, keys: Iterable[str] = (), **ingest: Any
) -> IngestBatch | None:
    """Ingest the affected items. None when the switch is off or nothing landed."""
    if not (cfg.rag_enabled and cfg.rag_auto_ingest):
        return None
    wanted = affected_keys(cfg, since, keys)
    if not wanted:
        return None
    entries = mirror_entries(cfg.out_dir, keys=wanted)
    if not entries:
        return None
    return ingest_entries(cfg, entries, **ingest)
