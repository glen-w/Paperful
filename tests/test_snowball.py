"""Snowball dry-run, creates, and PDF handoff. No live network."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, load_config
from paperful.run_config import RunConfigError, resolve_run_config
from paperful.snowball.command import (
    SnowballError,
    SnowballRequest,
    run_apply,
    run_collection,
    run_doi,
    run_hybrid,
    run_orcid,
    run_resume,
    run_search,
)
from paperful.snowball.expand import MAX_DEPTH, cap_ids, clamp_depth, keyword_depth, truncate
from paperful.snowball.candidate import Candidate
from paperful.snowball.openalex import OpenAlexBudgetExceeded, OpenAlexClient, _is_budget, keyless_limit_message
from paperful.zot import Item

runner = CliRunner()


def _work(oa: str, doi: str, title: str, year: int, cites: int, refs: list[str] | None = None) -> dict:
    return {
        "id": f"https://openalex.org/{oa}",
        "doi": f"https://doi.org/{doi}",
        "display_name": title,
        "publication_year": year,
        "type": "article",
        "cited_by_count": cites,
        "referenced_works": [f"https://openalex.org/{ref}" for ref in (refs or [])],
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {"source": {"display_name": "Marine Policy"}, "landing_page_url": "https://example.test/a"},
    }


def _client(works: dict[str, dict], *, citing: dict[str, list[str]] | None = None) -> OpenAlexClient:
    citing = citing or {}

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if work["doi"].endswith(doi):
                    return work
            return {}
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[i] for i in ids if i in works]}
        if "cites:" in filt:
            seed = ""
            for part in filt.split(","):
                if part.startswith("cites:"):
                    seed = part.split(":", 1)[1]
            ids = citing.get(seed, [])
            return {"results": [works[i] for i in ids if i in works]}
        if "author.orcid:" in filt:
            return {"results": []}
        if "search" in params:
            return {"results": list(works.values())}
        return {"results": []}

    return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)


def _cfg(tmp_path: Path, **extra: str) -> Config:
    body = f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
    body += "[snowball]\nenabled = true\n"
    body += extra.get("more", "")
    path = tmp_path / "config.toml"
    path.write_text(body)
    return load_config(path)


def test_stop_rules_clamp_and_cap():
    assert clamp_depth(2) == (2, None)
    assert clamp_depth(MAX_DEPTH + 3) == (MAX_DEPTH, f"depth clamped to {MAX_DEPTH}")
    assert keyword_depth(None) == 0
    assert keyword_depth(2) == 2
    assert cap_ids(["b", "a", "b", "c"], 2) == ["b", "a"]
    assert cap_ids(["b", "a", "b", "c"], 0) == ["b", "a", "c"]
    from paperful.config import parse_cap, parse_per_hop_rank
    from paperful.snowball.expand import sample_ids, select_works_by_citations
    import random

    assert parse_cap("all") == 0
    assert parse_cap("unlimited") == 0
    assert parse_cap(25) == 25
    assert parse_per_hop_rank("least-cited") == "least-cited"
    works = [
        {"id": "W1", "cited_by_count": 10},
        {"id": "W2", "cited_by_count": 2},
        {"id": "W3", "cited_by_count": 50},
    ]
    top = select_works_by_citations(works, 2, "most-cited", id_of=lambda w: w["id"])
    assert [w["id"] for w in top] == ["W3", "W1"]
    low = select_works_by_citations(works, 2, "least-cited", id_of=lambda w: w["id"])
    assert [w["id"] for w in low] == ["W2", "W1"]
    assert len(select_works_by_citations(works, 0, "most-cited")) == 3
    assert sample_ids(["a", "b", "c"], 2, rng=random.Random(0)) == sample_ids(
        ["a", "b", "c"], 2, rng=random.Random(0)
    )
    assert len(sample_ids(["a", "b", "c"], 2, rng=random.Random(1))) == 2
    rows = [
        Candidate("r", {"type": "doi", "value": "x"}, 1, "refs", {"doi": "10.1/b"}, {}, "w", "new", {}, "dry-run", score=1),
        Candidate("r", {"type": "doi", "value": "x"}, 1, "refs", {"doi": "10.1/a"}, {}, "w", "new", {}, "dry-run", score=5),
        Candidate("r", {"type": "doi", "value": "x"}, 1, "refs", {"doi": "10.1/c"}, {}, "w", "exists", {}, "dry-run", score=5),
    ]
    kept = truncate(rows, 2)
    assert [row.ids["doi"] for row in kept] == ["10.1/a", "10.1/c"]
    assert len(truncate(rows, 0)) == 3


def test_tally_line_names_the_totals():
    from paperful.snowball.tally import Tally

    lines: list[str] = []
    tally = Tally(lines.append, interval_s=60)
    tally.stage = "hop 2/2 references · 80 ids"
    tally.searches = 12
    tally.papers = 40
    tally.fields = 3
    tally.report()
    assert lines == ["hop 2/2 references · 80 ids · 12 searches · 40 papers"]
    tally.stage = "hop 2/2 cited-by 2/9 W2"
    tally.searches = 14
    tally.papers = 55
    tally.report()
    assert lines[-1] == "hop 2/2 cited-by 2/9 W2 · 2 searches · 15 papers"
    tally.stage = "crossref"
    tally.searches = 16
    tally.fields = 7
    tally.report()
    assert lines[-1] == "crossref · 2 searches · 4 fields updated"
    tally.stage = "creating"
    tally.created = 4
    tally.report()
    assert lines[-1] == "creating · 4 created"
    tally.stage = "fetching PDFs"
    tally.bind_pdfs(lambda: 2)
    assert tally.line() == "fetching PDFs · 2 PDFs"
    tally.stop()
    assert len(lines) == 4

    class _Bar:
        def __init__(self) -> None:
            self.updates: list[dict] = []
            self.stopped = False

        def update(self, task_id: int, **kwargs) -> None:
            self.updates.append(kwargs)

        def stop(self) -> None:
            self.stopped = True

    bar = _Bar()
    live = Tally(lines.append, interval_s=60)
    live.stage = "hop 2/2 references · 10 ids"
    live.bind_bar(bar, 1)
    live.track(10)
    live.advance(4)
    assert bar.updates[-1]["completed"] == 4
    assert bar.updates[-1]["total"] == 10
    assert "[cyan]" in bar.updates[-1]["description"]
    assert "searches" in bar.updates[-1]["description"]
    live.stage = "creating"
    live.created = 1
    live.track(3)
    live.advance(1)
    assert "[green]" in bar.updates[-1]["description"]
    live.stop()
    assert bar.stopped

    counted = Tally(lines.append, interval_s=60)
    client = OpenAlexClient(
        email="t@example.org",
        api_key="",
        sleep_s=0,
        getter=lambda _path, _params: {"results": [{"id": "W1"}, {"id": "W2"}]},
    )
    client.tally = counted
    client.get("/works", {})
    assert counted.searches == 1
    assert counted.papers == 2

    from paperful.snowball.fill import fill_crossref

    row = Candidate(
        "r",
        {"type": "doi", "value": "x"},
        1,
        "refs",
        {"doi": "10.1/b"},
        {},
        "w",
        "new",
        {},
        "dry-run",
    )
    fill_crossref(
        [row],
        lambda _doi: {"title": "T", "year": 2020, "venue": "V", "authors": ["A"]},
        tally=counted,
    )
    assert counted.searches == 2
    assert counted.fields == 4
    assert row.biblio["title"] == "T"


def test_doi_refs_and_keyword_hits(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 3, ["W2", "W3"]),
        "W2": _work("W2", "10.1000/b", "Bee", 2019, 1),
        "W3": _work("W3", "10.1000/a", "Aye", 2018, 9),
    }
    cfg = _cfg(tmp_path)
    buf = StringIO()
    console = Console(file=buf, highlight=False, width=200, force_terminal=False)
    client = _client(works)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=1),
        console=console,
        client=client,
        lookup=lambda doi, title: "EXIST" if doi == "10.1000/a" else None,
    )
    assert result.exit_code == 0
    lines = (result.run_dir / "candidates.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert {row["ids"]["doi"] for row in rows} == {"10.1000/a", "10.1000/b"}
    text = buf.getvalue()
    assert "hop 1/1" in text
    assert "searches" in text and "papers" in text
    assert "fields updated" not in text and "PDFs" not in text
    by_doi = {row["ids"]["doi"]: row for row in rows}
    assert by_doi["10.1000/a"]["hop"] == 1
    assert by_doi["10.1000/a"]["direction"] == "refs"
    assert by_doi["10.1000/a"]["provenance"]["backend"] == "openalex"
    assert by_doi["10.1000/a"]["status"] == "exists"
    assert by_doi["10.1000/b"]["status"] == "new"
    again = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    again_rows = [json.loads(line) for line in (again.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert [row["ids"]["doi"] for row in again_rows] == [row["ids"]["doi"] for row in rows]

    search = run_search(
        cfg,
        "bbnj",
        SnowballRequest(),
        console=console,
        client=_client({"W9": _work("W9", "10.1000/hit", "Hit", 2021, 2)}),
        lookup=lambda doi, title: None,
    )
    hit = json.loads((search.run_dir / "candidates.jsonl").read_text().splitlines()[0])
    assert hit["hop"] == 0
    assert hit["direction"] == "search"


def test_depth_two_and_cited_by(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 3, ["W2"]),
        "W2": _work("W2", "10.1000/mid", "Mid", 2019, 1, ["W3"]),
        "W3": _work("W3", "10.1000/deep", "Deep", 2018, 1),
        "W4": _work("W4", "10.1000/cite", "Citer", 2021, 2),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=200)
    depth2 = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=2),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    dois = {json.loads(line)["ids"]["doi"] for line in (depth2.run_dir / "candidates.jsonl").read_text().splitlines()}
    assert dois == {"10.1000/mid", "10.1000/deep"}
    hops = {
        json.loads(line)["ids"]["doi"]: json.loads(line)["hop"]
        for line in (depth2.run_dir / "candidates.jsonl").read_text().splitlines()
    }
    assert hops["10.1000/mid"] == 1
    assert hops["10.1000/deep"] == 2

    cites = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="cites", depth=1),
        console=console,
        client=_client(works, citing={"W1": ["W4"]}),
        lookup=lambda doi, title: None,
    )
    cite_rows = [json.loads(line) for line in (cites.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert len(cite_rows) == 1
    assert cite_rows[0]["ids"]["doi"] == "10.1000/cite"
    assert cite_rows[0]["direction"] == "cites"


class _Lib:
    def __init__(self, items: list[Item] | None = None):
        self.created: list[dict] = []
        self.notes: list[tuple[str, str]] = []
        self._items = items or []

    def ensure_collection_path(self, path: str) -> str:
        assert path == "Inbox/Snowball"
        return "COL1"

    def create_parent(self, data: dict) -> str:
        self.created.append(data)
        return f"ITEM{len(self.created)}"

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        self.notes.append((item_key, html, tag))
        return "NOTE"

    def resolve_collection(self, spec: str):
        class Root:
            key = "COLSEED"

        assert spec == "Inbox/Seeds"
        return Root()

    def subtree_keys(self, root) -> list[str]:
        return [root.key]

    def items_in_scope(self, keys: list[str]) -> list[Item]:
        return list(self._items)


def test_auto_creates_only_new_and_fetch_pdfs_uses_those_keys(tmp_path: Path, monkeypatch):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/new", "New paper", 2019, 4),
    }
    cfg = _cfg(tmp_path)
    lib = _Lib()
    seen: list[Item] = []

    def fake_fill(cfg, backend, items, console, **_kwargs):
        seen.extend(items)

        class Stats:
            attached = 1
            attach_failed = 0
            not_found = 0

        return Stats()

    monkeypatch.setattr("paperful.snowball.command.fill_pdfs", fake_fill)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", fetch_pdfs=True),
        console=Console(highlight=False, width=200),
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert result.exit_code == 0
    assert len(lib.created) == 1
    assert lib.created[0]["DOI"] == "10.1000/new"
    assert lib.created[0]["collections"] == ["COL1"]
    assert {tag["tag"] for tag in lib.created[0]["tags"]} >= {"paperful-snowball", "paperful-snowball:openalex"}
    assert lib.notes[0][0] == "ITEM1"
    assert "mailto" not in lib.notes[0][1]
    assert "OPENALEX" not in lib.notes[0][1]
    assert "10.1000/seed" in lib.notes[0][1]
    assert [item.key for item in seen] == ["ITEM1"]
    report = json.loads((result.run_dir / "write_report.json").read_text())
    assert report["created"] == 1
    assert report["attach_ok"] == 1

    lib2 = _Lib()
    monkeypatch.setattr("paperful.snowball.command.fill_pdfs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no pdf")))
    run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", fetch_pdfs=False),
        console=Console(highlight=False, width=200),
        client=_client(works),
        lookup=lambda doi, title: "HAVE" if doi == "10.1000/new" else None,
        backend=lib2,
    )
    assert lib2.created == []


def test_dry_run_does_not_create(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/new", "New paper", 2019, 1),
    }
    lib = _Lib()
    run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(fetch_pdfs=False),
        console=Console(highlight=False, width=120),
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert lib.created == []


def test_approve_batch_and_apply(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2", "W3"]),
        "W2": _work("W2", "10.1000/keep", "Keep me", 2019, 4),
        "W3": _work("W3", "10.1000/skip", "Skip me", 2018, 1),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=160)
    queued = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(gate="approve-batch", collection="Inbox/Snowball"),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    lines = (queued.run_dir / "candidates.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert all(row.get("keep") is False for row in rows)
    for row in rows:
        if row["ids"]["doi"] == "10.1000/keep":
            row["keep"] = True
    (queued.run_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )
    lib = _Lib()
    applied = run_apply(
        cfg,
        queued.run_dir.name,
        SnowballRequest(collection="Inbox/Snowball"),
        console=console,
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert applied.exit_code == 0
    assert len(lib.created) == 1
    assert lib.created[0]["DOI"] == "10.1000/keep"
    report = json.loads((applied.run_dir / "write_report.json").read_text())
    assert report["created"] == 1


def test_orcid_seeds(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/ego", "Ego", 2020, 2, ["W2"]),
        "W2": _work("W2", "10.1000/ref", "Ref", 2019, 1),
    }
    cfg = _cfg(tmp_path)

    def getter(orcid: str):
        assert orcid == "0000-0002-9162-9618"
        return {
            "group": [
                {
                    "work-summary": [
                        {
                            "external-ids": {
                                "external-id": [
                                    {"external-id-type": "doi", "external-id-value": "10.1000/ego"}
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    result = run_orcid(
        cfg,
        "0000-0002-9162-9618",
        SnowballRequest(depth=1),
        console=Console(highlight=False, width=160),
        client=_client(works),
        lookup=lambda doi, title: None,
        orcid_getter=getter,
    )
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    dois = {row["ids"]["doi"] for row in rows}
    assert "10.1000/ego" in dois
    assert "10.1000/ref" in dois
    by_doi = {row["ids"]["doi"]: row for row in rows}
    assert by_doi["10.1000/ego"]["hop"] == 0
    assert by_doi["10.1000/ref"]["hop"] == 1


def test_collection_seeds(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/new", "New", 2019, 1),
    }
    cfg = _cfg(tmp_path)
    item = Item(
        key="K1",
        item_type="journalArticle",
        title="Seed",
        doi="10.1000/seed",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author=None,
        collection_paths=["Inbox/Seeds"],
        doi_source="crossref",
    )
    lib = _Lib(items=[item])
    result = run_collection(
        cfg,
        "Inbox/Seeds",
        SnowballRequest(collection="Inbox/Snowball"),
        console=Console(highlight=False, width=160),
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert {row["ids"]["doi"] for row in rows} == {"10.1000/new"}


def test_cli_refusals(tmp_path: Path):
    off = tmp_path / "off.toml"
    off.write_text(f'email = "t@example.org"\nstate_dir = "{tmp_path / "state"}"\n')
    assert runner.invoke(cli.app, ["snowball", "search", "bbnj", "-c", str(off)]).exit_code == 2
    assert runner.invoke(cli.app, ["snowball", "orcid", "0000-0002-9162-9618", "-c", str(off)]).exit_code == 2
    on = tmp_path / "on.toml"
    on.write_text(off.read_text() + "\n[snowball]\nenabled = true\n")
    refused = runner.invoke(
        cli.app, ["snowball", "doi", "10.1/x", "--gate", "approve-each", "-c", str(on)]
    )
    assert refused.exit_code == 2
    with pytest.raises(SnowballError, match="Invalid ORCID"):
        run_orcid(_cfg(tmp_path), "not-an-orcid", SnowballRequest(), console=Console())


def test_profile_list_labels_snowball(tmp_path: Path):
    from paperful.run_config import list_profiles

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('email = "t@example.org"\n')
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "doi-refs.toml").write_text(
        'kind = "snowball"\ndescription = "gated"\ngate = "approve-batch"\n'
    )
    listings = list_profiles(load_config(cfg_path))
    assert listings[0].name == "doi-refs"
    assert listings[0].description.startswith("snowball profile")
    assert "invalid" not in listings[0].description


def test_run_refuses_snowball_profile(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('email = "t@example.org"\n')
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "doi-refs.toml").write_text('kind = "snowball"\ngate = "dry-run"\n')
    cfg = load_config(cfg_path)
    with pytest.raises(RunConfigError, match="paperful snowball"):
        resolve_run_config(cfg, profile="doi-refs", use_run_policy=True)


def test_snowball_profile_loads_gate(tmp_path: Path):
    from paperful.snowball.profile import load_profile, request_from_profile

    cfg = _cfg(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "scout.toml").write_text(
        'kind = "snowball"\nmode = "search"\nquery = "bbnj"\ngate = "auto"\n'
        'target_collection = "Inbox/Snowball"\n'
    )
    raw = load_profile(cfg, "scout")
    request = request_from_profile(raw, cfg)
    assert request.gate == "auto"
    assert request.collection == "Inbox/Snowball"
    assert raw["query"] == "bbnj"


def test_failed_seed_exits_nonzero_and_summary(tmp_path: Path):
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=160)
    result = run_doi(
        cfg,
        ["10.1000/missing"],
        SnowballRequest(),
        console=console,
        client=_client({}),
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 1
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert rows[0]["status"] == "error"
    summary = json.loads((result.run_dir / "summary.json").read_text())
    assert summary["by_status"]["error"] == 1
    assert summary["requests"] >= 1
    assert "library_unread" in summary


def test_bad_direction_and_auto_without_collection_exit(tmp_path: Path):
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    with pytest.raises(SnowballError, match="direction must be"):
        run_doi(cfg, ["10.1000/seed"], SnowballRequest(direction="sideways"), console=console, client=_client({}))
    with pytest.raises(SnowballError, match="target collection"):
        run_doi(cfg, ["10.1000/seed"], SnowballRequest(gate="auto"), console=console, client=_client({}))


def test_dry_run_ignores_fetch_pdfs(tmp_path: Path, monkeypatch):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/new", "New paper", 2019, 1),
    }
    monkeypatch.setattr(
        "paperful.snowball.command.fill_pdfs",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")),
    )
    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(fetch_pdfs=True),
        console=Console(highlight=False, width=120),
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 0
    assert "write_report.json" not in [p.name for p in result.run_dir.iterdir()]


def test_auto_refuses_when_library_unread(tmp_path: Path, monkeypatch):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/new", "New paper", 2019, 1),
    }

    def boom(cfg):
        raise RuntimeError("zotero down")

    monkeypatch.setattr("paperful.snowball.command.get_backend", boom)
    with pytest.raises(SnowballError, match="Refusing to create"):
        run_doi(
            _cfg(tmp_path),
            ["10.1000/seed"],
            SnowballRequest(gate="auto", collection="Inbox/Snowball"),
            console=Console(highlight=False, width=120),
            client=_client(works),
        )


def test_doctor_snowball_row(monkeypatch):
    from paperful.doctor import _snowball_check

    off = _snowball_check(Config())
    assert off.name == "snowball" and off.detail == "off"
    enabled = Config(snowball_enabled=True, email="")
    assert _snowball_check(enabled).status == "amber"
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    probe = lambda email: "ok"
    ready = _snowball_check(Config(snowball_enabled=True, email="a@b.c"), probe=probe)
    assert "no OpenAlex key" in ready.detail
    assert "semantic scholar public (no key)" in ready.detail
    assert ready.status == "amber"
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    keyed = _snowball_check(Config(snowball_enabled=True, email="a@b.c"), probe=probe)
    assert "key set" in keyed.detail
    assert "secret-key" not in keyed.detail
    assert "a@b.c" not in keyed.detail
    down = _snowball_check(Config(snowball_enabled=True, email="a@b.c"), probe=lambda email: "unreachable")
    assert down.status == "amber"
    assert "unreachable" in down.detail
    from paperful.doctor import _openalex_probe_status

    assert _openalex_probe_status(401, keyed=True) == "key rejected"
    assert _openalex_probe_status(401, keyed=False) == "unauthorized"
    assert _openalex_probe_status(429, keyed=True) == "rate limited"
    assert _openalex_probe_status(200, keyed=True) == "ok"


def test_s2_paper_sends_key_only_when_set(tmp_path: Path, monkeypatch):
    from paperful.snowball.fill import s2_paper

    captured: dict = {}

    class Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"title": "Live"}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["headers"] = headers
        return Resp()

    monkeypatch.setattr("httpx.get", fake_get)
    cache = tmp_path / "cache"
    assert s2_paper("10.1000/live", cache_dir=cache, api_key="")["title"] == "Live"
    assert captured["headers"] is None
    (cache / "10.1000_live.json").unlink()
    assert s2_paper("10.1000/live", cache_dir=cache, api_key="test-key")["title"] == "Live"
    assert captured["headers"] == {"x-api-key": "test-key"}


def test_s2_rejected_key_is_not_a_miss(tmp_path: Path, monkeypatch):
    from paperful.snowball.fill import ApiKeyRejected, s2_paper

    class Resp:
        status_code = 401

        def raise_for_status(self) -> None:
            raise AssertionError("401 must not be treated as a normal HTTP miss")

        def json(self) -> dict:
            return {}

    monkeypatch.setattr("httpx.get", lambda *a, **k: Resp())
    with pytest.raises(ApiKeyRejected, match="rejected"):
        s2_paper("10.1000/denied", cache_dir=tmp_path / "cache", api_key="bad-key")


def test_s2_short_429_retries_then_returns(tmp_path: Path, monkeypatch):
    from paperful.snowball.fill import s2_paper
    import paperful.snowball.fill as fill

    fill._s2_next_ok = 0.0
    calls = {"n": 0}

    class Resp:
        def __init__(self, status: int):
            self.status_code = status
            self.headers = {"Retry-After": "0"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"title": "After retry"}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return Resp(429 if calls["n"] == 1 else 200)

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr(fill.time, "sleep", lambda _s: None)
    paper = s2_paper("10.1000/burst", cache_dir=tmp_path / "cache", api_key="test-key")
    assert paper is not None and paper["title"] == "After retry"
    assert calls["n"] == 2


def test_fill_resume_creates_rows_the_fill_added(tmp_path: Path, monkeypatch):
    from paperful.snowball.queue import write_queue

    cfg = _cfg(tmp_path)
    seed = Candidate(
        "r",
        {"type": "doi", "value": "10.1000/seed"},
        1,
        "refs",
        {"doi": "10.1000/seed"},
        {"title": "Seed"},
        "seed",
        "new",
        {"backend": "openalex"},
        "auto",
    )
    child = Candidate(
        "r",
        {"type": "doi", "value": "10.1000/seed"},
        2,
        "refs",
        {"doi": "10.1000/child"},
        {"title": "Child"},
        "s2 ref of 10.1000/seed",
        "new",
        {"backend": "semanticscholar"},
        "auto",
    )
    client = OpenAlexClient(email="t@example.org", sleep_s=0)
    dest = write_queue(cfg.state_dir, "run1", [seed], client, library_unread=False)
    (dest / "deferred.json").write_text(
        json.dumps({"kind": "fill", "direction": "refs", "per_hop_limit": 15}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "paperful.snowball.command._fill_metadata",
        lambda *a, **k: ([seed, child], {}),
    )
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda cfg: object())
    seen: dict[str, list[str]] = {}

    def create_new(lib, rows, collection, **kwargs):
        seen["dois"] = [row.ids.get("doi") for row in rows]
        return [], {"created": len(rows), "skipped_exists": 0, "failed": 0}

    monkeypatch.setattr("paperful.snowball.command.create_new", create_new)
    result = run_resume(
        cfg,
        "run1",
        SnowballRequest(gate="auto", collection="Snowball/bbnj-hop-test"),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
    )
    assert result.exit_code == 0
    assert seen["dois"] == ["10.1000/child"]


def test_year_window_and_direction_both(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 3, ["W2", "W3"]),
        "W2": _work("W2", "10.1000/old", "Old", 2010, 1),
        "W3": _work("W3", "10.1000/new", "New", 2019, 1),
        "W4": _work("W4", "10.1000/cite", "Citer", 2021, 2),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=160)
    filtered = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(year_from=2018, year_to=2020),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    window = [json.loads(line) for line in (filtered.run_dir / "candidates.jsonl").read_text().splitlines()]
    by_doi = {row["ids"]["doi"]: row for row in window}
    assert by_doi["10.1000/new"]["status"] == "new"
    assert by_doi["10.1000/old"]["status"] == "filtered"

    both = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="both", depth=1, per_hop_limit=5),
        console=console,
        client=_client(works, citing={"W1": ["W4"]}),
        lookup=lambda doi, title: None,
    )
    rows = [json.loads(line) for line in (both.run_dir / "candidates.jsonl").read_text().splitlines()]
    dirs = {row["direction"] for row in rows}
    assert dirs >= {"refs", "cites"}
    assert {row["ids"]["doi"] for row in rows} >= {"10.1000/old", "10.1000/new", "10.1000/cite"}


def test_keyword_depth_expand_and_soft_ceiling(tmp_path: Path):
    from paperful.snowball.expand import normalize_direction

    assert normalize_direction("references") == "refs"
    assert normalize_direction("citations") == "cites"
    assert clamp_depth(-3) == (0, None)
    assert truncate([], -1) == []

    works = {
        "W9": _work("W9", "10.1000/hit", "Hit", 2021, 2, ["W2"]),
        "W2": _work("W2", "10.1000/ref", "Ref", 2019, 1),
    }

    def getter(path: str, params: dict) -> dict:
        if "search" in params:
            return {"results": [works["W9"]]}
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[i] for i in ids if i in works]}
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if work["doi"].endswith(doi):
                    return work
            return {}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    search = run_search(
        cfg,
        "bbnj",
        SnowballRequest(depth=1),
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    rows = [json.loads(line) for line in (search.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert {row["hop"] for row in rows} == {0, 1}

    # Soft ceiling: request above MAX_DEPTH still runs at MAX_DEPTH.
    capped = run_doi(
        cfg,
        ["10.1000/hit"],
        SnowballRequest(depth=MAX_DEPTH + 2),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    assert capped.exit_code == 0


def test_orcid_openalex_fill_and_list_payload(tmp_path: Path):
    from paperful.snowball.orcid import orcid_dois
    from paperful.snowball.openalex import normalize_orcid, short_id

    assert normalize_orcid("https://orcid.org/0000-0002-9162-9618") == "0000-0002-9162-9618"
    assert normalize_orcid("0000000291629618") == "0000-0002-9162-9618"
    assert short_id("https://openalex.org/W1") == "W1"
    assert orcid_dois(
        "0000-0002-9162-9618",
        getter=lambda _o: [
            {
                "work-summary": [
                    {
                        "external-ids": {
                            "external-id": [
                                {"external-id-type": "doi", "external-id-value": "10.1000/list"}
                            ]
                        }
                    }
                ]
            }
        ],
    ) == ["10.1000/list"]

    works = {
        "W1": _work("W1", "10.1000/ego", "Ego", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/ref", "Ref", 2019, 1),
        "W9": _work("W9", "10.1000/oa-only", "OA only", 2018, 1),
    }

    def getter(path: str, params: dict) -> dict:
        filt = str(params.get("filter") or "")
        if "author.orcid:" in filt:
            return {"results": [works["W9"]]}
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if work["doi"].endswith(doi):
                    return work
            return {}
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[i] for i in ids if i in works]}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    result = run_orcid(
        _cfg(tmp_path),
        "0000-0002-9162-9618",
        SnowballRequest(depth=1),
        console=Console(highlight=False, width=120),
        client=client,
        lookup=lambda doi, title: None,
        orcid_getter=lambda _o: {"group": []},
    )
    dois = {json.loads(line)["ids"]["doi"] for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()}
    assert "10.1000/oa-only" in dois


def test_collection_empty_and_apply_skips_exists(tmp_path: Path):
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    empty = _Lib(items=[])
    with pytest.raises(SnowballError, match="No DOIs"):
        run_collection(cfg, "Inbox/Seeds", SnowballRequest(), console=console, backend=empty, client=_client({}))

    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]),
        "W2": _work("W2", "10.1000/keep", "Keep", 2019, 1),
    }
    queued = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(gate="approve-batch", collection="Inbox/Snowball"),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    rows = [json.loads(line) for line in (queued.run_dir / "candidates.jsonl").read_text().splitlines()]
    for row in rows:
        row["keep"] = True
    (queued.run_dir / "candidates.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    # First apply creates; second apply sees exists and creates nothing.
    lib = _Lib()
    run_apply(
        cfg,
        queued.run_dir.name,
        SnowballRequest(collection="Inbox/Snowball"),
        console=console,
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert len(lib.created) == 1
    lib2 = _Lib()
    again = run_apply(
        cfg,
        queued.run_dir.name,
        SnowballRequest(collection="Inbox/Snowball"),
        console=console,
        lookup=lambda doi, title: "HAVE",
        backend=lib2,
    )
    assert lib2.created == []
    report = json.loads((again.run_dir / "write_report.json").read_text())
    assert report["created"] == 0
    assert report["skipped_exists"] >= 1


def test_openalex_cites_and_ingest_types(tmp_path: Path):
    from paperful.snowball.ingest import _creators, _item_type
    from paperful.snowball.candidate import Candidate
    from paperful.snowball.queue import load_queue
    from paperful.snowball.profile import profile_path

    assert _item_type("posted-content") == "preprint"
    assert _item_type("book-chapter") == "bookSection"
    assert _item_type("book") == "book"
    assert _item_type("other") == "document"
    assert _creators(["Cher"]) == [{"creatorType": "author", "name": "Cher"}]
    assert _creators(["Ada Lovelace"])[0]["lastName"] == "Lovelace"

    row = Candidate(
        "r",
        {"type": "doi", "value": "x"},
        0,
        "refs",
        {"openalex": "W9"},
        {"title": "T", "year": 2020, "authors": [], "venue": "", "type": ""},
        "w",
        "new",
        {},
        "dry-run",
    )
    assert row.identity == "openalex:W9"

    client = _client(
        {"W1": _work("W1", "10.1000/seed", "Seed", 2020, 1), "W4": _work("W4", "10.1000/c", "C", 2021, 1)},
        citing={"W1": ["W4"]},
    )
    citing = client.works_citing("W1", limit=5)
    assert citing and citing[0]["id"].endswith("W4")
    assert client.works_citing("", limit=5) == []

    cfg = _cfg(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_queue(cfg.state_dir, "no-such-run")
    assert profile_path(cfg, "scout").name == "scout.toml"

    # Keyword soft-ceiling warning path (depth request above MAX_DEPTH).
    run_search(
        cfg,
        "bbnj",
        SnowballRequest(depth=MAX_DEPTH + 1),
        console=Console(highlight=False, width=80),
        client=_client({"W9": _work("W9", "10.1000/hit", "Hit", 2021, 2)}),
        lookup=lambda doi, title: None,
    )

    with pytest.raises(SnowballError, match="target collection"):
        run_apply(cfg, "x", SnowballRequest(), console=Console())

    # DOI seed that raises inside the client still records an error row.
    class Boom(OpenAlexClient):
        def work_by_doi(self, doi: str):
            raise RuntimeError("boom")

    boom = Boom(email="t@example.org", api_key="", sleep_s=0, getter=lambda *a, **k: {})
    failed = run_doi(
        cfg,
        ["10.1000/x"],
        SnowballRequest(),
        console=Console(highlight=False, width=80),
        client=boom,
        lookup=lambda doi, title: None,
    )
    assert failed.exit_code == 1
    assert json.loads((failed.run_dir / "candidates.jsonl").read_text().splitlines()[0])["status"] == "error"


def test_filters_dedupe_scope_and_partial_create(tmp_path: Path):
    from paperful.library import LibraryError
    from paperful.zot import Item

    book = _work("W2", "10.1000/book", "A Book", 2019, 3)
    book["type"] = "book"
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2", "W3", "W4"]),
        "W2": book,
        "W3": _work("W3", "10.1000/same", "Same Title", 2018, 2),
        "W4": _work("W4", "10.1000/fail", "Fail", 2019, 1),
    }
    cfg = _cfg(tmp_path, more='dedupe_scope = "collection"\ntag_prefix = "sb"\n')
    held = Item(
        key="HAVE",
        item_type="journalArticle",
        title="Same Title",
        doi=None,
        arxiv_id=None,
        url=None,
        year=2018,
        first_author="Lovelace",
        collection_paths=["Inbox/Snowball"],
    )

    class Catalog(_Lib):
        def items_in_scope(self, keys):
            return [held]

        def create_parent(self, data):
            if data.get("DOI") == "10.1000/fail":
                raise LibraryError("write failed")
            return super().create_parent(data)

    lib = Catalog()
    result = run_doi(
        cfg,
        ["https://doi.org/10.1000/seed", "not-a-doi"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", dedupe_scope="collection"),
        console=Console(highlight=False, width=160),
        client=_client(works),
        backend=lib,
    )
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    by = {row["ids"]["doi"]: row for row in rows}
    assert by["not-a-doi"]["status"] == "error"
    assert by["10.1000/book"]["status"] == "filtered"
    assert by["10.1000/same"]["status"] == "exists"
    assert by["10.1000/same"]["exists_match"]["title_year"].startswith("same title|")
    assert result.exit_code == 1
    summary = json.loads((result.run_dir / "summary.json").read_text())
    assert summary["score"] == "overlap * 1000 + cited_by_count"
    assert summary["filtered"] >= 1
    assert summary["dedupe_scope"] == "collection"


def test_profile_save_refuses_secrets(tmp_path: Path):
    from paperful.snowball.profile import save_profile

    cfg = _cfg(tmp_path)
    with pytest.raises(SnowballError, match="key"):
        save_profile(cfg, "scout", {"mode": "search", "query": "bbnj", "api_key": "secret"}, force=False)
    with pytest.raises(SnowballError, match="force"):
        save_profile(
            cfg,
            "lib",
            {"mode": "search", "query": "bbnj", "gate": "auto", "target_collection": "Inbox"},
            force=False,
        )
    path = save_profile(cfg, "scout", {"mode": "search", "query": "bbnj", "description": "Scout"}, force=False)
    assert "api_key" not in path.read_text()
    assert 'kind = "snowball"' in path.read_text()


def test_cli_profile_save_and_per_hop(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nstate_dir = "{tmp_path / "state"}"\n[snowball]\nenabled = true\n'
    )
    saved = runner.invoke(
        cli.app,
        ["snowball", "profile", "save", "keyword-scout", "--query", "bbnj", "--description", "Scout", "-c", str(cfg_path)],
    )
    assert saved.exit_code == 0
    text = (tmp_path / "profiles" / "keyword-scout.toml").read_text()
    assert "bbnj" in text
    refused = runner.invoke(
        cli.app,
        ["snowball", "profile", "save", "lib", "--query", "bbnj", "--gate", "auto", "-c", str(cfg_path)],
    )
    assert refused.exit_code == 2


def test_language_filter_and_min_seed_citations(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 2, refs=["W2"]),
        "W2": _work("W2", "10.1000/ref", "Ref", 2021, 1),
        "C1": _work("C1", "10.1000/cite", "Cite", 2022, 9),
    }
    works["W2"]["language"] = "fr"
    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(direction="both", languages=("en",), min_seed_citations=5),
        console=Console(highlight=False, width=160),
        client=_client(works, citing={"W1": ["C1"]}),
        lookup=lambda doi, title: None,
    )
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    by = {row["ids"]["doi"]: row for row in rows}
    assert by["10.1000/ref"]["status"] == "filtered"
    assert "language" in by["10.1000/ref"]["why"]
    assert "10.1000/cite" not in by


class _CreateLib:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.notes: list[str] = []

    def ensure_collection_path(self, path: str) -> str:
        return "COL"

    def create_parent(self, payload: dict) -> str:
        self.created.append(str(payload.get("DOI") or ""))
        return "ITEM"

    def create_or_update_note(self, key: str, note: str, tag: str) -> None:
        self.notes.append(note)

    def items_in_scope(self, keys):
        return []


def test_note_provenance_off(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 3, refs=["W2"]),
        "W2": _work("W2", "10.1000/new", "New", 2021, 1),
    }
    lib = _CreateLib()
    run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", note_provenance=False),
        console=Console(highlight=False, width=160),
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert lib.created == ["10.1000/new"]
    assert lib.notes == []


def test_hybrid_and_overlap(tmp_path: Path):
    works = {
        "A": _work("A", "10.1000/a", "Alpha", 2020, 10, refs=["R"]),
        "B": _work("B", "10.1000/b", "Beta", 2020, 9, refs=["R"]),
        "R": _work("R", "10.1000/shared", "Shared", 2019, 4),
    }

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if work["doi"].endswith(doi):
                    return work
            return {}
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[i] for i in ids if i in works]}
        if "search" in params:
            return {"results": [works["A"], works["B"]]}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    result = run_hybrid(
        _cfg(tmp_path),
        "abmt",
        SnowballRequest(hybrid_seeds=2, direction="refs", max_candidates=20),
        console=Console(highlight=False, width=160),
        client=client,
        lookup=lambda doi, title: None,
    )
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    shared = next(row for row in rows if row["ids"]["doi"] == "10.1000/shared")
    assert shared["hop"] == 1
    assert shared["biblio"]["overlap"] == 2
    assert shared["score"] == 2004


def test_crossref_fills_empty_and_s2_does_not_overwrite(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, refs=["W2"]),
        "W2": _work("W2", "10.1000/new", "", 2021, 0),
    }
    works["W2"]["display_name"] = ""
    works["W2"]["publication_year"] = None
    works["W2"]["primary_location"] = {}
    works["W2"]["authorships"] = []
    called = {"s2": 0}

    def crossref(doi: str) -> dict:
        return {"title": "Filled", "year": 2018, "venue": "Nature", "authors": ["Ada Lovelace"]}

    def s2(doi: str) -> dict:
        called["s2"] += 1
        return {}

    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(),
        console=Console(highlight=False, width=160),
        client=_client(works),
        lookup=lambda doi, title: None,
        crossref_getter=crossref,
        s2_getter=s2,
    )
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    filled = next(row for row in rows if row["ids"]["doi"] == "10.1000/new")
    assert filled["biblio"]["title"] == "Filled"
    assert filled["biblio"]["venue"] == "Nature"
    assert called["s2"] == 1


def test_approve_each_yes_no_and_cap(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, refs=["A", "B"]),
        "A": _work("A", "10.1000/a", "Alpha", 2020, 1),
        "B": _work("B", "10.1000/b", "Beta", 2020, 1),
    }
    lib = _CreateLib()
    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(gate="approve-each", collection="Inbox/Snowball", approve_each_max=5),
        console=Console(highlight=False, width=160),
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
        decider=lambda row: row.ids.get("doi") == "10.1000/a",
    )
    assert result.exit_code == 0
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    kept = {row["ids"]["doi"]: row.get("keep") for row in rows}
    assert kept["10.1000/a"] is True
    assert kept["10.1000/b"] is False
    assert lib.created == ["10.1000/a"]
    with pytest.raises(SnowballError, match="approve-batch"):
        run_doi(
            _cfg(tmp_path),
            ["10.1000/seed"],
            SnowballRequest(gate="approve-each", collection="Inbox/Snowball", approve_each_max=0),
            console=Console(highlight=False, width=160),
            client=_client(works),
            lookup=lambda doi, title: None,
            backend=lib,
            decider=lambda row: True,
        )


def test_refine_suggestions_do_not_create(tmp_path: Path):
    works = {"A": _work("A", "10.1000/a", "Alpha", 2020, 3)}
    result = run_search(
        _cfg(tmp_path),
        "bbnj",
        SnowballRequest(refine=True),
        console=Console(highlight=False, width=160),
        client=_client(works),
        lookup=lambda doi, title: None,
        suggester=lambda query: ["bbnj EIA", query],
    )
    summary = json.loads((result.run_dir / "summary.json").read_text())
    assert summary["suggestions"] == ["bbnj EIA", "bbnj"]
    assert result.exit_code == 0
    assert not (result.run_dir / "write_report.json").exists()


def test_deep_gates_backends_and_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from paperful.snowball.expand import normalize_direction
    from paperful.snowball.fill import s2_paper

    works = {
        "W1": _work("W1", "10.1000/seed", "Seed title stays", 2020, 1, refs=["W2"]),
        "W2": _work("W2", "10.1000/new", "Kept title", 2021, 2),
        "C1": _work("C1", "10.1000/cite", "Cite", 2022, 3),
    }
    works["W2"]["language"] = ""
    console = Console(highlight=False, width=160)
    cfg = _cfg(tmp_path)

    def boom(path: str, params: dict) -> dict:
        raise AssertionError("crawl should not start")

    with pytest.raises(SnowballError, match="target collection"):
        run_doi(
            cfg,
            ["10.1000/seed"],
            SnowballRequest(gate="approve-batch"),
            console=console,
            client=OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=boom),
        )
    with pytest.raises(SnowballError, match="Unknown"):
        run_doi(cfg, ["10.1000/seed"], SnowballRequest(backends=("nope",)), console=console, client=_client(works))
    with pytest.raises(SnowballError, match="openalex"):
        run_doi(cfg, ["10.1000/seed"], SnowballRequest(backends=("crossref",)), console=console, client=_client(works))

    class Stdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("paperful.snowball.command.sys.stdin", Stdin())
    with pytest.raises(SnowballError, match="terminal"):
        run_doi(
            cfg,
            ["10.1000/seed"],
            SnowballRequest(gate="approve-each", collection="Inbox/Snowball"),
            console=console,
            client=_client(works),
            lookup=lambda doi, title: None,
        )

    kept_lang = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(languages=("en",), direction="both", min_seed_citations=0),
        console=console,
        client=_client(works, citing={"W1": ["C1"]}),
        lookup=lambda doi, title: None,
    )
    rows = [json.loads(line) for line in (kept_lang.run_dir / "candidates.jsonl").read_text().splitlines()]
    by = {row["ids"]["doi"]: row for row in rows}
    assert by["10.1000/new"]["status"] == "new"
    assert by["10.1000/cite"]["direction"] == "cites"

    def crossref(doi: str) -> dict:
        return {"title": "Overwrite", "year": 1999, "venue": "Other", "authors": ["Other"]}

    filled = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="references"),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        crossref_getter=crossref,
    )
    rows = [json.loads(line) for line in (filled.run_dir / "candidates.jsonl").read_text().splitlines()]
    titles = {row["ids"]["doi"]: row["biblio"]["title"] for row in rows}
    assert titles["10.1000/new"] == "Kept title"

    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    def s2(doi: str) -> dict:
        if doi != "10.1000/new":
            return {}
        return {
            "title": "Should not replace",
            "references": [{"title": "Extra", "year": 2017, "externalIds": {"DOI": "10.1000/s2"}}],
        }

    s2_run = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="both"),
        console=console,
        client=_client(works, citing={"W1": ["C1"]}),
        lookup=lambda doi, title: None,
        s2_getter=s2,
    )
    s2_rows = [json.loads(line) for line in (s2_run.run_dir / "candidates.jsonl").read_text().splitlines()]
    extra = next(row for row in s2_rows if row["ids"]["doi"] == "10.1000/s2")
    assert extra["provenance"]["backend"] == "semanticscholar"
    assert extra["why"].startswith("s2 ref")
    assert normalize_direction("all") == "both"

    cache = tmp_path / "cache"
    (cache).mkdir()
    (cache / "10.1000_cached.json").write_text('{"title": "Cached"}', encoding="utf-8")
    assert s2_paper("10.1000/cached", cache_dir=cache, api_key="test-key")["title"] == "Cached"

    lib = _CreateLib()
    noted = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", note_provenance=True),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert noted.exit_code == 0
    assert lib.created
    assert "seed:" in lib.notes[0]
    assert "api_key" not in lib.notes[0]
    assert "@" not in lib.notes[0]


def test_deep_refine_hybrid_orcid_and_cli(tmp_path: Path):
    works = {"A": _work("A", "10.1000/a", "Alpha", 2020, 4, refs=["R"]), "R": _work("R", "10.1000/r", "Ref", 2019, 1)}
    console = Console(highlight=False, width=160)
    cfg = _cfg(tmp_path)
    disabled = run_search(
        cfg,
        "bbnj",
        SnowballRequest(refine=True),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    summary = json.loads((disabled.run_dir / "summary.json").read_text())
    assert summary["suggestions_error"] == "llm disabled"
    assert "suggestions" not in summary

    failed = run_search(
        cfg,
        "bbnj",
        SnowballRequest(refine=True),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        suggester=lambda query: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    err = json.loads((failed.run_dir / "summary.json").read_text())["suggestions_error"]
    assert "boom" in err

    with pytest.raises(SnowballError, match="keyword"):
        run_hybrid(cfg, "  ", SnowballRequest(), console=console, client=_client(works))

    nodoi = {"A": _work("A", "10.1000/a", "Alpha", 2020, 4)}
    nodoi["A"]["doi"] = ""
    bare = run_hybrid(
        cfg,
        "abmt",
        SnowballRequest(hybrid_seeds=3),
        console=console,
        client=_client(nodoi),
        lookup=lambda doi, title: None,
    )
    bare_rows = [json.loads(line) for line in (bare.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert bare_rows
    assert all(row["hop"] == 0 for row in bare_rows)

    def orcid_boom(_orcid: str) -> list[str]:
        raise AssertionError("orcid api")

    skipped = run_orcid(
        cfg,
        "0000-0002-9162-9618",
        SnowballRequest(backends=("openalex", "crossref")),
        console=console,
        client=_client({}),
        lookup=lambda doi, title: None,
        orcid_getter=orcid_boom,
    )
    assert skipped.exit_code == 0

    cfg_path = tmp_path / "config.toml"
    saved = runner.invoke(
        cli.app,
        ["snowball", "profile", "save", "hy", "--query", "bbnj", "--hybrid", "--hybrid-seeds", "3", "-c", str(cfg_path)],
    )
    assert saved.exit_code == 0
    text = (tmp_path / "profiles" / "hy.toml").read_text()
    assert 'mode = "hybrid"' in text
    assert "hybrid_seeds = 3" in text
    refused = runner.invoke(
        cli.app,
        ["snowball", "hybrid", "bbnj", "--gate", "auto", "-c", str(cfg_path)],
    )
    assert refused.exit_code == 2
    assert "target collection" in refused.output


def test_parse_fetch_pdfs_modes():
    from paperful.config import parse_fetch_pdfs

    assert parse_fetch_pdfs(False) == "off"
    assert parse_fetch_pdfs(True) == "fast"
    assert parse_fetch_pdfs("full") == "full"
    with pytest.raises(ValueError):
        parse_fetch_pdfs("sometimes")


def test_fill_pdfs_full_retries_only_misses(tmp_path: Path, monkeypatch):
    from paperful.snowball.ingest import fill_pdfs
    from paperful.store import STATUS_OK, Manifest, Record

    cfg = Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        sources=["unpaywall", "scihub"],
    )
    cfg.state_dir.mkdir()
    seen: list[tuple[bool, list[str]]] = []

    class Pipe:
        def __init__(self, cfg, manifest, console, sources=None, attacher=None, use_browser=True, progress=None):
            self.use_browser = use_browser
            self._keys: list[str] = []
            self.stats = type("S", (), {"ok": 0, "attached": 0, "attach_failed": 0})()

        def run(self, items):
            keys = [it.key for it in items]
            seen.append((self.use_browser, keys))
            if not self.use_browser:
                Manifest(cfg.manifest_path).write(Record(itemKey="A", status=STATUS_OK))
                self.stats.ok = 1
            else:
                self.stats.ok = 1
            return self.stats

    monkeypatch.setattr("paperful.snowball.ingest.Pipeline", Pipe)
    monkeypatch.setattr(
        "paperful.snowball.ingest.with_recover_lane",
        lambda cfg, sources: [*sources, "browser_agent"],
    )
    items = [
        Item("A", "journalArticle", "Hit", "10.1/a", None, None, 2020, "A"),
        Item("B", "journalArticle", "Miss", "10.1/b", None, None, 2024, "B"),
    ]
    stats = fill_pdfs(cfg, object(), items, Console(highlight=False, width=120), mode="full")
    assert seen == [(False, ["A", "B"]), (True, ["B"])]
    assert stats.ok == 2


def test_auto_full_mode_reaches_fill(tmp_path: Path, monkeypatch):
    works = {"W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, ["W2"]), "W2": _work("W2", "10.1000/new", "New", 2019, 1)}
    modes: list[str] = []

    def fake_fill(cfg, backend, items, console, **kwargs):
        modes.append(kwargs.get("mode"))

        class Stats:
            ok = 1
            attached = 0
            attach_failed = 0

        return Stats()

    monkeypatch.setattr("paperful.snowball.command.fill_pdfs", fake_fill)
    run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", fetch_pdfs="full"),
        console=Console(highlight=False, width=200),
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=_Lib(),
    )
    assert modes == ["full"]


def test_api_error_keeps_a_restorable_queue(tmp_path: Path):
    from paperful.snowball.openalex import OpenAlexError

    works = {"W1": _work("W1", "10.1000/seed", "Seed", 2020, 5)}

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            return works["W1"]
        if "cites:" in str(params.get("filter") or ""):
            raise OpenAlexError("openalex down")
        return {"results": []}

    console = Console(file=StringIO(), highlight=False, width=120)
    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(gate="dry-run", direction="cites", depth=1),
        console=console,
        client=OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter),
    )
    assert result.exit_code == 1
    assert (result.run_dir / "candidates.jsonl").is_file()
    deferred = json.loads((result.run_dir / "deferred.json").read_text())
    assert deferred["kind"] == "cites"
    assert deferred["remaining_ids"] == ["W1"]
    assert "Crawl paused" in console.file.getvalue()


def test_keyless_promotes_to_one_key():
    bare = OpenAlexClient(email="a@b.c", api_key="", sleep_s=0)
    assert bare._promote_key() is False
    assert "Authorization" not in bare._headers()
    keyed = OpenAlexClient(email="a@b.c", api_key="k", sleep_s=0)
    assert "Authorization" not in keyed._headers()
    assert keyed._promote_key() is True
    assert keyed._headers()["Authorization"] == "Bearer k"
    assert keyed._promote_key() is False
    notice = keyless_limit_message(has_key=False, reset_at="2099-01-01T00:00:00+00:00")
    assert "https://openalex.org/settings/api" in notice
    assert "VPN" in notice
    assert "more reliable" in notice


def test_openalex_rejected_key_is_not_a_budget_stop():
    import httpx

    from paperful.snowball.openalex import OpenAlexError

    client = OpenAlexClient(email="a@b.c", api_key="k", sleep_s=0, max_retries=0)
    client._using_key = True

    class Fake:
        def get(self, url, params=None, headers=None):
            return httpx.Response(401, request=httpx.Request("GET", url))

    client._http_client = Fake()  # type: ignore[assignment]
    with pytest.raises(OpenAlexError, match="API key was rejected"):
        client.get("/works", {})


def test_budget_stop_keeps_partial_rows_and_resume(tmp_path: Path):
    import httpx

    spent = httpx.Response(429, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "40000"})
    burst = httpx.Response(429, headers={"Retry-After": "1", "X-RateLimit-Remaining": "10"})
    assert _is_budget(spent, 0.0)
    assert not _is_budget(burst, 0.0)

    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 5),
        "W2": _work("W2", "10.1000/cite", "Citer", 2021, 1),
    }
    calls = {"cites": 0}

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            return works["W1"]
        filt = str(params.get("filter") or "")
        if "cites:" in filt:
            calls["cites"] += 1
            if calls["cites"] == 1:
                raise OpenAlexBudgetExceeded("spent", reset_at="2099-01-01T00:00:00+00:00", reset_in_s=999)
            return {"results": [works["W2"]]}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="k", sleep_s=0, getter=getter)
    client._using_key = True
    console = Console(file=StringIO(), highlight=False, width=120)
    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(gate="dry-run", direction="cites", depth=1, per_hop_limit=10),
        console=console,
        client=client,
    )
    assert result.exit_code == 1
    deferred_path = result.run_dir / "deferred.json"
    deferred = json.loads(deferred_path.read_text())
    assert deferred["kind"] == "cites"
    assert deferred["remaining_ids"] == ["W1"]
    assert "paperful snowball resume" in console.file.getvalue()

    early = Console(file=StringIO(), highlight=False, width=120)
    held = run_resume(
        _cfg(tmp_path),
        result.run_dir.name,
        SnowballRequest(gate="dry-run"),
        console=early,
        client=OpenAlexClient(email="t@example.org", api_key="k", sleep_s=0, getter=getter),
    )
    assert held.exit_code == 1
    assert "still spent" in early.file.getvalue()
    assert calls["cites"] == 1

    deferred["reset_at"] = "2000-01-01T00:00:00+00:00"
    deferred_path.write_text(json.dumps(deferred))
    resumed = run_resume(
        _cfg(tmp_path),
        result.run_dir.name,
        SnowballRequest(gate="dry-run"),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=OpenAlexClient(email="t@example.org", api_key="k", sleep_s=0, getter=getter),
    )
    assert resumed.exit_code == 0
    assert not deferred_path.exists()
    saved = (resumed.run_dir / "candidates.jsonl").read_text()
    assert "10.1000/cite" in saved


def _keyword(slug: str, score: float) -> dict:
    return {
        "id": f"https://openalex.org/keywords/{slug}",
        "display_name": slug,
        "score": score,
    }


def _keyword_client(works: dict[str, dict]) -> tuple[OpenAlexClient, dict]:
    seen: dict[str, str] = {}

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if str(work.get("doi") or "").endswith(doi):
                    return work
            return {}
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[item] for item in ids if item in works]}
        if filt.startswith("keywords.id:"):
            seen["filter"] = filt.split(",", 1)[0]
            slugs = set(seen["filter"].split(":", 1)[1].split("|"))
            hits = []
            for work in works.values():
                owned = {
                    str(item.get("id") or "").rsplit("/", 1)[-1]
                    for item in (work.get("keywords") or [])
                    if isinstance(item, dict)
                }
                if owned & slugs and not str(work.get("doi") or "").endswith("10.1000/seed"):
                    hits.append(work)
            hits.sort(key=lambda work: -int(work.get("cited_by_count") or 0))
            return {"results": hits}
        return {"results": []}

    return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter), seen


def test_keyword_hop_uses_top_slugs_and_finite_cap(tmp_path: Path):
    from paperful.snowball.expand import normalize_direction, parse_keyword_hop_limit, parse_keyword_limit

    assert normalize_direction("refs+keywords") == "refs+keywords"
    assert normalize_direction("all") == "both"
    with pytest.raises(ValueError, match="keyword_limit"):
        parse_keyword_limit("all")
    with pytest.raises(ValueError, match="keyword_hop_limit"):
        parse_keyword_hop_limit(0)
    with pytest.raises(ValueError, match="keyword_hop_limit"):
        parse_keyword_hop_limit("all")

    seed = _work("W1", "10.1000/seed", "Seed", 2020, 4)
    seed["keywords"] = [
        _keyword("alpha", 0.9),
        _keyword("beta", 0.8),
        _keyword("gamma", 0.7),
        _keyword("delta", 0.2),
    ]
    wide = _work("H1", "10.1000/wide", "Wide", 2021, 1)
    wide["keywords"] = [_keyword("alpha", 0.5), _keyword("beta", 0.5), _keyword("gamma", 0.5)]
    narrow = _work("H2", "10.1000/narrow", "Narrow", 2021, 50)
    narrow["keywords"] = [_keyword("alpha", 0.4)]
    extra = _work("H3", "10.1000/extra", "Extra", 2021, 9)
    extra["keywords"] = [_keyword("alpha", 0.4), _keyword("beta", 0.4)]
    works = {"W1": seed, "H1": wide, "H2": narrow, "H3": extra}
    cfg = _cfg(tmp_path)
    buf = StringIO()
    console = Console(file=buf, highlight=False, width=200, force_terminal=False)
    client, seen = _keyword_client(works)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="keywords", depth=1, keyword_limit=3, keyword_hop_limit=2),
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 0
    assert seen["filter"] == "keywords.id:alpha|beta|gamma"
    lines = (result.run_dir / "candidates.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines if json.loads(line)["direction"] == "keywords"]
    assert len(rows) == 2
    by_doi = {row["ids"]["doi"]: row for row in rows}
    assert set(by_doi) == {"10.1000/narrow", "10.1000/extra"}
    assert by_doi["10.1000/extra"]["biblio"]["overlap"] == 2
    assert by_doi["10.1000/narrow"]["biblio"]["overlap"] == 1
    assert by_doi["10.1000/extra"]["score"] > by_doi["10.1000/narrow"]["score"]
    assert "keywords alpha, beta of 10.1000/seed" in by_doi["10.1000/extra"]["why"]


def test_keywords_only_empty_seeds_exit(tmp_path: Path):
    seed = _work("W1", "10.1000/seed", "Seed", 2020, 4)
    seed["keywords"] = []
    cfg = _cfg(tmp_path)
    client, seen = _keyword_client({"W1": seed})
    with pytest.raises(SnowballError, match="1 of 1 seeds have no OpenAlex keywords") as exc:
        run_doi(
            cfg,
            ["10.1000/seed"],
            SnowballRequest(direction="keywords", depth=1),
            console=Console(file=StringIO(), highlight=False, width=120),
            client=client,
            lookup=lambda doi, title: None,
        )
    assert exc.value.code == 2
    assert "filter" not in seen


def test_mixed_direction_keeps_refs_when_keywords_missing(tmp_path: Path):
    seed = _work("W1", "10.1000/seed", "Seed", 2020, 4, ["W2"])
    seed["keywords"] = []
    child = _work("W2", "10.1000/ref", "Ref", 2019, 2)
    cfg = _cfg(tmp_path)
    buf = StringIO()
    client, _seen = _keyword_client({"W1": seed, "W2": child})
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="refs+keywords", depth=1, per_hop_limit="all"),
        console=Console(file=buf, highlight=False, width=200, force_terminal=False),
        client=client,
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 0
    text = buf.getvalue()
    assert "1 of 1 seeds have no OpenAlex keywords" in text
    lines = (result.run_dir / "candidates.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert {row["direction"] for row in rows} == {"refs"}
    assert rows[0]["ids"]["doi"] == "10.1000/ref"


def test_keyword_notice_counts_the_whole_doi_list(tmp_path: Path):
    bare = _work("W1", "10.1000/bare", "Bare", 2020, 2, ["W3"])
    bare["keywords"] = []
    tagged = _work("W2", "10.1000/tagged", "Tagged", 2020, 3)
    tagged["keywords"] = [_keyword("alpha", 0.9)]
    neighbour = _work("H1", "10.1000/hit", "Hit", 2021, 4)
    neighbour["keywords"] = [_keyword("alpha", 0.5)]
    ref = _work("W3", "10.1000/ref", "Ref", 2019, 1)
    works = {"W1": bare, "W2": tagged, "H1": neighbour, "W3": ref}
    cfg = _cfg(tmp_path)
    buf = StringIO()
    client, seen = _keyword_client(works)
    result = run_doi(
        cfg,
        ["10.1000/bare", "10.1000/tagged"],
        SnowballRequest(direction="keywords", depth=1, keyword_limit=3, keyword_hop_limit=5),
        console=Console(file=buf, highlight=False, width=200, force_terminal=False),
        client=client,
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 0
    text = buf.getvalue()
    assert text.count("1 of 2 seeds have no OpenAlex keywords") == 1
    assert seen["filter"] == "keywords.id:alpha"
    lines = (result.run_dir / "candidates.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert {row["ids"]["doi"] for row in rows} == {"10.1000/hit"}


def test_keyword_min_score_drops_weak_slugs(tmp_path: Path):
    seed = _work("W1", "10.1000/seed", "Seed", 2020, 4)
    seed["keywords"] = [_keyword("alpha", 0.9), _keyword("beta", 0.2)]
    hit = _work("H1", "10.1000/hit", "Hit", 2021, 3)
    hit["keywords"] = [_keyword("alpha", 0.5)]
    cfg = _cfg(tmp_path)
    client, seen = _keyword_client({"W1": seed, "H1": hit})
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="keywords", depth=1, keyword_min_score=0.5),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 0
    assert seen["filter"] == "keywords.id:alpha"


def test_works_by_keywords_refuses_unbounded_limit():
    from paperful.snowball.openalex import OpenAlexError

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=lambda path, params: {})
    with pytest.raises(OpenAlexError, match="keyword_hop_limit"):
        client.works_by_keywords(["alpha"], limit=0)


def test_empty_refs_recover_from_semanticscholar(tmp_path: Path):
    seed = _work("W1", "10.1000/seed", "Seed empty refs", 2024, 0, refs=[])
    neighbour = _work("W2", "10.1000/s2-ref", "S2 neighbour", 2020, 5)
    works = {"W1": seed, "W2": neighbour}
    pdf_calls: list[str] = []

    def s2(doi: str) -> dict:
        if doi != "10.1000/seed":
            return {}
        return {
            "title": "Seed empty refs",
            "references": [
                {"title": "S2 neighbour", "year": 2020, "externalIds": {"DOI": "10.1000/s2-ref"}},
            ],
        }

    client = _client(works)
    client.pdf_fetcher = lambda url: pdf_calls.append(url) or ""
    cfg = _cfg(tmp_path)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="refs", depth=1),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
        lookup=lambda doi, title: None,
        s2_getter=s2,
    )
    assert result.exit_code == 0
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    by_doi = {row["ids"]["doi"]: row for row in rows}
    assert "10.1000/s2-ref" in by_doi
    assert by_doi["10.1000/s2-ref"]["provenance"]["backend"] == "semanticscholar"
    assert by_doi["10.1000/s2-ref"]["why"].startswith("s2 ref")
    assert pdf_calls == []


def test_empty_refs_recover_from_open_pdf(tmp_path: Path):
    seed = _work("W1", "10.1000/seed", "Seed empty refs", 2024, 0, refs=[])
    seed["open_access"] = {
        "is_oa": True,
        "oa_status": "bronze",
        "oa_url": "https://example.test/seed.pdf",
    }
    doi_hit = _work("W2", "10.1000/doi-ref", "DOI bibliography hit", 2019, 4)
    title_hit = _work("W3", "10.1000/title-ref", "Exact title match paper", 2021, 3)
    miss = _work("W4", "10.1000/other", "Completely different topic", 2018, 2)
    works = {"W1": seed, "W2": doi_hit, "W3": title_hit, "W4": miss}

    pdf_text = """
Body text.

References
[1] Ada Lovelace. (2019). DOI bibliography hit. Marine Policy.
https://doi.org/10.1000/doi-ref
[2] Someone. (2021). Exact title match paper. Marine Policy.
[3] Other. (2018). Unrelated phantom title never in OpenAlex. Fantasy Journal.
"""

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if work["doi"].endswith(doi):
                    return work
            return {}
        if "search" in params:
            query = str(params.get("search") or "").lower()
            hits = []
            if "exact title match paper" in query:
                hits.append(title_hit)
            elif "unrelated phantom" in query:
                hits.append(miss)
            return {"results": hits, "meta": {"count": len(hits)}}
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[i] for i in ids if i in works]}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    client.pdf_fetcher = lambda url: pdf_text if url.endswith(".pdf") else ""
    cfg = _cfg(tmp_path)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="refs", depth=1),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
        lookup=lambda doi, title: None,
        s2_getter=lambda doi: {},
    )
    assert result.exit_code == 0
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    by_doi = {row["ids"]["doi"]: row for row in rows}
    assert "10.1000/doi-ref" in by_doi
    assert "10.1000/title-ref" in by_doi
    assert "10.1000/other" not in by_doi
    assert by_doi["10.1000/doi-ref"]["provenance"]["backend"] == "pdf"
    assert by_doi["10.1000/doi-ref"]["why"].startswith("pdf ref")
    assert by_doi["10.1000/title-ref"]["provenance"]["backend"] == "pdf"


def test_nonempty_openalex_refs_skip_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seed = _work("W1", "10.1000/seed", "Seed with refs", 2020, 1, refs=["W2"])
    neighbour = _work("W2", "10.1000/oa-ref", "OpenAlex neighbour", 2019, 2)
    works = {"W1": seed, "W2": neighbour}
    pdf_calls: list[str] = []
    recover_calls: list[str] = []

    client = _client(works)
    client.pdf_fetcher = lambda url: pdf_calls.append(url) or ""

    import paperful.snowball.crawl as crawl_mod

    import paperful.snowball.bibliography as bib

    def wrapped(client_arg, work, **kwargs):
        recover_calls.append(str(work.get("id") or ""))
        return bib.recover_referenced_works(client_arg, work, **kwargs)

    monkeypatch.setattr(crawl_mod, "recover_referenced_works", wrapped)
    cfg = _cfg(tmp_path)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(direction="refs", depth=1),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
        lookup=lambda doi, title: None,
    )
    assert result.exit_code == 0
    rows = [json.loads(line) for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()]
    dois = {row["ids"]["doi"] for row in rows}
    assert "10.1000/oa-ref" in dois
    assert recover_calls == []
    assert pdf_calls == []


def test_watch_baseline_then_propose(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import inbox_count, load_seen, run_watch, save_watch

    cfg = _cfg(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    save_profile(
        cfg,
        "keyword-scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    save_watch(cfg, "bbnj", "keyword-scout")
    works = {
        "W1": _work("W1", "10.1000/a", "Alpha", 2020, 1),
        "W2": _work("W2", "10.1000/b", "Beta", 2021, 2),
    }
    lib = _Lib()
    console = Console(file=StringIO(), highlight=False, width=120)
    first = run_watch(
        cfg,
        "bbnj",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert first.baseline is True
    assert first.proposed == 0
    assert first.baseline_count == 2
    assert lib.created == []
    assert inbox_count(cfg, "bbnj") == 0
    assert (first.run_dir / "candidates.jsonl").read_text().strip() == ""
    assert load_seen(cfg, "bbnj") == {"doi:10.1000/a", "doi:10.1000/b"}

    works["W3"] = _work("W3", "10.1000/c", "Gamma", 2022, 3)
    second = run_watch(
        cfg,
        "bbnj",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert second.baseline is False
    assert second.proposed == 1
    assert second.already_seen == 2
    assert lib.created == []
    assert inbox_count(cfg, "bbnj") == 1
    rows = [json.loads(line) for line in (second.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["ids"]["doi"] == "10.1000/c"
    assert rows[0]["keep"] is True
    assert rows[0]["status"] == "new"

    third = run_watch(
        cfg,
        "bbnj",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert third.proposed == 0
    assert third.already_seen == 3
    assert inbox_count(cfg, "bbnj") == 1
    assert lib.created == []


def test_watch_auto_profile_never_creates(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import run_watch, save_watch

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "auto-scout",
        {
            "mode": "search",
            "query": "bbnj",
            "gate": "auto",
            "target_collection": "Inbox/Snowball",
            "fetch_pdfs": "fast",
        },
        force=True,
    )
    save_watch(cfg, "auto", "auto-scout")
    works = {"W1": _work("W1", "10.1000/a", "Alpha", 2020, 1)}
    lib = _Lib()
    console = Console(file=StringIO(), highlight=False, width=120)
    run_watch(
        cfg,
        "auto",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    works["W2"] = _work("W2", "10.1000/b", "Beta", 2021, 1)
    result = run_watch(
        cfg,
        "auto",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert result.proposed == 1
    assert lib.created == []
    assert not (result.run_dir / "write_report.json").is_file()


def test_watch_passes_from_created_date_after_baseline(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import run_watch, save_watch

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    save_watch(cfg, "w", "scout")
    works = {"W1": _work("W1", "10.1000/a", "Alpha", 2020, 1)}
    filters: list[str] = []

    def getter(path: str, params: dict) -> dict:
        filt = str(params.get("filter") or "")
        if "search" in params or filt:
            filters.append(filt)
        if "search" in params:
            return {"results": list(works.values())}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    console = Console(file=StringIO(), highlight=False, width=120)
    run_watch(cfg, "w", console=console, client=client, lookup=lambda doi, title: None)
    assert all("from_created_date:" not in f for f in filters)
    filters.clear()
    works["W2"] = _work("W2", "10.1000/b", "Beta", 2021, 1)
    run_watch(cfg, "w", console=console, client=client, lookup=lambda doi, title: None)
    assert any("from_created_date:" in f for f in filters)


def test_cli_watch_save_show(tmp_path: Path):
    cfg = _cfg(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "scout.toml").write_text(
        'kind = "snowball"\nmode = "search"\nquery = "bbnj"\ngate = "dry-run"\n'
    )
    result = runner.invoke(
        cli.app,
        ["snowball", "watch", "save", "bbnj", "--profile", "scout", "--config", str(cfg.config_path)],
    )
    assert result.exit_code == 0, result.output
    show = runner.invoke(
        cli.app,
        ["snowball", "watch", "show", "bbnj", "--config", str(cfg.config_path)],
    )
    assert show.exit_code == 0, show.output
    assert "baseline · not yet" in show.output
    assert "inbox · 0" in show.output


def test_watch_hybrid_stays_on_keyword_hits(tmp_path: Path):
    """Hybrid profiles watch depth 0 only; refs of hits are not proposed."""
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import load_seen, run_watch, save_watch

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "hybrid-scout",
        {
            "mode": "hybrid",
            "query": "bbnj",
            "gate": "dry-run",
            "direction": "refs",
            "hybrid_seeds": 5,
            "depth": 2,
        },
        force=False,
    )
    save_watch(cfg, "hy", "hybrid-scout")
    hit = _work("W1", "10.1000/hit", "Hit", 2020, 5, ["W2"])
    ref = _work("W2", "10.1000/ref", "Ref only", 2019, 1)
    new_hit = _work("W3", "10.1000/newhit", "New hit", 2022, 2, ["W2"])
    works = {"W1": hit, "W2": ref}
    search_ids = {"W1"}

    def getter(path: str, params: dict) -> dict:
        if path.startswith("/works/https://doi.org/"):
            doi = path.split("/works/https://doi.org/", 1)[1]
            for work in works.values():
                if work["doi"].endswith(doi):
                    return work
            return {}
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [works[i] for i in ids if i in works]}
        if "search" in params:
            return {"results": [works[i] for i in search_ids if i in works]}
        return {"results": []}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    console = Console(file=StringIO(), highlight=False, width=120)
    first = run_watch(
        cfg,
        "hy",
        console=console,
        client=client,
        lookup=lambda doi, title: None,
        backend=_Lib(),
    )
    assert first.baseline is True
    assert load_seen(cfg, "hy") == {"doi:10.1000/hit"}
    works["W3"] = new_hit
    search_ids.add("W3")
    second = run_watch(
        cfg,
        "hy",
        console=console,
        client=OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter),
        lookup=lambda doi, title: None,
        backend=_Lib(),
    )
    assert second.proposed == 1
    rows = [json.loads(line) for line in (second.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert {row["ids"]["doi"] for row in rows} == {"10.1000/newhit"}
    assert "10.1000/ref" not in load_seen(cfg, "hy")


def test_watch_exists_marked_seen_not_proposed(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import inbox_count, load_seen, run_watch, save_watch

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    save_watch(cfg, "ex", "scout")
    works = {"W1": _work("W1", "10.1000/a", "Alpha", 2020, 1)}
    console = Console(file=StringIO(), highlight=False, width=120)
    run_watch(
        cfg,
        "ex",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=_Lib(),
    )
    works["W2"] = _work("W2", "10.1000/inlib", "Already here", 2021, 1)
    works["W3"] = _work("W3", "10.1000/fresh", "Fresh", 2022, 1)

    def lookup(doi, title):
        return "HAVE" if doi == "10.1000/inlib" else None

    second = run_watch(
        cfg,
        "ex",
        console=console,
        client=_client(works),
        lookup=lookup,
        backend=_Lib(),
    )
    assert second.proposed == 1
    assert inbox_count(cfg, "ex") == 1
    rows = [json.loads(line) for line in (second.run_dir / "candidates.jsonl").read_text().splitlines()]
    assert rows[0]["ids"]["doi"] == "10.1000/fresh"
    assert "doi:10.1000/inlib" in load_seen(cfg, "ex")
    assert "doi:10.1000/fresh" in load_seen(cfg, "ex")


def test_watch_apply_creates_from_proposed_queue(tmp_path: Path):
    from paperful.snowball.profile import save_profile
    from paperful.snowball.watch import run_watch, save_watch

    cfg = _cfg(tmp_path)
    (tmp_path / "profiles").mkdir()
    save_profile(
        cfg,
        "scout",
        {"mode": "search", "query": "bbnj", "gate": "dry-run"},
        force=False,
    )
    save_watch(cfg, "ap", "scout")
    works = {"W1": _work("W1", "10.1000/a", "Alpha", 2020, 1)}
    console = Console(file=StringIO(), highlight=False, width=120)
    run_watch(
        cfg,
        "ap",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=_Lib(),
    )
    works["W2"] = _work("W2", "10.1000/b", "Beta", 2021, 1)
    second = run_watch(
        cfg,
        "ap",
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        backend=_Lib(),
    )
    lib = _Lib()
    applied = run_apply(
        cfg,
        second.run_dir.name,
        SnowballRequest(gate="auto", collection="Inbox/Snowball", fetch_pdfs=False),
        console=console,
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert applied.exit_code == 0
    assert len(lib.created) == 1
    assert lib.created[0]["DOI"] == "10.1000/b"


def test_fill_pause_continues_and_retries_then_writes_settled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from paperful.snowball.fill import FillPaused, run_fill_pass
    from paperful.snowball.candidate import Candidate

    calls: list[str] = []

    def s2(doi: str) -> dict:
        calls.append(f"s2:{doi}")
        raise FillPaused("semanticscholar", [doi])

    def epmc(doi: str) -> dict:
        calls.append(f"epmc:{doi}")
        if doi in {"10.1000/seed", "10.1000/new"}:
            return {"references": [{"doi": "10.1000/from-epmc", "title": "From PMC", "year": 2020}]}
        return {}

    def pdf(doi: str) -> dict:
        calls.append(f"pdf:{doi}")
        return {"references": [{"doi": "10.1000/from-pdf", "title": "From PDF", "year": 2019}]}

    seed = Candidate(
        "r",
        {"type": "doi", "value": "10.1000/seed"},
        0,
        "refs",
        {"doi": "10.1000/seed"},
        {"title": "Seed"},
        "seed",
        "new",
        {"backend": "openalex"},
        "auto",
    )
    order_seen: list[str] = []

    def tracking_s2(doi: str) -> dict:
        order_seen.append("semanticscholar")
        return s2(doi)

    def tracking_epmc(doi: str) -> dict:
        order_seen.append("europepmc")
        return epmc(doi)

    def tracking_pdf(doi: str) -> dict:
        order_seen.append("pdf")
        return pdf(doi)

    rows = [seed]
    paused = run_fill_pass(
        rows,
        ("openalex", "semanticscholar", "europepmc", "pdf"),
        crossref_getter=None,
        s2_getter=tracking_s2,
        europepmc_getter=tracking_epmc,
        pdf_getter=tracking_pdf,
        per_hop_limit=15,
        direction="refs",
    )
    assert paused.get("semanticscholar")
    assert "10.1000/seed" in paused["semanticscholar"]
    assert order_seen[:3] == ["semanticscholar", "europepmc", "pdf"]
    assert calls.count("s2:10.1000/seed") == 2
    dois = {row.ids["doi"] for row in rows}
    assert "10.1000/from-epmc" in dois
    assert "10.1000/from-pdf" in dois

    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 1, refs=["W2"]),
        "W2": _work("W2", "10.1000/new", "New", 2021, 1),
    }
    fetched: list[str] = []

    def fake_fill_pdfs(cfg, backend, items, console, **kwargs):
        fetched.extend(item.doi or "" for item in items)
        return type("S", (), {"ok": len(items), "attached": 0})()

    monkeypatch.setattr("paperful.snowball.command.fill_pdfs", fake_fill_pdfs)
    client = _client(works)
    client.epmc_getter = epmc
    client.pdf_getter = lambda doi: {}
    lib = _CreateLib()
    result = run_doi(
        _cfg(tmp_path),
        ["10.1000/seed"],
        SnowballRequest(gate="auto", collection="Inbox/Snowball", fetch_pdfs="fast", backends=("openalex", "semanticscholar", "europepmc", "pdf")),
        console=Console(file=StringIO(), highlight=False, width=120),
        client=client,
        lookup=lambda doi, title: None,
        backend=lib,
        s2_getter=s2,
    )
    assert result.exit_code == 1
    assert (result.run_dir / "deferred.json").is_file()
    created = set(lib.created)
    assert "10.1000/new" not in created
    assert "10.1000/from-epmc" in created
    assert "10.1000/new" not in fetched
    assert "10.1000/from-epmc" in fetched


def test_fill_order_follows_backends_and_cached_pdf_is_written(tmp_path: Path):
    from paperful.snowball.command import _write_cached_pdfs
    from paperful.snowball.fill import run_fill_pass
    from paperful.zot import Item

    seen: list[str] = []

    def pdf(doi: str) -> dict:
        seen.append("pdf")
        return {}

    def epmc(doi: str) -> dict:
        seen.append("europepmc")
        return {}

    row = Candidate(
        "r",
        {"type": "doi", "value": "10.1000/seed"},
        0,
        "refs",
        {"doi": "10.1000/seed"},
        {"title": "Seed"},
        "seed",
        "new",
        {"backend": "openalex"},
        "auto",
    )
    run_fill_pass(
        [row],
        ("pdf", "europepmc"),
        crossref_getter=None,
        s2_getter=None,
        europepmc_getter=epmc,
        pdf_getter=pdf,
        per_hop_limit=5,
        direction="refs",
    )
    assert seen == ["pdf", "europepmc"]

    blob = tmp_path / "open.pdf"
    blob.write_bytes(b"%PDF-1.4 cached")
    row.biblio["cached_pdf"] = str(blob)
    item = Item(
        key="ITEM",
        item_type="journalArticle",
        title="Seed",
        doi="10.1000/seed",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Ada",
        collection_paths=["Inbox"],
    )
    _write_cached_pdfs(_cfg(tmp_path), [item], [row])
    written = list((tmp_path / "out").rglob("*.pdf"))
    assert written and written[0].read_bytes() == b"%PDF-1.4 cached"
