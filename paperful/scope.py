"""Collection, year, and type selection.

No Typer and no console output. Callers turn :class:`ScopeError` into an exit.
"""

from __future__ import annotations

from dataclasses import dataclass

from .zot import Item, filter_items_by_type, filter_items_by_year


class ScopeError(Exception):
    """The requested slice cannot be loaded."""


@dataclass(frozen=True)
class ItemScope:
    items: list[Item]
    label: str
    keys: list[str] | None


def resolve_keys(
    backend, collections: list[str], library: bool
) -> tuple[list[str] | None, str]:
    """Collection subtree keys and the scope label before year or type filters."""
    if library:
        return None, "whole library"
    keys: list[str] = []
    for spec in collections:
        try:
            root = backend.resolve_collection(spec)
        except LookupError as exc:
            raise ScopeError(str(exc)) from exc
        keys.extend(backend.subtree_keys(root))
    return keys, ", ".join(collections)


def _year_label(year_from: int | None, year_to: int | None) -> str | None:
    if year_from is None and year_to is None:
        return None
    if year_from is not None and year_to is not None:
        return f"years {year_from}–{year_to}"
    if year_from is not None:
        return f"years ≥{year_from}"
    return f"years ≤{year_to}"


def _type_label(types: frozenset[str] | None) -> str | None:
    if not types:
        return None
    return "types " + ", ".join(sorted(types))


def filter_scope_items(
    items: list[Item],
    label: str,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
    annotate: bool = True,
) -> tuple[list[Item], str]:
    """Filter by year and item type. ``annotate`` appends those bounds to ``label``."""
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ScopeError("--year-from must be ≤ --year-to.")
    filtered = filter_items_by_year(items, year_from, year_to)
    filtered = filter_items_by_type(filtered, item_types)
    if annotate:
        for part in (_year_label(year_from, year_to), _type_label(item_types)):
            if part:
                label = f"{label}, {part}"
    return filtered, label


def load_scope(
    backend,
    *,
    item_keys: list[str] | None = None,
    collections: list[str] | None = None,
    library: bool = False,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
    pdfs_only: bool = False,
) -> ItemScope:
    """Union of ``--item`` keys and a collection or library, then year and type.

    ``--item`` rows come first. Duplicate keys keep the first copy. A whole
    library wins over collection specs for the label and the walk.
    """
    keys_asked = list(item_keys or [])
    specs = list(collections or [])
    items: list[Item] = []
    for key in keys_asked:
        it = backend.get_item(key)
        if it is None:
            raise ScopeError(f"Unknown item {key}")
        items.append(it)
    keys: list[str] | None = None
    if library:
        label = "whole library"
        items.extend(backend.items_in_scope(None))
    elif specs:
        keys, label = resolve_keys(backend, specs, False)
        items.extend(backend.items_in_scope(keys))
    else:
        label = "items " + ",".join(keys_asked)
    seen: set[str] = set()
    unique: list[Item] = []
    for it in items:
        if it.key in seen:
            continue
        seen.add(it.key)
        unique.append(it)
    if pdfs_only:
        unique = [it for it in unique if it.has_pdf]
    unique, label = filter_scope_items(
        unique,
        label,
        year_from=year_from,
        year_to=year_to,
        item_types=item_types,
    )
    return ItemScope(items=unique, label=label, keys=keys)
