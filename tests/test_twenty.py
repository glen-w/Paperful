"""Twenty CRM author lookup (mocked HTTP, read-only)."""

from __future__ import annotations

import json

from paperful.snowball.authors import classify_listing_url, load_pack_file, pack_path
from paperful.twenty import (
    PersonHit,
    lookup_authors,
    names_match,
    unique_match,
    work_emails,
)
from paperful.snowball.authors import PackAuthor
from tests.conftest import make_item
from paperful.twenty import authors_from_items


def _people_payload(people: list[dict]) -> dict:
    return {"data": {"people": people}}


def test_classify_listing_rejects_researchgate():
    assert classify_listing_url("https://www.researchgate.net/profile/Ada") == ""


def test_work_emails_prefer_institutional():
    assert work_emails(["ada@gmail.com", "ada@univ.edu"]) == ["ada@univ.edu"]


def test_unique_match_fails_closed_on_ambiguous():
    hits = [
        PersonHit(twenty_id="1", first_name="Ada", last_name="Lovelace"),
        PersonHit(twenty_id="2", first_name="Ann", last_name="Lovelace"),
    ]
    assert unique_match(hits, "Lovelace") is None
    assert unique_match(hits, "Lovelace", "Ada") is not None
    assert names_match(hits[0], "Lovelace", "Ada")


def test_lookup_apply_writes_pack_and_contact(cfg, monkeypatch):
    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"

    def getter(url, headers, params):
        assert "Bearer test-key" in headers.get("Authorization", "")
        return _people_payload(
            [
                {
                    "id": "abc",
                    "name": {"firstName": "Ada", "lastName": "Lovelace"},
                    "emails": {"primaryEmail": "ada@univ.edu"},
                    "website": "https://lovelace.github.io/papers/",
                }
            ]
        )

    authors = [PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a")]
    rows = lookup_authors(
        cfg, authors, getter=getter, collection="BBNJ", apply=True
    )
    assert rows[0].status == "match"
    assert "github.io" in rows[0].listing_url
    pack = load_pack_file(pack_path(cfg, "bbnj", promoted=False))
    assert pack is not None
    assert any(a.source == "twenty" and a.listing_url for a in pack.authors)
    contact = next((cfg.state_dir / "author-contacts").glob("*.json"))
    body = json.loads(contact.read_text(encoding="utf-8"))
    assert body["schema"] == "paperful.author_contact.v1"
    assert body["emails"] == ["ada@univ.edu"]
    assert body["twenty_id"] == "abc"


def test_lookup_ambiguous_and_empty_do_not_write(cfg, monkeypatch):
    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"

    def getter(url, headers, params):
        return _people_payload(
            [
                {
                    "id": "1",
                    "name": {"firstName": "Ada", "lastName": "Lovelace"},
                },
                {
                    "id": "2",
                    "name": {"firstName": "Ann", "lastName": "Lovelace"},
                },
            ]
        )

    authors = [PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a")]
    rows = lookup_authors(
        cfg, authors, getter=getter, collection="BBNJ", apply=True
    )
    assert rows[0].status == "ambiguous"
    assert not pack_path(cfg, "bbnj", promoted=False).is_file() or not any(
        a.listing_url
        for a in (load_pack_file(pack_path(cfg, "bbnj", promoted=False)).authors)
    )
    assert not list((cfg.state_dir / "author-contacts").glob("*.json"))


def test_lookup_rejects_researchgate_website(cfg, monkeypatch):
    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"

    def getter(url, headers, params):
        return _people_payload(
            [
                {
                    "id": "abc",
                    "name": {"firstName": "Ada", "lastName": "Lovelace"},
                    "emails": {"primaryEmail": "ada@univ.edu"},
                    "website": "https://www.researchgate.net/profile/Ada-Lovelace",
                }
            ]
        )

    authors = [PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a")]
    rows = lookup_authors(
        cfg, authors, getter=getter, collection="BBNJ", apply=True
    )
    assert rows[0].status == "match"
    assert rows[0].listing_url == ""
    contact = json.loads(
        next((cfg.state_dir / "author-contacts").glob("*.json")).read_text()
    )
    assert "researchgate" in contact["website"]


def test_authors_from_items_dedupes():
    items = [
        make_item(creator_surnames=["Lovelace"], first_author="Lovelace"),
        make_item(key="B", creator_surnames=["Lovelace"], first_author="Lovelace"),
    ]
    authors = authors_from_items(items)
    assert len(authors) == 1
