"""Typed Paperful notes: first-line prefixes plus a ``paperful.note.v1`` block.

Zotero shows the first line in the item pane. Machine readers parse the HTML
comment. Tags stay the update lookup key.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

SCHEMA = "paperful.note.v1"
# Required keys on every paperful.note.v1 block(). Extra keys may be added.
NOTE_BLOCK_KEYS = frozenset(
    {"schema", "type", "verb", "model", "run_id", "prompt_sha"}
)
_BLOCK = re.compile(
    r"<!--\s*paperful\.note\.v1\s+(?P<body>\{.*?\})\s*-->",
    re.DOTALL,
)

PREFIX = {
    "summary": "Summary",
    "review": "Review",
    "duplicate": "Duplicate",
    "attach": "Attach",
    "linked": "Linked",
    "snowball": "Snowball",
    "briefing": "Briefing",
}


def first_line(note_type: str, *, model: str = "", extra: str = "") -> str:
    """Scannable lead for the item pane."""
    head = PREFIX.get(note_type, note_type.capitalize() or "Paperful")
    if model.strip():
        head = f"{head} ({model.strip()})"
    extra = (extra or "").strip()
    if extra:
        return f"{head}: {extra}"
    return f"{head}:"


def block(
    *,
    note_type: str,
    verb: str,
    model: str = "",
    run_id: str = "",
    prompt_sha: str = "",
) -> dict[str, str]:
    return {
        "schema": SCHEMA,
        "type": note_type,
        "verb": verb,
        "model": model,
        "run_id": run_id,
        "prompt_sha": prompt_sha,
    }


def comment(meta: dict[str, str]) -> str:
    return f"<!-- {SCHEMA} {json.dumps(meta, ensure_ascii=False, separators=(',', ':'))} -->"


def wrap(
    body_html: str,
    *,
    note_type: str,
    verb: str,
    model: str = "",
    run_id: str = "",
    prompt_sha: str = "",
    extra: str = "",
) -> str:
    """Prefix + provenance comment around existing note HTML. Idempotent."""
    stripped = (body_html or "").strip()
    if _BLOCK.search(stripped):
        return stripped
    lead = html.escape(first_line(note_type, model=model, extra=extra))
    meta = block(
        note_type=note_type,
        verb=verb,
        model=model,
        run_id=run_id,
        prompt_sha=prompt_sha,
    )
    return f"<p>{lead}</p>\n{comment(meta)}\n{stripped}"


def parse(html_note: str) -> dict[str, Any] | None:
    match = _BLOCK.search(html_note or "")
    if not match:
        return None
    try:
        body = json.loads(match.group("body"))
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None
