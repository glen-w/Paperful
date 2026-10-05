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


def test_homepage_preferred_over_linkedin():
    from paperful.twenty import parse_person

    hit = parse_person(
        {
            "id": "1",
            "name": {"firstName": "Ada", "lastName": "Lovelace"},
            "linkedinLink": {"primaryLinkUrl": "https://www.linkedin.com/in/ada"},
            "homepage": "https://lovelace.github.io/papers/",
        }
    )
    assert hit is not None
    assert "github.io" in hit.website
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

    authors = [PackAuthor(name="Lovelace", fingerprint="lovelace|")]
    rows = lookup_authors(
        cfg, authors, getter=getter, collection="BBNJ", apply=True
    )
    assert rows[0].status == "ambiguous"
    assert not pack_path(cfg, "bbnj", promoted=False).is_file()
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


def test_authors_from_items_includes_coauthors():
    items = [
        make_item(
            creator_surnames=["Allsopp", "Miller", "Atkins"],
            first_author="Allsopp",
        ),
    ]
    authors = authors_from_items(items)
    assert {a.name for a in authors} == {"Allsopp", "Miller", "Atkins"}


def _status(code: int, body: dict | None = None, retry_after: str = "0"):
    import httpx

    req = httpx.Request("GET", "https://api.twenty.example/rest/people")
    resp = httpx.Response(
        code,
        json=body or {},
        headers={"Retry-After": retry_after},
        request=req,
    )
    return httpx.HTTPStatusError(f"HTTP {code}", request=req, response=resp)


def test_split_display_name_keeps_given_names():
    from paperful.twenty import split_display_name

    assert split_display_name("Ada Augusta Lovelace") == ("Lovelace", "Ada Augusta")


def test_authors_from_items_uses_given_names():
    from paperful.zot import CreatorPerson

    item = make_item(
        creator_people=[
            CreatorPerson(first="Ada", last="Lovelace", display="Ada Lovelace"),
            CreatorPerson(first="Charles", last="Babbage", display="Charles Babbage"),
        ],
        creator_surnames=["Lovelace", "Babbage"],
    )
    authors = authors_from_items([item])
    assert {a.name for a in authors} == {"Ada Lovelace", "Charles Babbage"}


def test_owned_email_stays_off_coauthor():
    from paperful.twenty import owned_emails
    from paperful.snowball.authors import PackAuthor
    from paperful.zot import CreatorPerson

    item = make_item(
        extra="Correspondence: ada@univ.edu",
        creator_people=[
            CreatorPerson(first="Ada", last="Lovelace", display="Ada Lovelace"),
            CreatorPerson(first="Charles", last="Babbage", display="Charles Babbage"),
        ],
    )
    ada = PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a")
    charles = PackAuthor(name="Charles Babbage", fingerprint="babbage|c")
    assert owned_emails([item], ada) == ["ada@univ.edu"]
    assert owned_emails([item], charles) == []


def test_twenty_request_retries_429(cfg, monkeypatch):
    from paperful.twenty import twenty_request

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_base_url = "https://api.twenty.example"
    cfg.twenty_retry_max = 2
    calls = {"n": 0}

    def sender(method, url, headers, params, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status(429)
        return {"data": {"people": []}}

    payload = twenty_request(
        cfg, "GET", "rest/people", sender=sender, sleeper=lambda _s: None
    )
    assert calls["n"] == 2
    assert payload["data"]["people"] == []


def test_lookup_apply_does_not_post(cfg, monkeypatch):
    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    seen: list[str] = []

    def fake_request(cfg, method, path, **kwargs):
        seen.append(method)
        return _people_payload(
            [
                {
                    "id": "abc",
                    "name": {"firstName": "Ada", "lastName": "Lovelace"},
                    "emails": {"primaryEmail": "ada@univ.edu"},
                }
            ]
        )

    monkeypatch.setattr("paperful.twenty.twenty_request", fake_request)
    rows = lookup_authors(
        cfg,
        [PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a")],
        collection="BBNJ",
        apply=True,
    )
    assert rows[0].status == "match"
    assert seen == ["GET"]


def test_sync_appends_homepage_and_stamps_keywords(cfg, monkeypatch):
    from paperful.twenty import apply_sync_actions, plan_sync
    from paperful.zot import CreatorPerson

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    calls: list[tuple[str, str, dict | None]] = []

    def sender(method, url, headers, params, body):
        calls.append((method, url, body))
        if method == "GET":
            return _people_payload(
                [
                    {
                        "id": "abc",
                        "name": {"firstName": "Ada", "lastName": "Lovelace"},
                        "homepage": {
                            "primaryLinkUrl": "https://ada.example.edu/",
                            "primaryLinkLabel": "",
                        },
                        "keywords": "ocean",
                    }
                ]
            )
        if method == "POST" and url.endswith("/notes"):
            return {"data": {"id": "note-1"}}
        return {"data": {"id": "ok"}}

    item = make_item(
        creator_people=[
            CreatorPerson(first="Ada", last="Lovelace", display="Ada Lovelace")
        ],
        extra="ada@univ.edu",
    )
    folder = cfg.state_dir / "author-contacts"
    folder.mkdir(parents=True)
    (folder / "lovelace-a.json").write_text(
        json.dumps(
            {
                "fingerprint": "lovelace|a",
                "website": "https://lovelace.github.io/papers/",
            }
        ),
        encoding="utf-8",
    )
    planned = plan_sync(
        cfg, [item], collection="ocean/BBNJ", sender=sender, sleeper=lambda _s: None
    )
    person = next(row for row in planned if row.name == "Ada Lovelace")
    assert person.action == "enrich"
    applied = apply_sync_actions(
        cfg, planned, collection="ocean/BBNJ", sender=sender, sleeper=lambda _s: None
    )
    patches = [body for method, url, body in calls if method == "PATCH" and body]
    homepage = next(body["homepage"] for body in patches if "homepage" in body)
    assert homepage["primaryLinkUrl"] == "https://ada.example.edu/"
    assert homepage["secondaryLinks"][0]["url"].startswith("https://lovelace.github.io/")
    keywords = next(body["keywords"] for body in patches if "keywords" in body)
    assert "paperful" in keywords and "ocean-bbnj" in keywords and "ocean" in keywords
    assert any(method == "POST" and url.endswith("/notes") for method, url, _body in calls)
    assert any(url.endswith("/noteTargets") for _method, url, _body in calls)
    assert next(row for row in applied if row.fingerprint == person.fingerprint).twenty_id == "abc"


def test_sync_fills_empty_homepage(cfg, monkeypatch):
    from paperful.twenty import PersonHit, merge_person_patch

    hit = PersonHit(
        twenty_id="abc",
        first_name="Ada",
        last_name="Lovelace",
        raw={"homepage": {}},
    )
    patch = merge_person_patch(
        hit,
        emails=[],
        urls=["https://lovelace.github.io/"],
        keywords=["paperful"],
    )
    assert patch["homepage"]["primaryLinkUrl"] == "https://lovelace.github.io/"
    assert "secondaryLinks" not in patch["homepage"]


def test_sync_creates_miss_and_skips_ambiguous(cfg, monkeypatch):
    from paperful.twenty import apply_sync_actions, plan_sync
    from paperful.zot import CreatorPerson

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    calls: list[tuple[str, str]] = []

    def sender(method, url, headers, params, body):
        calls.append((method, url))
        filt = (params or {}).get("filter", "")
        if method == "GET" and "Babbage" in filt:
            return _people_payload(
                [
                    {"id": "1", "name": {"firstName": "Charles", "lastName": "Babbage"}},
                    {"id": "2", "name": {"firstName": "Charles", "lastName": "Babbage"}},
                ]
            )
        if method == "GET":
            return _people_payload([])
        if method == "POST" and url.endswith("/people"):
            assert body["name"] == {"firstName": "Ada", "lastName": "Lovelace"}
            assert "paperful" in body["keywords"]
            return {
                "data": {
                    "id": "new-ada",
                    "name": body["name"],
                    "keywords": body["keywords"],
                }
            }
        if method == "POST" and url.endswith("/notes"):
            return {"data": {"id": "note-9"}}
        return {"data": {"id": "x"}}

    items = [
        make_item(
            creator_people=[
                CreatorPerson(first="Ada", last="Lovelace", display="Ada Lovelace")
            ],
            corporate_creators=["FAO"],
        ),
        make_item(
            key="B",
            creator_people=[
                CreatorPerson(first="Charles", last="Babbage", display="Charles Babbage")
            ],
        ),
    ]
    planned = plan_sync(
        cfg, items, collection="BBNJ", sender=sender, sleeper=lambda _s: None
    )
    by_name = {row.name: row.action for row in planned}
    assert by_name["FAO"] == "skip-corporate"
    assert by_name["Ada Lovelace"] == "create"
    assert by_name["Charles Babbage"] == "ambiguous"
    apply_sync_actions(
        cfg, planned, collection="BBNJ", sender=sender, sleeper=lambda _s: None
    )
    posts = [url for method, url in calls if method == "POST" and url.endswith("/people")]
    assert len(posts) == 1
    contact = json.loads(next((cfg.state_dir / "author-contacts").glob("*.json")).read_text())
    assert contact["twenty_id"] == "new-ada"


def test_author_site_cache_and_policy_order(cfg):
    from paperful.routing import apply_fetch_order, order_run, source_applicable
    from paperful.twenty import author_site_ready, resolve_listing
    from paperful.zot import CreatorPerson

    cfg.twenty_enabled = False
    item = make_item(
        has_pdf=False,
        creator_people=[
            CreatorPerson(first="Ada", last="Lovelace", display="Ada Lovelace")
        ],
        creator_surnames=["Lovelace"],
    )
    folder = cfg.state_dir / "author-contacts"
    folder.mkdir(parents=True)
    (folder / "lovelace-a.json").write_text(
        json.dumps(
            {
                "schema": "paperful.author_contact.v1",
                "fingerprint": "lovelace|a",
                "website": "https://lovelace.github.io/papers/",
            }
        ),
        encoding="utf-8",
    )
    assert author_site_ready(item, cfg)
    assert source_applicable(item, cfg, "author_site")
    listed = resolve_listing(item, cfg, live=False)
    assert listed is not None and "github.io" in listed.listing_url
    lanes = apply_fetch_order(
        cfg, ["unpaywall", "author_site", "scholar", "scihub"], item
    )
    assert lanes.index("unpaywall") < lanes.index("author_site") < lanes.index("scholar")
    steps = [step.name for step in order_run(cfg, ["ezproxy", "author_site", "scholar"])]
    assert steps.index("author_site") < steps.index("scholar")


def test_writeback_off_does_not_patch(cfg, monkeypatch):
    from paperful.twenty import writeback_author_listing

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    cfg.twenty_writeback_listings = False
    called = {"n": 0}

    def sender(*_a, **_k):
        called["n"] += 1
        return {}

    status = writeback_author_listing(
        cfg,
        PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a"),
        "https://lovelace.github.io/",
        sender=sender,
    )
    assert status == "off"
    assert called["n"] == 0


def test_writeback_appends_searx_listing(cfg, monkeypatch):
    from paperful.twenty import writeback_author_listing

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    cfg.twenty_writeback_listings = True
    patches: list[dict] = []

    def sender(method, url, headers, params, body):
        if method == "GET":
            return _people_payload(
                [
                    {
                        "id": "abc",
                        "name": {"firstName": "Ada", "lastName": "Lovelace"},
                        "homepage": {"primaryLinkUrl": "https://ada.example.edu/"},
                    }
                ]
            )
        if method == "PATCH" and "people" in url:
            patches.append(body)
            return {"data": {"id": "abc"}}
        if method == "POST" and url.endswith("/notes"):
            return {"data": {"id": "note-1"}}
        return {"data": {"id": "t"}}

    status = writeback_author_listing(
        cfg,
        PackAuthor(name="Ada Lovelace", fingerprint="lovelace|a"),
        "https://lovelace.github.io/papers/",
        collection="ocean/BBNJ",
        source="searxng",
        sender=sender,
        sleeper=lambda _s: None,
    )
    assert status == "enrich"
    assert patches[0]["homepage"]["primaryLinkUrl"] == "https://ada.example.edu/"
    assert patches[0]["homepage"]["secondaryLinks"][0]["url"].startswith(
        "https://lovelace.github.io/"
    )
    assert "paperful" in patches[0]["keywords"]


def test_sync_resume_skips_finished_fingerprint(cfg, monkeypatch):
    from paperful.twenty import plan_sync
    from paperful.zot import CreatorPerson

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_base_url = "https://api.twenty.example"
    progress = cfg.state_dir / "twenty-sync" / "bbnj.jsonl"
    progress.parent.mkdir(parents=True)
    progress.write_text(
        json.dumps(
            {"fingerprint": "lovelace|a", "action": "create", "twenty_id": "abc"}
        )
        + "\n",
        encoding="utf-8",
    )

    def sender(*_args, **_kwargs):
        raise AssertionError("resume should not call Twenty")

    item = make_item(
        creator_people=[
            CreatorPerson(first="Ada", last="Lovelace", display="Ada Lovelace")
        ]
    )
    rows = plan_sync(
        cfg, [item], collection="BBNJ", sender=sender, sleeper=lambda _s: None
    )
    assert rows[0].action == "unchanged"
    assert rows[0].note == "already synced"


def test_preflight_twenty_listing_before_searx(cfg, monkeypatch):
    from paperful.snowball.candidate import Candidate
    from paperful.snowball.preflight import run_author_site_preflight
    from rich.console import Console
    from io import StringIO

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    cfg.searxng_base_url = "http://127.0.0.1:9"

    def listing(*_args, **_kwargs):
        return "https://ada.github.io/"

    def searx(_query):
        raise AssertionError("SearXNG should wait until Twenty has no listing")

    monkeypatch.setattr("paperful.twenty.listing_for_author", listing)
    row = Candidate(
        run_id="r",
        seed={"type": "doi", "value": "10.1000/a"},
        hop=0,
        direction="refs",
        ids={"openalex": "A1"},
        biblio={
            "authors": ["Ada Lovelace"],
            "author_records": [
                {
                    "openalex": "A1",
                    "display_name": "Ada Lovelace",
                    "fingerprint": "lovelace|a",
                }
            ],
        },
        why="w",
        status="new",
        provenance={},
        gate="dry-run",
    )
    path = run_author_site_preflight(
        cfg,
        [row],
        dest=cfg.state_dir / "snowball" / "run1",
        collection="BBNJ",
        console=Console(file=StringIO(), highlight=False),
        searx_getter=searx,
    )
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "https://ada.github.io/" in text
    assert 'source = "twenty"' in text


def test_preflight_searx_writeback_when_flag_on(cfg, monkeypatch):
    from paperful.snowball.candidate import Candidate
    from paperful.snowball.preflight import run_author_site_preflight
    from rich.console import Console
    from io import StringIO

    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    cfg.searxng_base_url = "http://searx.local"
    cfg.twenty_writeback_listings = True
    seen: list[str] = []

    monkeypatch.setattr("paperful.twenty.listing_for_author", lambda *_a, **_k: "")

    def writeback(_cfg, author, url, **_kwargs):
        seen.append(url)
        assert author.name == "Ada Lovelace"
        return "enrich"

    monkeypatch.setattr("paperful.twenty.writeback_author_listing", writeback)
    row = Candidate(
        run_id="r",
        seed={"type": "doi", "value": "10.1000/a"},
        hop=0,
        direction="refs",
        ids={"openalex": "A1"},
        biblio={
            "authors": ["Ada Lovelace"],
            "author_records": [
                {
                    "openalex": "A1",
                    "display_name": "Ada Lovelace",
                    "fingerprint": "lovelace|a",
                }
            ],
        },
        why="w",
        status="new",
        provenance={},
        gate="dry-run",
    )

    def searx(_query):
        return {
            "results": [
                {
                    "url": "https://lovelace.github.io/papers/a.pdf",
                    "title": "A",
                }
            ]
        }

    run_author_site_preflight(
        cfg,
        [row],
        dest=cfg.state_dir / "snowball" / "run2",
        collection="BBNJ",
        console=Console(file=StringIO(), highlight=False),
        searx_getter=searx,
    )
    assert seen == ["https://lovelace.github.io/papers/a.pdf"]
