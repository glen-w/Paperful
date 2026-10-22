"""Collection [[exclude]] protect rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperful.config import Config, load_config
from paperful.exclude import (
    ExcludeDenied,
    ExcludeGuard,
    ExcludeRule,
    filter_library_scope_items,
    parse_exclude_rule,
    parse_exclude_rules,
    path_under,
)
from paperful.library import LibraryError, ZoteroBackend
from paperful.zot import Collection, Item


def _cols() -> dict[str, Collection]:
    return {
        "HAND": Collection("HAND", "Hand curated", None, "Hand curated", "Hand curated"),
        "ARCH": Collection(
            "ARCH", "Archive", "HAND", "Hand curated/Archive", "Hand curated/Archive"
        ),
        "INBOX": Collection("INBOX", "Inbox", None, "Inbox", "Inbox"),
        "STAGE": Collection(
            "STAGE", "Staging", "INBOX", "Inbox/Staging", "Inbox/Staging"
        ),
        "WORK": Collection("WORK", "Work", None, "Work", "Work"),
    }


def test_path_under():
    assert path_under("Hand curated/Archive", "Hand curated")
    assert path_under("Hand curated", "Hand curated")
    assert not path_under("Hand", "Hand curated")
    assert not path_under("Work", "Hand curated")


def test_preset_full_denies_all():
    rule = parse_exclude_rule({"path": "Hand curated", "mode": "full"})
    assert rule.mode == "full"
    assert rule.protect_items is True
    for op in (
        "create",
        "add",
        "ensure_path",
        "update",
        "notes",
        "tags",
        "attach",
        "trash",
        "collection_notes",
        "merge",
    ):
        assert rule.allows(op) is False


def test_preset_add_only():
    rule = parse_exclude_rule({"path": "Inbox/Staging", "mode": "add_only"})
    assert rule.allows("create") is True
    assert rule.allows("add") is True
    assert rule.allows("ensure_path") is True
    assert rule.allows("update") is False
    assert rule.allows("trash") is False


def test_custom_overrides():
    rule = parse_exclude_rule(
        {
            "path": "Work",
            "mode": "custom",
            "allow_create": True,
            "allow_add": True,
            "allow_update": False,
            "protect_items": False,
        }
    )
    assert rule.allows("create") is True
    assert rule.allows("add") is True
    assert rule.allows("update") is False
    assert rule.protect_items is False


def test_parse_requires_path_or_key():
    with pytest.raises(ValueError, match="path or key"):
        parse_exclude_rule({})


def test_parse_exclude_rules_list():
    rules = parse_exclude_rules(
        [
            {"path": "Hand curated", "mode": "full"},
            {"path": "Inbox/Staging", "mode": "add_only"},
        ]
    )
    assert len(rules) == 2
    assert rules[0].mode == "full"
    assert rules[1].mode == "add_only"


def test_guard_full_blocks_collection_and_item():
    guard = ExcludeGuard(
        (ExcludeRule(path="Hand curated", mode="full"),),
        _cols(),
    )
    with pytest.raises(ExcludeDenied, match="add"):
        guard.check_collection("add", "ARCH")
    with pytest.raises(ExcludeDenied, match="update"):
        guard.check_item("update", ["ARCH", "WORK"])
    # unprotected collection ok
    guard.check_collection("add", "WORK")
    guard.check_item("update", ["WORK"])


def test_guard_add_only_allows_create_denies_update():
    guard = ExcludeGuard(
        (parse_exclude_rule({"path": "Inbox/Staging", "mode": "add_only"}),),
        _cols(),
    )
    guard.check_collection("add", "STAGE")
    guard.check_collection("create", "STAGE")
    with pytest.raises(ExcludeDenied, match="update"):
        guard.check_item("update", ["STAGE"])


def test_guard_path_not_yet_created():
    guard = ExcludeGuard(
        (ExcludeRule(path="Hand curated", mode="full"),),
        _cols(),
    )
    with pytest.raises(ExcludeDenied, match="ensure"):
        guard.check_path("ensure_path", "Hand curated/NewFolder")


def test_guard_protect_items_false():
    rule = parse_exclude_rule(
        {"path": "Hand curated", "mode": "full", "protect_items": False}
    )
    guard = ExcludeGuard((rule,), _cols())
    with pytest.raises(ExcludeDenied):
        guard.check_collection("add", "HAND")
    # item mutations allowed when protect_items is off
    guard.check_item("update", ["HAND"])


def test_skip_library_scope_filter():
    rule = parse_exclude_rule(
        {"path": "Hand curated", "mode": "full", "skip_library_scope": True}
    )
    guard = ExcludeGuard((rule,), _cols())
    only_hand = Item(
        key="A",
        item_type="journalArticle",
        title="A",
        doi=None,
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="A",
        collection_paths=["Hand curated/Archive"],
    )
    also_work = Item(
        key="B",
        item_type="journalArticle",
        title="B",
        doi=None,
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="B",
        collection_paths=["Hand curated", "Work"],
    )
    work_only = Item(
        key="C",
        item_type="journalArticle",
        title="C",
        doi=None,
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="C",
        collection_paths=["Work"],
    )
    kept = filter_library_scope_items([only_hand, also_work, work_only], guard)
    assert [i.key for i in kept] == ["B", "C"]


def test_load_config_exclude(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
email = "t@example.org"
[[exclude]]
path = "Hand curated"
mode = "full"
[[exclude]]
path = "Inbox/Staging"
mode = "add_only"
allow_update = true
"""
    )
    cfg = load_config(p)
    assert len(cfg.exclude_rules) == 2
    assert cfg.exclude_rules[0].mode == "full"
    assert cfg.exclude_rules[1].allows("add") is True
    # explicit override on add_only preset
    assert cfg.exclude_rules[1].allows("update") is True


def test_backend_add_denied_full(tmp_path: Path):
    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )

    class FakeZot:
        def item(self, key):
            return {
                "key": key,
                "data": {"key": key, "collections": ["WORK"], "title": "T"},
            }

        def update_item(self, raw):
            raise AssertionError("should not write")

    class ZL:
        def __init__(self):
            self.zot = FakeZot()
            self._collections = _cols()

        def collections(self):
            return self._collections

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    with pytest.raises(LibraryError, match="excluded"):
        backend.add_to_collection("ITEM1", "HAND")


def test_backend_add_allowed_add_only(tmp_path: Path):
    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(
            parse_exclude_rule({"path": "Inbox/Staging", "mode": "add_only"}),
        ),
    )
    updated = []

    class FakeZot:
        def item(self, key):
            return {
                "key": key,
                "data": {"key": key, "collections": [], "title": "T"},
            }

        def update_item(self, raw):
            updated.append(list(raw["data"]["collections"]))

    class ZL:
        def __init__(self):
            self.zot = FakeZot()
            self._collections = _cols()

        def collections(self):
            return self._collections

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    backend.add_to_collection("ITEM1", "STAGE")
    assert updated == [["STAGE"]]


def test_backend_patch_denied_when_item_in_excluded(tmp_path: Path):
    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )

    class FakeZot:
        def item(self, key):
            return {
                "key": key,
                "data": {
                    "key": key,
                    "collections": ["ARCH", "WORK"],
                    "title": "T",
                    "DOI": "",
                },
            }

        def update_item(self, raw):
            raise AssertionError("should not write")

    class ZL:
        def __init__(self):
            self.zot = FakeZot()
            self._collections = _cols()

        def collections(self):
            return self._collections

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    with pytest.raises(LibraryError, match="excluded"):
        backend.apply_patch("ITEM1", {"doi": "10.1/x"})


def test_backend_create_parent_denied(tmp_path: Path):
    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )

    class FakeZot:
        def create_items(self, payloads):
            raise AssertionError("should not create")

    class ZL:
        def __init__(self):
            self.zot = FakeZot()
            self._collections = _cols()

        def collections(self):
            return self._collections

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    with pytest.raises(LibraryError, match="excluded"):
        backend.create_parent(
            {"itemType": "journalArticle", "title": "T", "collections": ["HAND"]}
        )


def test_doctor_exclude_check(tmp_path: Path):
    from paperful.doctor import _exclude_check

    cfg = Config(
        exclude_rules=(
            ExcludeRule(path="Hand curated", mode="full"),
            parse_exclude_rule(
                {"path": "Inbox/Staging", "mode": "add_only", "skip_library_scope": True}
            ),
        )
    )
    check = _exclude_check(cfg)
    assert check.status == "green"
    assert "Hand curated" in check.detail
    assert "add_only" in check.detail
    assert "skip-scope" in check.detail

    empty = _exclude_check(Config())
    assert empty.detail == "none"

    missing = _exclude_check(
        Config(exclude_rules=(ExcludeRule(path="No Such Folder", mode="full"),)),
        collections=_cols(),
    )
    assert missing.status == "amber"
    assert "unmatched" in missing.detail


def test_guard_key_match():
    guard = ExcludeGuard(
        (ExcludeRule(key="HAND", mode="full"),),
        _cols(),
    )
    with pytest.raises(ExcludeDenied, match="add"):
        guard.check_collection("add", "ARCH")


def test_backend_ensure_path_and_notes_denied(tmp_path: Path):
    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )

    class FakeZot:
        def item(self, key):
            return {
                "key": key,
                "data": {
                    "key": key,
                    "collections": ["HAND"],
                    "title": "T",
                    "itemType": "journalArticle",
                },
            }

        def children(self, key):
            return []

        def create_items(self, payloads):
            raise AssertionError("should not create")

        def create_collections(self, payloads):
            raise AssertionError("should not create collection")

        def update_item(self, raw):
            raise AssertionError("should not update")

    class ZL:
        def __init__(self):
            self.zot = FakeZot()
            self._collections = _cols()

        def collections(self):
            return self._collections

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    with pytest.raises(LibraryError, match="excluded"):
        backend.ensure_collection_path("Hand curated/NewLeaf")
    with pytest.raises(LibraryError, match="excluded"):
        backend.create_or_update_note("ITEM1", "<p>x</p>", "paperful-summary")
    with pytest.raises(LibraryError, match="excluded"):
        backend.create_or_update_collection_note("HAND", "<p>x</p>", ["paperful-report"])


def test_mendeley_add_denied_full(tmp_path: Path):
    from paperful.mendeley import MendeleyBackend

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )

    class FakeClient:
        def post(self, *args, **kwargs):
            raise AssertionError("should not write")

    backend = MendeleyBackend(cfg, client=FakeClient())
    backend.collections = lambda: _cols()  # type: ignore[method-assign]
    backend._folder_membership = lambda: {"HAND": set(), "WORK": set()}  # type: ignore[method-assign]
    with pytest.raises(LibraryError, match="excluded"):
        backend.add_to_collection("DOC1", "HAND")


def test_mendeley_add_allowed_add_only(tmp_path: Path):
    from paperful.mendeley import MendeleyBackend

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(
            parse_exclude_rule({"path": "Inbox/Staging", "mode": "add_only"}),
        ),
    )
    posted: list[tuple] = []

    class FakeClient:
        def post(self, path, **kwargs):
            posted.append((path, kwargs.get("body")))
            return {"id": "DOC1"}

    backend = MendeleyBackend(cfg, client=FakeClient())
    backend.collections = lambda: _cols()  # type: ignore[method-assign]
    backend._folder_membership = lambda: {"STAGE": set()}  # type: ignore[method-assign]
    backend.add_to_collection("DOC1", "STAGE")
    assert posted == [("/folders/STAGE/documents", {"id": "DOC1"})]


def test_mendeley_patch_denied_when_item_in_excluded(tmp_path: Path):
    from paperful.mendeley import MendeleyBackend

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )

    class FakeClient:
        def patch(self, *args, **kwargs):
            raise AssertionError("should not write")

    backend = MendeleyBackend(cfg, client=FakeClient())
    backend.collections = lambda: _cols()  # type: ignore[method-assign]
    backend._item_collection_keys = lambda key: ["HAND"]  # type: ignore[method-assign]
    with pytest.raises(LibraryError, match="excluded"):
        backend.apply_patch("DOC1", {"title": "X"})


def test_endnote_create_parent_denied(tmp_path: Path):
    from paperful.endnote import EndNoteBackend
    from tests.test_endnote import make_endnote_library

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )
    cfg.endnote_library = make_endnote_library(tmp_path)
    backend = EndNoteBackend(cfg)
    backend.collections = lambda: _cols()  # type: ignore[method-assign]
    with pytest.raises(LibraryError, match="excluded"):
        backend.create_parent(
            {
                "collections": ["HAND"],
                "title": "T",
                "itemType": "journalArticle",
            }
        )


def test_endnote_ensure_path_denied(tmp_path: Path):
    from paperful.endnote import EndNoteBackend
    from tests.test_endnote import make_endnote_library

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )
    cfg.endnote_library = make_endnote_library(tmp_path)
    backend = EndNoteBackend(cfg)
    backend.collections = lambda: _cols()  # type: ignore[method-assign]
    with pytest.raises(LibraryError, match="excluded"):
        backend.ensure_collection_path("Hand curated/NewChild")


def test_endnote_attach_denied(tmp_path: Path):
    from paperful.endnote import EndNoteBackend
    from tests.test_endnote import make_endnote_library

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        exclude_rules=(ExcludeRule(path="Hand curated", mode="full"),),
    )
    cfg.endnote_library = make_endnote_library(tmp_path)
    backend = EndNoteBackend(cfg)
    backend.collections = lambda: _cols()  # type: ignore[method-assign]
    backend._item_collection_keys = lambda key: ["HAND"]  # type: ignore[method-assign]
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(LibraryError, match="excluded"):
        backend.attach("ITEM1", pdf)
