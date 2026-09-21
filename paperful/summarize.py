"""Grounded paper summaries on disk and optional Zotero notes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .grounding import budget_slice, metadata_block, pdf_text_for
from .library import LibraryBackend
from .llm import CompletionRequest, get_client, llm_egress_is_remote
from .store import Manifest
from .zot import Item

_DEFAULT_PROMPT = """You are summarizing a scholarly work for a personal research library.
Use ONLY the metadata and document text below. If information is missing, say so.
Structure the summary in HTML (no outer html/body tags):
<h2>Objective</h2>
<h2>Methods</h2>
<h2>Key findings</h2>
<h2>Limitations</h2>
Keep under 600 words."""


def load_prompt_template(cfg: Config) -> tuple[str, str]:
    if cfg.summarize_prompt_template == "default":
        return _DEFAULT_PROMPT, "default"
    path = Path(cfg.summarize_prompt_template)
    return path.read_text(encoding="utf-8"), str(path)


class IdentityMismatch(ValueError):
    """The gated identity check flagged this PDF; pass --force to summarize anyway."""


def summarize_item(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
    *,
    force: bool = False,
) -> Path:
    if not item.has_pdf:
        raise ValueError("item has no PDF attachment")
    if cfg.lint_llm_pdf_match and not force:
        from .llm_pdf_match import pdf_identity_finding

        finding = pdf_identity_finding(cfg, item, manifest, backend)
        if finding is not None:
            raise IdentityMismatch(
                f"pdf_identity_mismatch: {finding.detail} (use --force to override)"
            )
    raw = pdf_text_for(cfg, item, manifest, backend, max_pages=None)
    if not raw.strip():
        raise ValueError("could not extract PDF text")
    text = budget_slice(raw, cfg.summarize_max_context_chars)
    template, template_id = load_prompt_template(cfg)
    client = get_client(cfg)
    prompt = (
        f"{template}\n\n---\n{metadata_block(item)}\n\n---\nDocument text:\n{text}"
    )
    html_body = client.complete(
        CompletionRequest(
            model=cfg.llm_model,
            prompt=prompt,
            timeout_seconds=cfg.llm_timeout_s,
        )
    ).strip()
    sha = hashlib.sha256(template.encode()).hexdigest()[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer = (
        f'<p><em>paperful · {cfg.llm_model} · {stamp} · prompt {sha}</em></p>'
    )
    if llm_egress_is_remote(cfg):
        footer = (
            f'<p><em>paperful · remote LLM · {cfg.llm_model} · {stamp}</em></p>'
        )
    html = f"{html_body}\n{footer}"
    out = cfg.summaries_dir / f"{item.key}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def apply_summary_note(cfg: Config, backend: LibraryBackend, item: Item) -> str:
    path = cfg.summaries_dir / f"{item.key}.html"
    if not path.is_file():
        raise FileNotFoundError(path)
    html = path.read_text(encoding="utf-8")
    return backend.create_or_update_note(item.key, html, cfg.summarize_tag)
