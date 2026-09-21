"""Scope loader. Offline — the backend is a stub."""

from __future__ import annotations

import pytest

from paperful.scope import ScopeError, load_scope
from paperful.zot import Collection, Item


def _item(key: str, **overrides) -> Item:
    base = dict(
        key=key,
        item_type="journalArticle",
        title=key,
        doi=None,
        arxiv_id=None,
        url=None,
        year=2024,
        first_author="Ada",
        collection_paths=["BBNJ"],
        has_pdf=True,
    )
    base.update(overrides)
    return Item(**base)


class _Backend:
    def __init__(self):
        self.rows = {
            "A": _item("A", year=2024, has_pdf=True),
            "B": _item("B", year=2019, has_pdf=False, item_type="report"),
        }

    def get_item(self, key):
        return self.rows.get(key)

    def resolve_collection(self, spec):
        if spec != "BBNJ":
            raise LookupError(f"No collection matching '{spec}'")
        return Collection("C1", "BBNJ", None, "BBNJ")

    def subtree_keys(self, root):
        return [root.key]

    def items_in_scope(self, keys):
        return list(self.rows.values())


def test_load_scope_unions_item_and_collection_and_filters():
    loaded = load_scope(
        _Backend(),
        item_keys=["A"],
        collections=["BBNJ"],
        year_from=2020,
        item_types=frozenset({"journalArticle"}),
        pdfs_only=True,
    )
    assert [it.key for it in loaded.items] == ["A"]
    assert loaded.label == "BBNJ, years ≥2020, types journalArticle"


def test_unknown_item_and_inverted_years():
    with pytest.raises(ScopeError, match="Unknown item"):
        load_scope(_Backend(), item_keys=["NOPE"])
    with pytest.raises(ScopeError, match="year-from"):
        load_scope(_Backend(), collections=["BBNJ"], year_from=2026, year_to=2020)
    with pytest.raises(ScopeError, match="No collection"):
        load_scope(_Backend(), collections=["missing"])
