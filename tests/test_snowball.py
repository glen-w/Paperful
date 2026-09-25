"""Snowball dry-run, creates, and PDF handoff. No live network."""

from __future__ import annotations

import json
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
    run_search,
)
from paperful.snowball.expand import MAX_DEPTH, cap_ids, clamp_depth, keyword_depth, truncate
from paperful.snowball.candidate import Candidate
from paperful.snowball.openalex import OpenAlexClient
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
    rows = [
        Candidate("r", {"type": "doi", "value": "x"}, 1, "refs", {"doi": "10.1/b"}, {}, "w", "new", {}, "dry-run", score=1),
        Candidate("r", {"type": "doi", "value": "x"}, 1, "refs", {"doi": "10.1/a"}, {}, "w", "new", {}, "dry-run", score=5),
        Candidate("r", {"type": "doi", "value": "x"}, 1, "refs", {"doi": "10.1/c"}, {}, "w", "exists", {}, "dry-run", score=5),
    ]
    kept = truncate(rows, 2)
    assert [row.ids["doi"] for row in kept] == ["10.1/a", "10.1/c"]


def test_doi_refs_and_keyword_hits(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 3, ["W2", "W3"]),
        "W2": _work("W2", "10.1000/b", "Bee", 2019, 1),
        "W3": _work("W3", "10.1000/a", "Aye", 2018, 9),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=200)
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

    def fake_fill(cfg, backend, items, console):
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
    assert "semantic scholar key absent" in ready.detail
    assert ready.status == "amber"
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    keyed = _snowball_check(Config(snowball_enabled=True, email="a@b.c"), probe=probe)
    assert "key set" in keyed.detail
    assert "secret-key" not in keyed.detail
    assert "a@b.c" not in keyed.detail
    down = _snowball_check(Config(snowball_enabled=True, email="a@b.c"), probe=lambda email: "unreachable")
    assert down.status == "amber"
    assert "unreachable" in down.detail


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


def test_crossref_fills_empty_and_s2_skipped(tmp_path: Path):
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
    assert called["s2"] == 0


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
