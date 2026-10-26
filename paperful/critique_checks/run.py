"""Orchestrate deterministic critique checkers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ..config import Config
from ..critique import Finding
from ..critique_extract import ExtractedDoc
from ..zot import Item
from .biblio import _bibliography_and_cites
from .floats import _acronyms, _floats, _glossary_acronyms
from .overlap import _overlap
from .structure import (
    _file_health,
    _identity,
    _integrity_item,
    _pps_fingerprint_findings,
    _structure,
)
from .style import (
    _abstract_numbers,
    _checklists,
    _mentions_and_urls,
    _prose,
    _stats,
    _style_metrics,
)


def run_checks(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    item: Item | None,
    collections: list[str],
    library: bool,
    offline: bool,
    client: httpx.Client | None,
    backend: Any | None,
    scope_items: list[Item],
    force: bool,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], list[dict[str, Any]], list[str]]:
    findings: list[Finding] = []
    sections_used: list[str] = []
    say = on_status or (lambda _msg: None)

    say("Checkers: file health and structure")
    findings.extend(_file_health(doc))
    if (
        doc.finding in {"no_file", "unsupported", "empty_extract", "needs_ocr"}
        and not doc.text.strip()
    ):
        return findings, [], sections_used

    findings.extend(_structure(cfg, doc, sections_used))
    say("Checkers: bibliography")
    findings.extend(
        _bibliography_and_cites(
            cfg, doc, item, scope_items, offline, client, on_status=on_status
        )
    )
    say("Checkers: floats, acronyms, stats, prose")
    findings.extend(_floats(doc))
    findings.extend(_acronyms(doc))
    findings.extend(_glossary_acronyms(cfg, doc))
    findings.extend(_abstract_numbers(doc))
    findings.extend(_mentions_and_urls(doc))
    findings.extend(_checklists(doc, item))
    findings.extend(_stats(doc))
    findings.extend(_prose(doc))
    findings.extend(_style_metrics(doc))

    say("Checkers: PPS fingerprints (tortured phrases, etc.)")
    findings.extend(_pps_fingerprint_findings(cfg, client, doc.text, offline=offline))

    if item is not None:
        say("Checkers: identity and integrity")
        findings.extend(_identity(cfg, item, client, backend, offline))
        findings.extend(_integrity_item(cfg, item, client, backend, offline))

    n_scope = len(scope_items)
    if n_scope:
        say(f"Library overlap vs {n_scope} scoped item(s)…")
    else:
        say("Library overlap (corpus on disk)…")
    overlap_rows: list[dict[str, Any]] = []
    findings.extend(_overlap(cfg, doc, item, scope_items, overlap_rows))
    return findings, overlap_rows, sections_used
