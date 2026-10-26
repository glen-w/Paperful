"""File health, structure, identity, and PPS fingerprint checkers."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Config
from ..critique import Finding, make_finding
from ..critique_extract import ExtractedDoc
from ..zot import Item


def _file_health(doc: ExtractedDoc) -> list[Finding]:
    out: list[Finding] = []
    if doc.finding == "no_file":
        out.append(
            make_finding(
                code="no_file",
                severity="major",
                detail="No file on disk to extract.",
                source="rule",
            )
        )
        return out
    if doc.finding == "unsupported":
        out.append(
            make_finding(
                code="unsupported_format",
                severity="major",
                detail=f"Unsupported format {doc.format!r}. Use pdf, txt, md, html, rtf, docx, odt, pptx.",
                source="rule",
            )
        )
        return out
    if doc.finding == "needs_ocr":
        out.append(
            make_finding(
                code="needs_ocr",
                severity="warn",
                detail="PDF text layer is too thin to check. Run paperful ocr or paste a text export.",
                source="rule",
            )
        )
    elif doc.finding == "empty_extract":
        detail = "Extracted too little text to check."
        if doc.error:
            detail = f"{detail} {doc.error}"
        out.append(
            make_finding(
                code="empty_extract",
                severity="warn",
                detail=detail,
                source="rule",
            )
        )
    if doc.format != "pdf":
        out.append(
            make_finding(
                code="skipped_not_pdf",
                severity="info",
                detail="PDF-only probes (short-PDF, page geometry) skipped.",
                source="rule",
            )
        )
    elif doc.pdf_pages == 1 and doc.pdf_words < 200:
        out.append(
            make_finding(
                code="short_pdf",
                severity="info",
                detail=f"One-page PDF ({doc.pdf_words} first-page words).",
                loc="p. 1",
                source="rule",
            )
        )
    return out


def _structure(
    cfg: Config, doc: ExtractedDoc, sections_used: list[str]
) -> list[Finding]:
    from ..sections.extract import split_sections

    pages = doc.pages or [doc.text]
    slices = split_sections(pages, cfg)
    have: set[str] = set()
    for sl in slices:
        label = sl.canonical or sl.heading or ""
        if label:
            sections_used.append(label)
        if sl.canonical:
            have.add(sl.canonical)
    out: list[Finding] = []
    for name in ("methodology", "results", "limitations", "related_work"):
        if name in have:
            continue
        out.append(
            make_finding(
                code="missing_section",
                severity="info",
                detail=f"No extractable {name.replace('_', ' ')} section.",
                source="rule",
                extra={"section": name},
            )
        )
    return out


def _identity(
    cfg: Config,
    item: Item,
    client: httpx.Client | None,
    backend: Any,
    offline: bool,
) -> list[Finding]:
    if offline or client is None:
        return [
            make_finding(
                code="identity_skipped_offline",
                severity="info",
                detail="Identity lint skipped (offline / no HTTP client).",
                source="rule",
            )
        ]
    from ..lint import lint_item
    from ..store import Manifest

    try:
        rows = lint_item(
            client,
            cfg,
            item,
            backend=backend,
            manifest=Manifest(cfg.manifest_path),
        )
    except Exception:
        return []
    out: list[Finding] = []
    for row in rows:
        sev = (
            "warn"
            if row.code in {"pdf_doi_mismatch", "pdf_identity_mismatch"}
            else "info"
        )
        out.append(
            make_finding(
                code=row.code,
                severity=sev,
                detail=row.detail,
                source="rule",
            )
        )
    return out


def _pps_fingerprint_findings(
    cfg: Config,
    client: httpx.Client | None,
    text: str,
    *,
    offline: bool,
) -> list[Finding]:
    """PPS-style fingerprint families on critique extract (same rules as ``screen``)."""
    if not (text or "").strip():
        return []
    from ..screen import (
        FINGERPRINT_FAMILIES,
        _detector_on,
        load_fingerprints,
        scan_text_fingerprints,
    )

    out: list[Finding] = []
    for family in FINGERPRINT_FAMILIES:
        if not _detector_on(cfg, family):
            continue
        try:
            fps = load_fingerprints(client, cfg, family, refresh=False, offline=offline)
            hits = scan_text_fingerprints(
                text,
                fps,
                family=family,
                tortured_min=cfg.screen_tortured_min,
            )
        except Exception:
            continue
        if not hits:
            continue
        sample = hits[:8]
        more = len(hits) - len(sample)
        detail = f"{len(hits)} fingerprint hit(s) (flags to review)."
        if more > 0:
            detail = f"{len(hits)} fingerprint hit(s) (flags to review; showing {len(sample)})."
        out.append(
            make_finding(
                code=f"pps_{family}",
                severity="info",
                detail=detail,
                quote="; ".join(sample[:2]),
                source="pps",
            )
        )
    return out


def _integrity_item(
    cfg: Config,
    item: Item,
    client: httpx.Client | None,
    backend: Any,
    offline: bool,
) -> list[Finding]:
    if offline or client is None:
        return []
    from ..screen import FINGERPRINT_FAMILIES, screen_item
    from ..store import Manifest

    try:
        rows = screen_item(
            client,
            cfg,
            item,
            backend=backend,
            manifest=Manifest(cfg.manifest_path),
        )
    except Exception:
        rows = []
    out: list[Finding] = []
    for row in rows:
        if row.code in FINGERPRINT_FAMILIES:
            continue
        out.append(
            make_finding(
                code=f"pps_{row.code}",
                severity="warn" if row.code in {"retracted", "withdrawn"} else "info",
                detail=row.detail,
                quote=" ".join(row.evidence[:2]),
                source="pps",
            )
        )
    return out
