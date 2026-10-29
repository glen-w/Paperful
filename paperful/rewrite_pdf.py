"""Rewrite ``tracked.pdf`` from extract paragraphs. Playwright Chromium print."""

from __future__ import annotations

import html
from pathlib import Path

from .pdfid import page_count
from .rewrite_plan import RewriteEdit
from .rewrite_render import apply_to_text

def pdf_structural_issues(path: Path) -> list[str]:
    """Catch unreadable PDF output. Not a full PDF/A validator."""
    if not path.is_file():
        return ["pdf: missing file"]
    raw = path.read_bytes()[:8]
    if not raw.lstrip().startswith(b"%PDF"):
        return ["pdf: missing %PDF header"]
    if page_count(path) < 1:
        return ["pdf: unreadable or empty"]
    return []


def applied_text(paragraphs: list[str], edits: list[RewriteEdit]) -> str:
    body_edits = [e for e in edits if e.kind in {"replace", "insert", "delete"}]
    blob = apply_to_text("\n\n".join(paragraphs), body_edits)
    parts = [p.strip() for p in blob.split("\n\n") if p.strip()] or [
        p.strip() for p in paragraphs if str(p).strip()
    ]
    return "\n\n".join(parts)


def comment_marks(
    blob: str, edits: list[RewriteEdit]
) -> list[tuple[int, int, int, RewriteEdit]]:
    """First unique occurrence of each comment quote in applied text."""
    marks: list[tuple[int, int, int, RewriteEdit]] = []
    taken: list[tuple[int, int]] = []
    n = 0
    for edit in edits:
        if edit.kind != "comment":
            continue
        quote = edit.quote
        if not quote or quote not in blob:
            continue
        idx = blob.find(quote)
        while idx >= 0 and any(not (idx + len(quote) <= a or idx >= b) for a, b in taken):
            idx = blob.find(quote, idx + 1)
        if idx < 0:
            continue
        n += 1
        end = idx + len(quote)
        taken.append((idx, end))
        marks.append((idx, end, n, edit))
    return marks


def html_from_paragraphs(paragraphs: list[str], edits: list[RewriteEdit]) -> str:
    blob = applied_text(paragraphs, edits)
    marks = comment_marks(blob, edits)
    chunks: list[str] = []
    cursor = 0
    by_span: dict[tuple[int, int], list[int]] = {}
    for start, end, n, _edit in marks:
        by_span.setdefault((start, end), []).append(n)
    for (start, end), nums in sorted(by_span.items()):
        chunks.append(html.escape(blob[cursor:start]))
        supers = "".join(f"<sup>[{n}]</sup>" for n in nums)
        chunks.append(
            f'<span class="pf-cmt">{html.escape(blob[start:end])}{supers}</span>'
        )
        cursor = end
    chunks.append(html.escape(blob[cursor:]))
    marked = "".join(chunks)
    inner = "".join(f"<p>{p}</p>" for p in marked.split("\n\n") if p.strip())
    if marks:
        items = []
        for _start, _end, n, edit in marks:
            body = html.escape((edit.body or edit.quote or "").strip()[:500])
            loc = html.escape(edit.loc) if edit.loc else ""
            loc_bit = f" <span class='pf-loc'>({loc})</span>" if loc else ""
            items.append(f"<li value='{n}'><strong>[{n}]</strong> {body}{loc_bit}</li>")
        inner += (
            "<h2 class='pf-comments'>Comments</h2>"
            f"<ol class='pf-comments'>{''.join(items)}</ol>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>paperful rewrite</title>"
        "<style>"
        "body{font:12pt/1.4 Georgia,serif;margin:0}"
        ".pf-cmt{background:#fff3c4}"
        ".pf-cmt sup{font-size:.75em;color:#8a5a00}"
        "h2.pf-comments{page-break-before:always;font-size:14pt}"
        ".pf-loc{color:#555;font-size:.9em}"
        "</style></head><body>"
        f"{inner}</body></html>"
    )


def html_to_pdf_bytes(html_doc: str) -> bytes:
    """Print HTML to PDF. Tests monkeypatch this."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html_doc, wait_until="domcontentloaded")
            return page.pdf(
                format="A4",
                print_background=True,
                margin={
                    "top": "16mm",
                    "bottom": "16mm",
                    "left": "16mm",
                    "right": "16mm",
                },
            )
        finally:
            browser.close()


def attach_pdf_comments(
    path: Path, marks: list[tuple[int, int, int, RewriteEdit]]
) -> list[str]:
    """Sticky-note annotations (Acrobat comments pane). Positions are on the last page."""
    if not marks or not path.is_file():
        return []
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.annotations import Text
    except ImportError:
        return []
    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            return ["pdf comments: no pages"]
        writer = PdfWriter()
        writer.append(reader)
        page_i = len(writer.pages) - 1
        page = writer.pages[page_i]
        height = float(page.mediabox.height)
        width = float(page.mediabox.width)
        for i, (_start, _end, n, edit) in enumerate(marks):
            y = max(36.0, height - 40.0 - i * 24.0)
            body = (edit.body or edit.quote or "").strip()[:500]
            writer.add_annotation(
                page_i,
                Text(
                    rect=(max(12.0, width - 40.0), y, width - 16.0, y + 18.0),
                    text=f"[{n}] {body}",
                    open=False,
                ),
            )
        dest = path.with_suffix(path.suffix + ".annot")
        with dest.open("wb") as fh:
            writer.write(fh)
        dest.replace(path)
    except Exception as exc:
        return [f"pdf comments: {type(exc).__name__}: {exc}"]
    return []


def build_pdf_from_paragraphs(
    dest: Path,
    paragraphs: list[str],
    edits: list[RewriteEdit],
) -> list[str]:
    """Applied-text PDF with numbered comments (print + sticky notes)."""
    html_doc = html_from_paragraphs(paragraphs, edits)
    try:
        pdf = html_to_pdf_bytes(html_doc)
    except Exception as exc:
        return [f"pdf: {type(exc).__name__}: {exc}"]
    if not pdf or not pdf.lstrip().startswith(b"%PDF"):
        return ["pdf: render produced no PDF"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf)
    issues = attach_pdf_comments(
        dest, comment_marks(applied_text(paragraphs, edits), edits)
    )
    issues.extend(pdf_structural_issues(dest))
    return issues
