"""Membership batch: parse, classify, apply."""

from __future__ import annotations

from paperful.collections_add import (
    SCHEMA,
    apply_adds,
    classify_rows,
    parse_key_lines,
    write_summary,
)
from paperful.library import LibraryError
from tests.conftest import make_item


class FakeBackend:
    def __init__(self, items: dict[str, dict]):
        # key -> {"collections": [...], "title": "...", "paths": [...]}
        self.items = items
        self.added: list[tuple[str, str]] = []
        self.fail_keys: set[str] = set()

    def raw_item(self, key: str):
        row = self.items.get(key)
        if row is None:
            return None
        return {
            "key": key,
            "data": {
                "collections": list(row.get("collections") or []),
                "title": row.get("title") or "",
            },
        }

    def get_item(self, key: str):
        row = self.items.get(key)
        if row is None:
            return None
        paths = list(row.get("paths") or [])
        return make_item(key=key, title=row.get("title") or "T", collection_paths=paths)

    def add_to_collection(self, item_key: str, collection_key: str) -> None:
        if item_key in self.fail_keys:
            raise LibraryError("write failed")
        row = self.items[item_key]
        cols = list(row.get("collections") or [])
        if collection_key not in cols:
            cols.append(collection_key)
            row["collections"] = cols
        self.added.append((item_key, collection_key))


def test_parse_key_lines_comments_and_dedupe():
    text = """
# skip
KEY1
KEY2  # comment
KEY1
"""
    assert parse_key_lines(text) == ["KEY1", "KEY2"]


def test_classify_add_already_in_not_found():
    backend = FakeBackend(
        {
            "IN": {"collections": ["C1"], "title": "Inside", "paths": ["BBNJ"]},
            "OUT": {"collections": [], "title": "Outside", "paths": ["Other"]},
        }
    )
    batch = classify_rows(
        ["IN", "OUT", "GONE"],
        backend,
        collection_key="C1",
        collection_path="BBNJ",
    )
    by_key = {r.key: r for r in batch.rows}
    assert by_key["IN"].status == "already-in"
    assert by_key["OUT"].status == "add"
    assert by_key["GONE"].status == "not-found"
    assert batch.counts()["already_in"] == 1
    assert batch.counts()["add"] == 1
    assert batch.counts()["not_found"] == 1


def test_classify_path_fallback_when_raw_collections_empty():
    backend = FakeBackend(
        {
            "M1": {"collections": [], "title": "Mendeley-like", "paths": ["BBNJ"]},
        }
    )
    batch = classify_rows(
        ["M1"], backend, collection_key="C1", collection_path="BBNJ"
    )
    assert batch.rows[0].status == "already-in"


def test_apply_adds_and_errors():
    backend = FakeBackend(
        {
            "A": {"collections": [], "title": "A", "paths": []},
            "B": {"collections": [], "title": "B", "paths": []},
        }
    )
    backend.fail_keys.add("B")
    batch = classify_rows(
        ["A", "B"], backend, collection_key="C1", collection_path="BBNJ"
    )
    apply_adds(backend, batch, "C1")
    by_key = {r.key: r for r in batch.rows}
    assert by_key["A"].status == "added"
    assert by_key["B"].status == "error"
    assert backend.added == [("A", "C1")]
    assert batch.added == 1 and batch.failed == 1
    assert batch.applied is True

    again = classify_rows(["A"], backend, collection_key="C1", collection_path="BBNJ")
    assert again.rows[0].status == "already-in"


def test_write_summary(tmp_path):
    backend = FakeBackend({"K": {"collections": [], "title": "T", "paths": []}})
    batch = classify_rows(["K"], backend, collection_key="C1", collection_path="BBNJ")
    folder = write_summary(tmp_path / "state", "BBNJ", batch)
    payload = (folder / "summary.json").read_text(encoding="utf-8")
    assert SCHEMA in payload
    assert '"applied": false' in payload
