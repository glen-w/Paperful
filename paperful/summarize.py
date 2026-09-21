"""Grounded paper summaries on disk and optional Zotero notes."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, wants_disk, wants_zotero
from .grounding import budget_slice, metadata_block, pdf_text_for
from .library import LibraryBackend, LibraryError
from .llm import CompletionRequest, ctx_tokens_for, get_client, llm_egress_is_remote
from .store import Manifest
from .zot import Item

_DEFAULT_PROMPT = """You are summarizing a scholarly work for a personal research library.
Use ONLY the metadata and document text below. If information is missing, say so.
Structure the summary in simple HTML (no outer html/body tags, no Markdown, no code fences):
<h2>Objective</h2>
<h2>Methods</h2>
<h2>Key findings</h2>
<h2>Limitations</h2>
Use <p> and <ul><li> for bullets. Keep under 600 words."""


_FENCE = re.compile(r"^```[a-zA-Z]*\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_TAG = re.compile(r"<\s*(h[1-6]|p|ul|ol|li|strong|em|br)\b", re.IGNORECASE)


def to_note_html(text: str) -> str:
    """Normalise model output for a Zotero note.

    Local models often ignore "reply in HTML" and emit Markdown (``## Heading``,
    ``* bullet``, ``**bold**``) or wrap the answer in a code fence. Zotero renders
    notes as HTML, so convert the common Markdown shapes; leave real HTML alone.
    """
    lines = [ln for ln in text.strip().splitlines() if not _FENCE.match(ln.strip())]
    body = "\n".join(lines).strip()
    if not body:
        return ""
    has_md = "**" in body or any(
        _HEADING.match(ln) or _BULLET.match(ln) for ln in body.splitlines()
    )
    if _TAG.search(body) and not has_md:
        return body
    out: list[str] = []
    para: list[str] = []
    in_list = False

    def flush_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            close_list()
            continue
        h = _HEADING.match(line)
        if h:
            flush_para()
            close_list()
            level = min(len(h.group(1)), 3)
            out.append(f"<h{level}>{_inline(h.group(2).strip())}</h{level}>")
            continue
        b = _BULLET.match(line)
        if b:
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(b.group(1).strip())}</li>")
            continue
        if _TAG.match(line.strip()):
            flush_para()
            close_list()
            out.append(line.strip())
            continue
        para.append(line.strip())
    flush_para()
    close_list()
    return "\n".join(out)


def _inline(text: str) -> str:
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def load_prompt_template(cfg: Config) -> tuple[str, str]:
    if cfg.summarize_prompt_template == "default":
        return _DEFAULT_PROMPT, "default"
    path = Path(cfg.summarize_prompt_template)
    return path.read_text(encoding="utf-8"), str(path)


class IdentityMismatch(ValueError):
    """The gated identity check flagged this PDF; pass --force to summarize anyway."""


def render_summary(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
    *,
    force: bool = False,
) -> str:
    """Grounded summary HTML, including the provenance footer. No disk or Zotero write."""
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
    template, _template_id = load_prompt_template(cfg)
    client = get_client(cfg)
    prompt = f"{template}\n\n---\n{metadata_block(item)}\n\n---\nDocument text:\n{text}"
    html_body = to_note_html(
        client.complete(
            CompletionRequest(
                model=cfg.llm_model,
                prompt=prompt,
                timeout_seconds=cfg.llm_timeout_s,
                num_ctx=ctx_tokens_for(prompt, max_num_ctx=cfg.llm_max_num_ctx),
            )
        )
    )
    sha = hashlib.sha256(template.encode()).hexdigest()[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer = f"<p><em>paperful · {cfg.llm_model} · {stamp} · prompt {sha}</em></p>"
    if llm_egress_is_remote(cfg):
        footer = f"<p><em>paperful · remote LLM · {cfg.llm_model} · {stamp}</em></p>"
    return f"{html_body}\n{footer}"


def write_summary_disk(cfg: Config, item: Item, html: str) -> Path:
    out = cfg.summaries_dir / f"{item.key}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def summarize_item(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
    *,
    force: bool = False,
) -> Path:
    """Render a summary and write ``state/summaries/<key>.html``."""
    html = render_summary(cfg, item, manifest, backend, force=force)
    return write_summary_disk(cfg, item, html)


@dataclass
class SummaryRow:
    key: str
    title: str
    status: str
    reason: str = ""
    disk_path: str = ""
    note_key: str = ""
    fatal: bool = False


@dataclass
class SummaryBatch:
    rows: list[SummaryRow]
    summarized: int
    failed: int

    @property
    def fatal(self) -> str | None:
        for row in self.rows:
            if row.fatal:
                return row.reason
        return None


def summarize_items(
    cfg: Config,
    items: list[Item],
    manifest: Manifest | None,
    backend: LibraryBackend | None,
    *,
    dest: str,
    force: bool = False,
    on_row: Callable[[SummaryRow], None] | None = None,
) -> SummaryBatch:
    """Summarize each item. A library write error stops the batch after that row."""
    rows: list[SummaryRow] = []
    ok = 0
    failed = 0
    for it in items:
        try:
            html = render_summary(cfg, it, manifest, backend, force=force)
            disk_path = ""
            note_key = ""
            if wants_disk(dest):
                disk_path = str(write_summary_disk(cfg, it, html))
            if wants_zotero(dest):
                if backend is None:
                    raise LibraryError("No library backend for a Zotero note.")
                note_key = apply_summary_note(cfg, backend, it, html)
            ok += 1
            row = SummaryRow(
                key=it.key,
                title=it.title,
                status="summarized",
                disk_path=disk_path,
                note_key=note_key,
            )
        except (ValueError, OSError) as exc:
            failed += 1
            row = SummaryRow(
                key=it.key, title=it.title, status="failed", reason=str(exc)
            )
        except LibraryError as exc:
            failed += 1
            row = SummaryRow(
                key=it.key,
                title=it.title,
                status="failed",
                reason=str(exc),
                fatal=True,
            )
            rows.append(row)
            if on_row is not None:
                on_row(row)
            return SummaryBatch(rows=rows, summarized=ok, failed=failed)
        rows.append(row)
        if on_row is not None:
            on_row(row)
    return SummaryBatch(rows=rows, summarized=ok, failed=failed)


def apply_summary_note(
    cfg: Config,
    backend: LibraryBackend,
    item: Item,
    html: str | None = None,
) -> str:
    if html is None:
        path = cfg.summaries_dir / f"{item.key}.html"
        if not path.is_file():
            raise FileNotFoundError(path)
        html = path.read_text(encoding="utf-8")
    return backend.create_or_update_note(item.key, html, cfg.summarize_tag)
