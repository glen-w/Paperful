"""Plain-language lines on a parent item. Notes by default; tags when asked.

The machine-readable attachment stamp stays on the PDF. These lines are the
human copy, written through ``[remarks].surface``.
"""

from __future__ import annotations

import html
from typing import Any

from .zot import Item

# Lookup tag on the child note, and the parent-tag prefix replaced on re-run.
_KINDS = {
    "found": ("paperful-found", "paperful found:"),
    "duplicate": ("paperful-duplicate", "paperful duplicate:"),
    "linked": ("paperful-linked", "paperful linked:"),
}


def say(backend: Any, item_key: str, kind: str, sentence: str, *, surface: str) -> None:
    """Write ``sentence`` once. ``off`` and a missing writer do nothing."""
    mode = (surface or "note").strip().lower()
    text = (sentence or "").strip()
    if mode == "off" or not text or not item_key:
        return
    note_tag, prefix = _KINDS[kind]
    if mode == "tag":
        writer = getattr(backend, "replace_prefixed_tag", None)
        if writer is None:
            return
        writer(item_key, prefix, f"{prefix} {text}")
        return
    writer = getattr(backend, "create_or_update_note", None)
    if writer is None:
        return
    writer(item_key, f"<p>{html.escape(text)}</p>", note_tag)


def spare_sentence(keeper: Item) -> str:
    """Name the copy to keep, on the spare parent."""
    author = (keeper.first_author or "").strip()
    year = str(keeper.year) if keeper.year else ""
    if author:
        name = f"{author} {year}".strip()
    else:
        title = (keeper.title or "").strip()
        if not title or title == "(untitled)":
            name = "another copy"
        elif len(title) > 60:
            name = title[:57].rstrip() + "..."
        else:
            name = title
    line = f"Same paper as {name}"
    if keeper.has_pdf:
        line += ", which already has the PDF"
    return line + "."


def remark_duplicates(
    backend: Any,
    groups: list[Any],
    items: list[Item],
    *,
    surface: str,
) -> None:
    """Write the spare-copy line. Held groups are skipped."""
    if (surface or "note").strip().lower() == "off":
        return
    by_key = {item.key: item for item in items}
    for group in groups:
        if getattr(group, "held", False) or not group.keep or not group.trash:
            continue
        keeper = by_key.get(group.keep)
        if keeper is None:
            continue
        sentence = spare_sentence(keeper)
        for key in group.trash:
            say(backend, key, "duplicate", sentence, surface=surface)


def cite_sentence(count: int, *, library: bool) -> str | None:
    if count < 1:
        return None
    noun = "paper" if count == 1 else "papers"
    where = "your library" if library else "this collection"
    return f"Cited by {count} {noun} in {where}."


def seed_sentence(*, hop: int, direction: str, overlap: int) -> str | None:
    """How many seeds from this run point at the new item. Not a collection count."""
    if hop < 1 or overlap < 2:
        return None
    from .snowball.expand import direction_sides

    try:
        sides = direction_sides(direction or "refs")
    except ValueError:
        sides = frozenset()
    n = overlap
    if "refs" in sides and "cites" in sides:
        return f"Linked to {n} of the papers you started from."
    if "cites" in sides:
        return f"Cites {n} of the papers you started from."
    if "refs" in sides:
        return f"In the bibliography of {n} of the papers you started from."
    return f"Linked to {n} of the papers you started from."


def linked_sentence(
    *,
    hop: int,
    direction: str,
    overlap: int,
    cite_count: int,
    library: bool,
) -> str:
    """In-collection cites, then the seed sentence when both apply."""
    parts = [
        cite_sentence(cite_count, library=library),
        seed_sentence(hop=hop, direction=direction, overlap=overlap),
    ]
    return " ".join(part for part in parts if part)
