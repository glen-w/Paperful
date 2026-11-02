"""1.7 adapter conformance kit.

One contract, every backend: a manager may be called "supported" only when
(1) this suite passes against it, and (2) a real-library field report is
filed (docs/plans/1.7-wave.md). This file is (1): structural conformance for
the shipped backends plus a behaviour contract exercised on an in-memory
fake, so a future backend can be submitted against the same tests.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from paperful.library import LibraryBackend


def _protocol_methods() -> list[str]:
    return [
        name
        for name, member in vars(LibraryBackend).items()
        if callable(member) and not name.startswith("_")
    ]


def test_protocol_is_nonempty():
    methods = _protocol_methods()
    # Guard against the kit silently degrading to a no-op.
    assert len(methods) >= 20
    for required in (
        "collections",
        "resolve_collection",
        "items_in_scope",
        "supports_write",
        "attach",
        "create_parent",
        "flush_writes",
    ):
        assert required in methods


@pytest.mark.parametrize(
    "module,cls_name",
    [
        ("paperful.library", "ZoteroBackend"),
        ("paperful.mendeley", "MendeleyBackend"),
        ("paperful.endnote", "EndNoteBackend"),
    ],
)
def test_real_backends_implement_protocol(module, cls_name):
    import importlib

    cls = getattr(importlib.import_module(module), cls_name)
    missing = [
        name for name in _protocol_methods() if not callable(getattr(cls, name, None))
    ]
    assert missing == [], f"{cls_name} missing protocol methods: {missing}"


def test_mirrored_backend_delegates_protocol(cfg):
    """MirroredBackend forwards reads to the wrapped backend (__getattr__)."""
    from paperful.library import MirroredBackend

    wrapped = MirroredBackend(cfg, FakeBackend())
    missing = [
        name
        for name in _protocol_methods()
        if not callable(getattr(wrapped, name, None))
    ]
    assert missing == [], f"MirroredBackend missing via delegation: {missing}"
    assert wrapped.collections()["C1"].name == "ocean"


class FakeBackend:
    """Minimal in-memory backend proving the contract is implementable."""

    def __init__(self):
        from paperful.zot import Collection, Item

        self._cols = {"C1": Collection("C1", "ocean", None, "ocean", "ocean")}
        self._items = [
            Item(
                key="K1",
                title="Paper",
                doi="10.1/x",
                item_type="journalArticle",
                arxiv_id=None,
                url="",
                year=2024,
                first_author="Smith",
                collection_paths=["ocean"],
            )
        ]
        self.attached: list[tuple[str, Path]] = []
        self.notes: dict[str, str] = {}

    def ping(self):
        return {"ok": True}

    def collections(self):
        return dict(self._cols)

    def collection_counts(self):
        return {"C1": (1, 0)}

    def resolve_collection(self, spec):
        for col in self._cols.values():
            if spec in (col.key, col.name, col.path):
                return col
        raise LookupError(spec)

    def subtree_keys(self, root):
        return [root.key]

    def items_lacking_pdf(self, collection_keys, upgrade_linked=False):
        return list(self._items)

    def items_in_scope(self, collection_keys):
        return list(self._items)

    def count_linked_url_only(self, collection_keys):
        return 0

    def get_item(self, key):
        return next((i for i in self._items if i.key == key), None)

    def raw_item(self, key):
        item = self.get_item(key)
        return {"key": item.key} if item else None

    def children(self, key):
        return []

    def export_pdf(self, item, dest):
        return None

    def apply_patch(self, item_key, fields):
        return None

    def relate_items(self, left_key, right_key):
        return None

    def trash_item(self, item_key):
        return None

    def trash_note(self, note_key, *, parent_key=""):
        return None

    def merge_into(self, keep_key, drop_key):
        return {}

    def find_child_note_keys(self, item_key, tag):
        return [k for k in self.notes if k.startswith(item_key)]

    def read_child_note(self, item_key, tag):
        return self.notes.get(f"{item_key}:{tag}")

    def create_or_update_note(self, item_key, html, tag):
        self.notes[f"{item_key}:{tag}"] = html
        return f"{item_key}:{tag}"

    def replace_prefixed_tag(self, item_key, prefix, tag):
        return None

    def find_collection_note_keys(self, collection_key, tag):
        return []

    def create_or_update_collection_note(self, collection_key, html, tags):
        return "CN1"

    def supports_write(self):
        return True

    def ensure_collection_path(self, path):
        return "C1"

    def add_to_collection(self, item_key, collection_key):
        return None

    def create_parent(self, data):
        return "K2"

    def attach(self, item_key, pdf_path, title=None, note=None):
        self.attached.append((item_key, Path(pdf_path)))
        return {"itemKey": item_key}

    def flush_writes(self):
        return None


def test_fake_backend_satisfies_behaviour_contract(tmp_path):
    backend = FakeBackend()
    # Structural: every protocol method callable on the instance too.
    for name in _protocol_methods():
        assert callable(getattr(backend, name)), name
    col = backend.resolve_collection("ocean")
    assert backend.subtree_keys(col) == ["C1"]
    items = backend.items_in_scope(["C1"])
    assert [i.key for i in items] == ["K1"]
    assert backend.get_item("K1").doi == "10.1/x"
    assert backend.get_item("nope") is None
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    backend.attach("K1", pdf)
    assert backend.attached == [("K1", pdf)]
    key = backend.create_or_update_note("K1", "<p>hi</p>", "summary")
    assert backend.read_child_note("K1", "summary") == "<p>hi</p>"
    assert backend.find_child_note_keys("K1", "summary") == [key]
    assert backend.create_parent({}) == "K2"
    assert backend.flush_writes() is None


def test_protocol_signatures_do_not_drift():
    """attach/create_parent keep the keyword shapes callers rely on."""
    attach = inspect.signature(LibraryBackend.attach)
    assert list(attach.parameters) == ["self", "item_key", "pdf_path", "title", "note"]
    create = inspect.signature(LibraryBackend.create_parent)
    assert list(create.parameters) == ["self", "data"]
