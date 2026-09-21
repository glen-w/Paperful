"""Literature-review report from summary notes already on disk or in Zotero."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, wants_disk, wants_zotero
from .dedupe import scope_slug
from .library import LibraryBackend
from .llm import CompletionRequest, ctx_tokens_for, llm_egress_is_remote
from .summarize import to_note_html
from .zot import Item

SCHEMA = "paperful.synthesis.v1"

_DEFAULT_REPORT_PROMPT = """You are writing a literature review for a personal research library.
Use ONLY the summaries below. Cite only as [Surname Year] from those blocks.
If something is not covered, say "not covered". Do not invent papers or findings.
Structure the review in simple HTML (no outer html/body tags, no Markdown, no code fences):
<h2>Corpus</h2>
<h2>Themes</h2>
<h2>Points of agreement</h2>
<h2>Disagreements and tensions</h2>
<h2>Gaps and open questions</h2>
<h2>Suggested reading order</h2>
Use <p> and <ul><li>. Keep under 1200 words."""

_CHUNK_PROMPT = """You are synthesising a batch of paper summaries for a later literature review.
Use ONLY the summaries below. Keep citations exactly as [Surname Year].
Write plain HTML (<p> and <ul><li> only). At most 500 words.
Do not invent papers or findings."""

_FOOTER = re.compile(
    r"\n?<p><em>paperful · (?P<body>.*?)</em></p>\s*$",
    re.DOTALL,
)
_LI_OPEN = re.compile(r"(?i)<li\b[^>]*>")
_H_OPEN = re.compile(r"(?i)<h[1-6]\b[^>]*>")
_BLOCK_CLOSE = re.compile(r"(?i)</(?:p|h[1-6]|div|ul|ol|li)>")
_BR = re.compile(r"(?i)<br\s*/?>")
_ANY_TAG = re.compile(r"<[^>]+>")
_CITE = re.compile(r"\[([^\[\]]+?)\]")
_YEAR = re.compile(r"^(?P<who>.+?)\s+(?P<year>\d{4}|n\.d\.)$")


class ReduceCapError(RuntimeError):
    """Map-reduce still overflowed the context budget after three passes."""


@dataclass
class SourceNote:
    key: str
    title: str
    year: int | None
    author: str
    doi: str | None
    label: str
    body_text: str
    provenance: str
    origin: str  # disk | note
    sha256: str


def note_text(raw_html: str) -> str:
    """HTML note → plain text. Headings stay lines; list items become '- '."""
    text = _BR.sub("\n", raw_html or "")
    text = _LI_OPEN.sub("\n- ", text)
    text = _H_OPEN.sub("\n", text)
    text = _BLOCK_CLOSE.sub("\n", text)
    text = _ANY_TAG.sub("", text)
    text = html.unescape(text)
    out: list[str] = []
    blank = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if out and not blank:
                out.append("")
            blank = True
            continue
        blank = False
        out.append(stripped)
    return "\n".join(out).strip()


def split_footer(raw_html: str) -> tuple[str, str]:
    """Return (body html, provenance text inside the paperful footer)."""
    stripped = (raw_html or "").strip()
    match = _FOOTER.search(stripped)
    if not match:
        return stripped, ""
    return stripped[: match.start()].strip(), match.group("body").strip()


def load_report_prompt(cfg: Config) -> tuple[str, str]:
    if cfg.synthesize_prompt_template == "default":
        return _DEFAULT_REPORT_PROMPT, "default"
    path = Path(cfg.synthesize_prompt_template)
    return path.read_text(encoding="utf-8"), str(path)


def cite_token(author: str, year: int | None) -> str:
    who = (author or "Unknown").split()[-1]
    yr = str(year) if year else "n.d."
    return f"{who} {yr}".lower()


def source_block(src: SourceNote) -> str:
    yr = src.year if src.year else "n.d."
    who = src.author or "Unknown"
    doi = f", DOI {src.doi}" if src.doi else ""
    return f"### [{who} {yr}] {src.title} (key {src.key}{doi})\n{src.body_text}"


def pack_chunks(blocks: list[str], budget: int) -> list[str]:
    """Greedy pack. A single block over the budget is truncated."""
    budget = max(1, budget)
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    marker = "\n[… truncated]"
    for raw in blocks:
        block = raw
        if len(block) > budget:
            keep = max(0, budget - len(marker))
            block = block[:keep] + marker
        extra = len(block) if not current else len(block) + 2
        if current and size + extra > budget:
            groups.append(current)
            current = [block]
            size = len(block)
        else:
            current.append(block)
            size += extra
    if current:
        groups.append(current)
    return ["\n\n".join(group) for group in groups]


def body_budget(cfg: Config, template: str) -> int:
    return max(500, cfg.synthesize_max_context_chars - len(template) - 64)


def load_sources(
    cfg: Config, items: list[Item], backend: LibraryBackend | None
) -> tuple[list[SourceNote], list[Item]]:
    """Disk file wins; otherwise the tagged child note. Items with neither are missing."""
    found: list[SourceNote] = []
    missing: list[Item] = []
    for item in items:
        raw_html = ""
        origin = ""
        path = cfg.summaries_dir / f"{item.key}.html"
        if path.is_file():
            raw_html = path.read_text(encoding="utf-8")
            origin = "disk"
        elif backend is not None:
            note = backend.read_child_note(item.key, cfg.summarize_tag)
            if note:
                raw_html = note
                origin = "note"
        if not raw_html.strip():
            missing.append(item)
            continue
        body, provenance = split_footer(raw_html)
        found.append(
            SourceNote(
                key=item.key,
                title=item.title,
                year=item.year,
                author=item.first_author or "Unknown",
                doi=item.doi,
                label=item.label,
                body_text=note_text(body),
                provenance=provenance,
                origin=origin,
                sha256=hashlib.sha256(body.encode()).hexdigest(),
            )
        )
    found.sort(key=lambda src: (src.year or 9999, src.author.lower(), src.key))
    return found, missing


def chunk_plan(cfg: Config, sources: list[SourceNote]) -> list[int]:
    """Character length of each first-level chunk. No model call."""
    template, _ = load_report_prompt(cfg)
    chunks = pack_chunks(
        [source_block(src) for src in sources], body_budget(cfg, template)
    )
    return [len(chunk) for chunk in chunks]


def _complete(cfg: Config, client, prompt: str) -> str:
    return client.complete(
        CompletionRequest(
            model=cfg.llm_model,
            prompt=prompt,
            timeout_seconds=cfg.effective_synthesize_timeout(),
            num_ctx=ctx_tokens_for(prompt, max_num_ctx=cfg.llm_max_num_ctx),
        )
    )


def map_reduce(
    cfg: Config,
    client,
    blocks: list[str],
    template: str,
    *,
    log=None,
) -> tuple[str, int]:
    """Return (html body, first-level chunk count). Raises ReduceCapError past 3 passes."""
    budget = body_budget(cfg, template)
    chunks = pack_chunks(blocks, budget)
    first = len(chunks)
    for level in range(3):
        if len(chunks) == 1:
            kind = "Summaries" if level == 0 else "Batch syntheses"
            prompt = f"{template}\n\n---\n{kind}:\n{chunks[0]}"
            return to_note_html(_complete(cfg, client, prompt)), first
        parts: list[str] = []
        for index, chunk in enumerate(chunks, 1):
            if log:
                log(f"level {level + 1} chunk {index}/{len(chunks)}")
            prompt = f"{_CHUNK_PROMPT}\n\n---\nSummaries:\n{chunk}"
            parts.append(_complete(cfg, client, prompt))
        chunks = pack_chunks(parts, budget)
    raise ReduceCapError(
        "synthesis still exceeds the context budget after 3 reduce passes; "
        "narrow the scope or raise [synthesize].max_context_chars"
    )


def unmatched_citations(model_html: str, sources: list[SourceNote]) -> list[str]:
    known = {cite_token(src.author, src.year) for src in sources}
    seen: list[str] = []
    for match in _CITE.finditer(note_text(model_html)):
        inner = match.group(1).strip()
        year = _YEAR.match(inner)
        if not year:
            continue
        token = f"{year.group('who').split()[-1]} {year.group('year')}".lower()
        if token not in known:
            label = f"[{inner}]"
            if label not in seen:
                seen.append(label)
    return seen


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def assemble_report(
    cfg: Config,
    *,
    scope_label: str,
    model_html: str,
    sources: list[SourceNote],
    missing: list[Item],
    prompt_sha: str,
    n_chunks: int,
) -> str:
    parts = [f"<h1>Paperful report: {_esc(scope_label)}</h1>", model_html.strip()]
    items = []
    for src in sources:
        yr = src.year if src.year else "n.d."
        who = src.author or "Unknown"
        doi = f", DOI {_esc(src.doi)}" if src.doi else ""
        prov = f" — {_esc(src.provenance)}" if src.provenance else ""
        items.append(
            "<li>"
            f"[{_esc(who)} {yr}] {_esc(src.title)} — key {_esc(src.key)}{doi}{prov}"
            "</li>"
        )
    parts.append("<h2>Sources</h2>\n<ul>\n" + "\n".join(items) + "\n</ul>")
    if missing:
        rows = "".join(
            f"<li>{_esc(item.label)} — key {_esc(item.key)}</li>" for item in missing
        )
        parts.append(
            "<h2>Not included</h2>\n"
            "<p>No summary note yet. Run <em>paperful summarize</em> for these items.</p>\n"
            f"<ul>\n{rows}\n</ul>"
        )
    bad = unmatched_citations(model_html, sources)
    if bad:
        parts.append(
            "<p><em>Unmatched citations: "
            + ", ".join(_esc(token) for token in bad)
            + "</em></p>"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    chunk_word = "chunk" if n_chunks == 1 else "chunks"
    detail = (
        f"{len(sources)} summaries · {n_chunks} {chunk_word} · scope {_esc(scope_label)}"
    )
    if llm_egress_is_remote(cfg):
        footer = (
            f"<p><em>paperful · remote LLM · {_esc(cfg.llm_model)} · {stamp} · {detail}</em></p>"
        )
    else:
        footer = (
            f"<p><em>paperful · {_esc(cfg.llm_model)} · {stamp} · prompt {prompt_sha} · {detail}</em></p>"
        )
    parts.append(footer)
    return "\n".join(parts)


def render_synthesis(
    cfg: Config,
    sources: list[SourceNote],
    missing: list[Item],
    scope_label: str,
    *,
    client,
    log=None,
) -> tuple[str, int, str]:
    """Return (full html, first-level chunk count, prompt sha)."""
    template, _template_id = load_report_prompt(cfg)
    sha = hashlib.sha256(template.encode()).hexdigest()[:8]
    body, n_chunks = map_reduce(
        cfg,
        client,
        [source_block(src) for src in sources],
        template,
        log=log,
    )
    html_out = assemble_report(
        cfg,
        scope_label=scope_label,
        model_html=body,
        sources=sources,
        missing=missing,
        prompt_sha=sha,
        n_chunks=n_chunks,
    )
    return html_out, n_chunks, sha


def synthesis_slug(*parts: str) -> str:
    return scope_slug(" ".join(part for part in parts if part))


def report_tags(cfg: Config, slug: str) -> list[str]:
    base = cfg.synthesize_tag or "paperful-report"
    return [base, f"{base}:{slug}"]


def fingerprint(sources: list[SourceNote]) -> list[dict[str, str]]:
    return [
        {"key": src.key, "source": src.origin, "sha256": src.sha256} for src in sources
    ]


def sidecar_path(cfg: Config, slug: str) -> Path:
    return cfg.reports_dir / f"{slug}.json"


def report_is_current(
    cfg: Config, slug: str, sources: list[SourceNote], *, dest: str | None = None
) -> bool:
    path = sidecar_path(cfg, slug)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if dest is not None and data.get("destinations") != destination_names(dest):
        return False
    previous = data.get("sources") or []

    def norm(rows: list) -> list[tuple[str, str]]:
        return sorted(
            (str(row.get("key") or ""), str(row.get("sha256") or "")) for row in rows
        )

    return norm(previous) == norm(fingerprint(sources))


def write_report_files(
    cfg: Config, slug: str, report_html: str, sidecar: dict
) -> tuple[Path, Path]:
    folder = cfg.reports_dir
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{slug}.html"
    json_path = folder / f"{slug}.json"
    html_path.write_text(report_html, encoding="utf-8")
    json_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return html_path, json_path


def destination_names(dest: str) -> list[str]:
    names: list[str] = []
    if wants_disk(dest):
        names.append("disk")
    if wants_zotero(dest):
        names.append("zotero")
    return names
