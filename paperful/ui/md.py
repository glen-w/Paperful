"""Escaped Markdown subset for Ask assistant turns.

Escape first, then a tight CommonMark slice: paragraphs, ``#`` / ``##`` /
``###``, ``**bold**``, ``_italic_`` / ``*italic*``, backticks, lists, and
``http(s)`` links. Raw HTML and ``javascript:`` URLs stay text.
"""

from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_ITALIC_US = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")


def _inline(text: str) -> str:
    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2).strip()
        if url.startswith(("http://", "https://")):
            href = html.escape(url, quote=True)
            return f'<a href="{href}">{label}</a>'
        return label

    text = _LINK.sub(link, text)
    text = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_STAR.sub(r"<em>\1</em>", text)
    text = _ITALIC_US.sub(r"<em>\1</em>", text)
    return text


def md_to_html(text: str | None) -> str:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    escaped = html.escape(raw, quote=False)
    lines = escaped.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        heading = _HEADING.match(stripped)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if stripped.startswith(("- ", "* ")):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        para: list[str] = []
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            if _HEADING.match(nxt.strip()) or nxt.strip().startswith(("- ", "* ")):
                break
            para.append(_inline(nxt.strip()))
            i += 1
        out.append("<p>" + "<br>\n".join(para) + "</p>")
    return "".join(out)
