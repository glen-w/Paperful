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
from paperful.snowball.command import SnowballError, SnowballRequest, run_doi, run_orcid, run_search
from paperful.snowball.expand import cap_ids, clamp_depth, keyword_depth, truncate
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


def _client(works: dict[str, dict]) -> OpenAlexClient:
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
    assert clamp_depth(2) == (1, "depth clamped to 1")
    assert keyword_depth(None) == 0
    assert keyword_depth(2) == 1
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
        SnowballRequest(depth=2),
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


class _Lib:
    def __init__(self):
        self.created: list[dict] = []
        self.notes: list[tuple[str, str]] = []

    def ensure_collection_path(self, path: str) -> str:
        assert path == "Inbox/Snowball"
        return "COL1"

    def create_parent(self, data: dict) -> str:
        self.created.append(data)
        return f"ITEM{len(self.created)}"

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        self.notes.append((item_key, html, tag))
        return "NOTE"


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


def test_cli_refusals(tmp_path: Path):
    off = tmp_path / "off.toml"
    off.write_text(f'email = "t@example.org"\nstate_dir = "{tmp_path / "state"}"\n')
    assert runner.invoke(cli.app, ["snowball", "search", "bbnj", "-c", str(off)]).exit_code == 2
    assert runner.invoke(cli.app, ["snowball", "orcid", "0000-0002-9162-9618", "-c", str(off)]).exit_code == 2
    on = tmp_path / "on.toml"
    on.write_text(off.read_text() + "\n[snowball]\nenabled = true\n")
    refused = runner.invoke(
        cli.app, ["snowball", "doi", "10.1/x", "--gate", "approve-batch", "-c", str(on)]
    )
    assert refused.exit_code == 2
    with pytest.raises(SnowballError):
        run_orcid()


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


def test_cites_and_auto_without_collection_exit(tmp_path: Path):
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    with pytest.raises(SnowballError, match="Cited-by"):
        run_doi(cfg, ["10.1000/seed"], SnowballRequest(direction="cites"), console=console, client=_client({}))
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
    ready = _snowball_check(Config(snowball_enabled=True, email="a@b.c"))
    assert "no OpenAlex key" in ready.detail
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    keyed = _snowball_check(Config(snowball_enabled=True, email="a@b.c"))
    assert keyed.detail == "enabled (key set)"
    assert "secret-key" not in keyed.detail

