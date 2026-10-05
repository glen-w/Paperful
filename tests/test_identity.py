"""Library fingerprint shared by snowball, ingest, refs gap, inbox."""

from types import SimpleNamespace

from paperful.identity import (
    LibraryFingerprint,
    from_seed_tag,
    inbox_dir_tag,
    merge_tags,
    seed_slug,
)
from tests.conftest import make_item


def test_fingerprint_doi_then_title_year():
    items = [
        make_item(key="A", doi="10.1000/a", title="Alpha paper about oceans", year=2020),
        make_item(key="B", doi=None, title="Beta paper about oceans", year=2021),
    ]
    fp = LibraryFingerprint.from_items(items)
    assert fp.find("10.1000/a").item_key == "A"
    assert fp.find(None, "Beta paper about oceans", 2021).kind == "title_year"
    assert fp.find("10.1000/missing", "Nope", 1999) is None


def test_fingerprint_blank_year_is_not_title_year():
    item = SimpleNamespace(
        key="K1",
        doi=None,
        title="Basketball tactics",
        year="",
        arxiv_id=None,
        extra="",
        collection_paths=[],
    )
    fp = LibraryFingerprint.from_items([item])
    assert fp.find(None, "Basketball tactics", "") is None


def test_merge_tags_stable_unique():
    assert merge_tags(["a", "b"], ["b", "c"], ["  "]) == ["a", "b", "c"]


def test_seed_slug_and_from_seed_tag(tmp_path):
    assert seed_slug("BBNJ ocean") == "bbnj-ocean"
    assert from_seed_tag({"type": "doi", "value": "10.1000/seed"}) == "from-10-1000-seed"
    assert from_seed_tag(tmp_path / "bbnj-seed.txt") == "from-bbnj-seed"
    assert inbox_dir_tag("~/Documents/paperful_inbox") == "inbox:paperful-inbox"
