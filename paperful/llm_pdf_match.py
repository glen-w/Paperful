"""Grounded PDF identity check via LLM."""

from __future__ import annotations

from .config import Config
from .grounding import metadata_block, pdf_text_for
from .library import LibraryBackend
from .llm import CompletionRequest, get_client
from .lint import Finding
from .store import Manifest
from .zot import Item


def pdf_identity_finding(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
) -> Finding | None:
    if not cfg.llm_enabled or not cfg.lint_llm_pdf_match:
        return None
    body = pdf_text_for(cfg, item, manifest, backend, max_pages=2)
    if not body.strip():
        return None
    client = get_client(cfg)
    prompt = (
        "Does the PDF excerpt belong to the bibliographic record? "
        'Reply JSON only: {"match": true|false, "confidence": 0-1, "reason": "..."}.\n\n'
        f"{metadata_block(item)}\n\nPDF excerpt:\n{body[:6000]}"
    )
    try:
        data = client.complete_json(
            CompletionRequest(
                model=cfg.llm_model,
                prompt=prompt,
                timeout_seconds=cfg.llm_timeout_s,
                json_mode=True,
            )
        )
    except Exception:
        return None
    match = data.get("match")
    conf_raw = data.get("confidence")
    try:
        conf = float(conf_raw) if conf_raw is not None else None
    except (TypeError, ValueError):
        conf = None
    if match is True and (
        conf is None or conf >= cfg.lint_llm_pdf_match_min_confidence
    ):
        return None
    if match is True:
        reason = str(data.get("reason") or "low-confidence match")
    else:
        reason = str(data.get("reason") or "LLM reports mismatch")
    detail = reason
    if conf is not None:
        detail = f"{reason} (confidence={conf:.2f})"
    return Finding(
        itemKey=item.key,
        code="pdf_identity_mismatch",
        title=item.title,
        detail=detail,
        library_doi=item.library_doi,
        doi=item.doi,
    )
