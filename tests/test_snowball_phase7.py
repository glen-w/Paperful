"""Snowball hardening and author-site preflight (offline)."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, parse_dedupe_after
from paperful.doctor import _author_packs_check
from paperful.provenance import provenance_label, provenance_sentence
from paperful.snowball.authors import (
    AuthorPack,
    PackAuthor,
    build_coauthor_graph,
    classify_listing_url,
    matching_author,
    name_fingerprint,
    write_pack,
)
from paperful.snowball.candidate import Candidate
from paperful.snowball.command import (
    SnowballError,
    SnowballRequest,
    _apply_fingerprint_scope,
    _checked_cites_query,
    _fingerprint_rows,
    run_apply,
    run_resume,
)
from paperful.snowball.expand import compose_keyword_query, expand_search_term
from paperful.snowball.ingest import _fill_sources
from paperful.snowball.openalex import OpenAlexClient, work_to_candidate
from paperful.snowball.orcid import orcid_researcher_urls
from paperful.snowball.preflight import promote_pack, run_author_site_preflight
from paperful.snowball.queue import write_queue
from paperful.snowball.searxng import rank_hit
from paperful.snowball.seeds import dois_from_seeds, parse_seed_lines, read_seeds_text
from paperful.zot import Item
from tests.textutil import plain_text

runner = CliRunner()


def _cfg(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir = tmp_path / "state"
    cfg.out_dir.mkdir()
    cfg.state_dir.mkdir()
    cfg.snowball_enabled = True
    cfg.email = "t@example.org"
    return cfg


def _row(**kwargs) -> Candidate:
    base = dict(
        run_id="r",
        seed={"type": "doi", "value": "10.1000/a"},
        hop=1,
        direction="refs",
        ids={"doi": "10.1000/a"},
        biblio={"title": "A", "authors": ["Ada Lovelace"]},
        why="w",
        status="new",
        provenance={},
        gate="dry-run",
    )
    base.update(kwargs)
    return Candidate(**base)


def test_trailing_star_expands_and_question_warns():
    text, notices = expand_search_term("polic*")
    assert "policy" in text or "polic" in text
    assert " OR " in text
    _, qn = expand_search_term("poli?y")
    assert qn
    assert compose_keyword_query(["bbnj EIA"]) == "bbnj EIA"
    assert compose_keyword_query(["msp", "ore"]) == '"msp" AND "ore"'
    notices2: list[str] = []
    composed = compose_keyword_query(["polic*"], notices=notices2)
    assert "polic" in composed


def test_parse_seed_lines_and_doi_validation():
    tokens = parse_seed_lines("# c\n10.1000/a\n10.1000/a\nhttps://doi.org/10.1000/b\n")
    assert tokens[0] == "10.1000/a"
    dois = dois_from_seeds(tokens)
    assert dois == ["10.1000/a", "10.1000/b"]


def test_resume_fingerprint_marks_exists(tmp_path: Path):
    cfg = _cfg(tmp_path)
    row = _row(ids={"doi": "10.1000/have", "openalex": "W1"})
    held = Item(
        key="HAVE",
        item_type="journalArticle",
        title="Have",
        doi="10.1000/have",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Ada",
        collection_paths=["Inbox/Snowball"],
    )

    class Lib:
        def items_in_scope(self, keys):
            del keys
            return [held]

    console = Console(file=StringIO(), highlight=False)
    request = SnowballRequest(gate="auto", collection="Inbox/Snowball", dedupe_scope="library")
    _fingerprint_rows(cfg, request, [row], backend=Lib(), console=console)
    assert row.status == "exists"


def test_resume_skips_library_hit_on_auto_create(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = OpenAlexClient(email="t@example.org", sleep_s=0)
    have = _row(
        ids={"doi": "10.1000/have", "openalex": "W9"},
        biblio={"title": "Have", "year": 2020, "authors": ["Ada"]},
    )
    dest = write_queue(cfg.state_dir, "run1", [], client, library_unread=False)
    (dest / "deferred.json").write_text(
        json.dumps({"kind": "refs", "remaining_ids": ["W9"], "run_id": "run1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "paperful.snowball.crawl.continue_deferred", lambda oa, deferred: [have]
    )
    created: list[str] = []

    def create_new(lib, rows, collection, **kwargs):
        created.extend(row.ids.get("doi") or "" for row in rows)
        return [], {"created": len(rows), "skipped_exists": 0, "failed": 0}

    monkeypatch.setattr("paperful.snowball.command.create_new", create_new)
    held = Item(
        key="HAVE",
        item_type="journalArticle",
        title="Have",
        doi="10.1000/have",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Ada",
        collection_paths=["Inbox/Snowball"],
    )

    class Lib:
        def items_in_scope(self, keys):
            del keys
            return [held]

    run_resume(
        cfg,
        "run1",
        SnowballRequest(gate="auto", collection="Inbox/Snowball"),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
        backend=Lib(),
    )
    assert created == []
    disk = json.loads((dest / "candidates.jsonl").read_text().splitlines()[0])
    assert disk["status"] == "exists"


def test_work_to_candidate_keeps_author_ids():
    work = {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/x",
        "display_name": "Paper",
        "publication_year": 2021,
        "type": "article",
        "cited_by_count": 1,
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A1",
                    "display_name": "Ada Lovelace",
                    "orcid": "https://orcid.org/0000-0002-1825-0097",
                }
            }
        ],
        "primary_location": {},
        "open_access": {},
    }
    row = work_to_candidate(
        work, run_id="r", seed={"type": "doi", "value": "10.1000/x"}, hop=0, direction="refs", why="s", gate="dry-run"
    )
    recs = row.biblio["author_records"]
    assert recs[0]["openalex"] == "A1"
    assert recs[0]["orcid"] == "0000-0002-1825-0097"
    assert recs[0]["fingerprint"] == "lovelace|a"


def test_coauthor_graph_ranks_by_frequency():
    a = {
        "openalex": "A1",
        "orcid": "",
        "display_name": "Ada Lovelace",
        "fingerprint": "lovelace|a",
    }
    b = {
        "openalex": "A2",
        "orcid": "",
        "display_name": "Charles Babbage",
        "fingerprint": "babbage|c",
    }
    rows = [
        _row(
            ids={"doi": "10.1000/1"},
            biblio={"authors": ["Ada Lovelace", "Charles Babbage"], "author_records": [a, b]},
        ),
        _row(
            ids={"doi": "10.1000/2"},
            biblio={"authors": ["Ada Lovelace"], "author_records": [a]},
        ),
    ]
    graph = build_coauthor_graph(rows, max_authors=5)
    assert graph["ranked"][0] == "openalex:A1"
    assert graph["nodes"][0]["frequency"] == 2


def test_simple_host_and_blocked():
    assert classify_listing_url("https://ada.github.io/papers/")
    assert not classify_listing_url("https://www.researchgate.net/profile/Ada")


def test_orcid_researcher_urls_from_person_payload():
    payload = {
        "researcher-urls": {
            "researcher-url": [
                {"url": {"value": "https://ada.github.io/"}},
                {"url": {"value": "https://www.researchgate.net/profile/x"}},
            ]
        }
    }
    urls = orcid_researcher_urls("0000-0002-1825-0097", getter=lambda _id: payload)
    assert "https://ada.github.io/" in urls


def test_preflight_writes_proposed_pack(tmp_path: Path):
    cfg = _cfg(tmp_path)
    rec = {
        "openalex": "A1",
        "orcid": "0000-0002-1825-0097",
        "display_name": "Ada Lovelace",
        "fingerprint": "lovelace|a",
    }
    rows = [
        _row(
            ids={"doi": "10.1000/1"},
            biblio={"authors": ["Ada Lovelace"], "author_records": [rec]},
        )
    ]
    dest = cfg.state_dir / "snowball" / "run1"
    path = run_author_site_preflight(
        cfg,
        rows,
        dest=dest,
        collection="Inbox/Snowball",
        console=Console(file=StringIO(), highlight=False),
        orcid_getter=lambda _id: {
            "researcher-urls": {
                "researcher-url": [{"url": {"value": "https://ada.github.io/"}}]
            }
        },
    )
    assert path is not None and path.is_file()
    assert "proposed" in path.name
    promoted = promote_pack(cfg, "inbox-snowball")
    assert promoted.is_file()
    assert "proposed" not in promoted.name


def test_searxng_rank_surname_in_host():
    assert rank_hit("https://mendenhall.github.io/paper.pdf", surname="mendenhall") > rank_hit(
        "https://publisher.example/article", surname="mendenhall"
    )
    assert rank_hit("https://www.researchgate.net/x.pdf", surname="mendenhall") < 0


def test_author_site_source_applicable_with_pack(tmp_path: Path):
    from paperful.routing import source_applicable
    from paperful.snowball.authors import pack_path

    cfg = _cfg(tmp_path)
    pack = AuthorPack(
        name="inbox-snowball",
        collection="Inbox/Snowball",
        status="promoted",
        authors=[
            PackAuthor(
                name="Ada Lovelace",
                fingerprint="lovelace|a",
                listing_url="https://ada.github.io/",
                base_host="ada.github.io",
            )
        ],
    )
    write_pack(pack_path(cfg, "inbox-snowball", promoted=True), pack)
    item = Item(
        key="K",
        item_type="journalArticle",
        title="Paper",
        doi="10.1000/x",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Lovelace",
        collection_paths=["Inbox/Snowball"],
        creator_surnames=["Lovelace"],
    )
    assert matching_author(item, cfg) is not None
    assert source_applicable(item, cfg, "author_site") is True
    other = Item(
        key="Z",
        item_type="journalArticle",
        title="Other",
        doi="10.1000/z",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Nobody",
        collection_paths=["Inbox/Snowball"],
        creator_surnames=["Nobody"],
    )
    assert source_applicable(other, cfg, "author_site") is False


def test_grey_author_site_stamp():
    assert provenance_label("author_site") == "grey:author_site"
    assert provenance_sentence("author_site") == "Saved from an author site."


def test_parse_dedupe_after():
    assert parse_dedupe_after("off") == "off"
    assert parse_dedupe_after("classify") == "classify"
    assert parse_dedupe_after("apply") == "apply"


def test_cli_flags_on_doi_help():
    res = runner.invoke(cli.app, ["snowball", "doi", "--help"])
    assert res.exit_code == 0
    out = plain_text(res.stdout)
    assert "--dedupe-scope" in out
    assert "--seeds-file" in out
    assert "--dedupe-after" in out
    assert "author-site" in out


def test_name_fingerprint():
    assert name_fingerprint("Ada Lovelace") == "lovelace|a"


def test_apply_scope_ignores_config_and_needs_explicit_flag():
    assert _apply_fingerprint_scope(SnowballRequest()) == "library"
    assert _apply_fingerprint_scope(SnowballRequest(dedupe_scope="collection")) == "collection"
    assert _apply_fingerprint_scope(SnowballRequest(dedupe_scope="none")) == "none"


def test_apply_library_default_skips_other_collection_hit(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg.snowball_dedupe_scope = "collection"
    client = OpenAlexClient(email="t@example.org", sleep_s=0)
    row = _row(
        keep=True,
        ids={"doi": "10.1000/have", "openalex": "W1"},
        biblio={"title": "Have", "year": 2020, "authors": ["Ada"]},
    )
    write_queue(cfg.state_dir, "apply1", [row], client, library_unread=False)
    held = Item(
        key="HAVE",
        item_type="journalArticle",
        title="Have",
        doi="10.1000/have",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Ada",
        collection_paths=["Other"],
    )

    class Lib:
        def __init__(self) -> None:
            self.created: list[dict] = []

        def items_in_scope(self, keys):
            del keys
            return [held]

        def ensure_collection_path(self, path: str) -> str:
            return "COL1"

        def create_parent(self, data: dict) -> str:
            self.created.append(data)
            return "ITEM1"

        def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
            del item_key, html, tag
            return "NOTE"

    lib = Lib()
    console = Console(file=StringIO(), highlight=False, width=120)
    run_apply(
        cfg,
        "apply1",
        SnowballRequest(collection="Inbox/Snowball"),
        console=console,
        backend=lib,
    )
    assert lib.created == []

    write_queue(cfg.state_dir, "apply2", [row], client, library_unread=False)
    lib2 = Lib()
    run_apply(
        cfg,
        "apply2",
        SnowballRequest(collection="Inbox/Snowball", dedupe_scope="collection"),
        console=console,
        backend=lib2,
    )
    assert lib2.created


def test_fill_sources_prepends_author_site(tmp_path: Path):
    from paperful.snowball.authors import pack_path

    cfg = _cfg(tmp_path)
    cfg.sources = ["unpaywall", "openalex"]
    pack = AuthorPack(
        name="inbox-snowball",
        collection="Inbox/Snowball",
        status="promoted",
        authors=[
            PackAuthor(
                name="Ada Lovelace",
                fingerprint="lovelace|a",
                listing_url="https://ada.github.io/",
                base_host="ada.github.io",
            )
        ],
    )
    write_pack(pack_path(cfg, "inbox-snowball", promoted=True), pack)
    item = Item(
        key="K",
        item_type="journalArticle",
        title="Paper",
        doi="10.1000/x",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Lovelace",
        collection_paths=["Inbox/Snowball"],
        creator_surnames=["Lovelace"],
    )
    assert _fill_sources(cfg, [item])[0] == "author_site"
    cfg.sources = ["author_site", "unpaywall"]
    assert _fill_sources(cfg, [item]) == ["author_site", "unpaywall"]


def test_seeds_refuse_tty_and_invalid_doi():
    class Tty:
        def isatty(self) -> bool:
            return True

        def read(self) -> str:
            return "10.1000/a\n"

    with pytest.raises(SnowballError, match="TTY"):
        read_seeds_text("-", stdin=Tty())
    with pytest.raises(SnowballError, match="Not a DOI"):
        dois_from_seeds(["not-a-doi"])


def test_cli_flags_on_search_and_watch_help():
    search = runner.invoke(cli.app, ["snowball", "search", "--help"])
    assert search.exit_code == 0
    search_out = plain_text(search.stdout)
    assert "--dedupe-scope" in search_out
    assert "author-site" in search_out
    watch = runner.invoke(cli.app, ["snowball", "watch", "run", "--help"])
    assert watch.exit_code == 0
    assert "--dedupe-scope" in plain_text(watch.stdout)


def test_cites_query_expands_stems():
    query = _checked_cites_query(
        SnowballRequest(cites_query="polic*", direction="refs"),
        "refs",
        expands=True,
    )
    assert "polic" in query


def test_doctor_author_packs_proposed(tmp_path: Path):
    cfg = _cfg(tmp_path)
    (cfg.state_dir / "author-packs").mkdir()
    (cfg.state_dir / "author-packs" / "inbox-snowball.proposed.toml").write_text(
        "name = 'inbox-snowball'\n",
        encoding="utf-8",
    )
    check = _author_packs_check(cfg)
    assert check.status == "green"
    assert "proposed" in check.detail
