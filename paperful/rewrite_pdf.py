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


def html_from_paragraphs(paragraphs: list[str], edits: list[RewriteEdit]) -> str:
    body_edits = [e for e in edits if e.kind in {"replace", "insert", "delete"}]
    blob = apply_to_text("\n\n".join(paragraphs), body_edits)
    parts = [p.strip() for p in blob.split("\n\n") if p.strip()] or [
        p.strip() for p in paragraphs if str(p).strip()
    ]
    inner = "".join(f"<p>{html.escape(p)}</p>" for p in parts)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>paperful rewrite</title></head><body>"
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


def build_pdf_from_paragraphs(
    dest: Path,
    paragraphs: list[str],
    edits: list[RewriteEdit],
) -> list[str]:
    """Applied-text PDF. Comments stay in the edit plan."""
    html_doc = html_from_paragraphs(paragraphs, edits)
    try:
        pdf = html_to_pdf_bytes(html_doc)
    except Exception as exc:
        return [f"pdf: {type(exc).__name__}: {exc}"]
    if not pdf or not pdf.lstrip().startswith(b"%PDF"):
        return ["pdf: render produced no PDF"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf)
    return pdf_structural_issues(dest)
