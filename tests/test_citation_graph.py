"""Citation map roles, edges, and one-hop expand. No live network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.snowball.candidate import Candidate
from paperful.snowball.citation_graph import (
    MAX_NODES,
    SCHEMA,
    CitationGraphError,
    build_graph,
    expand_queue,
    graph_for_run,
    role_for,
)
from paperful.snowball.crawl import doi_candidates
from paperful.snowball.openalex import OpenAlexClient, OpenAlexError
from paperful.snowball.queue import write_queue


def test_roles_follow_year_and_citations():
    assert role_for(2010, 80, now_year=2026, threshold=50) == "foundational"
    assert role_for(2024, 80, now_year=2026, threshold=50) == "influential"
    assert role_for(2024, 3, now_year=2026, threshold=50) == "emerging"
    assert role_for(2010, 3, now_year=2026, threshold=50) == "other"
    assert role_for(None, 500, now_year=2026, threshold=50) == "other"


def test_edges_and_threshold_from_queue():
    seed = _candidate("10.1000/seed", "W1", "Seed paper", 2024, 12, hop=0, direction="search")
    old = _candidate(
        "10.1000/old",
        "W2",
        "Foundational review",
        2008,
        400,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
    )
    hot = _candidate(
        "10.1000/hot",
        "W3",
        "Influential now",
        2023,
        120,
        hop=1,
        direction="cites",
        links=[{"parent": seed.identity, "direction": "cites"}],
    )
    fresh = _candidate(
        "10.1000/fresh",
        "W4",
        "Emerging note",
        2025,
        4,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
    )
    quiet = _candidate(
        "10.1000/quiet",
        "W5",
        "Older aside",
        2001,
        2,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
    )
    graph = build_graph([seed, old, hot, fresh, quiet], run_id="R1", now_year=2026)
    assert graph["schema"] == SCHEMA
    assert graph["threshold"]["highly_cited"] == 50
    assert graph["threshold"]["recent_from_year"] == 2021
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id[old.identity]["role"] == "foundational"
    assert by_id[hot.identity]["role"] == "influential"
    assert by_id[fresh.identity]["role"] == "emerging"
    assert by_id[quiet.identity]["occasional"] is True
    pairs = {(edge["source"], edge["target"], edge["direction"]) for edge in graph["edges"]}
    assert (seed.identity, old.identity, "refs") in pairs
    assert (hot.identity, seed.identity, "cites") in pairs


def test_single_seed_fallback_when_links_were_not_recorded():
    seed = _candidate("10.1000/seed", "W1", "Seed", 2018, 10, hop=0, direction="doi")
    ref = _candidate("10.1000/ref", "W2", "Ref", 2010, 80, hop=1, direction="refs")
    graph = build_graph([seed, ref], run_id="R1", now_year=2026)
    assert graph["edges"] == [
        {"source": seed.identity, "target": ref.identity, "direction": "refs"}
    ]


def test_node_cap_keeps_seeds():
    rows = [_candidate("10.1000/seed", "W0", "Seed", 2020, 1, hop=0, direction="search")]
    for index in range(MAX_NODES + 20):
        rows.append(
            _candidate(
                f"10.1000/{index}",
                f"W{index + 1}",
                f"Paper {index}",
                2024,
                index,
                hop=1,
                direction="refs",
            )
        )
    graph = build_graph(rows, run_id="R1", now_year=2026, max_nodes=MAX_NODES)
    assert len(graph["nodes"]) == MAX_NODES
    assert any(node["seed"] for node in graph["nodes"])


def test_doi_hop_records_parent_link():
    seed = _work("W1", "10.1000/seed", "Seed", 2020, 40, refs=["W2"])
    cited = _work("W2", "10.1000/cited", "Cited work", 2004, 900)
    client = _client({"W1": seed, "W2": cited})
    rows, failed = doi_candidates(
        client,
        ["10.1000/seed"],
        run_id="Rhop",
        gate="dry-run",
        depth=1,
        direction="refs",
        max_candidates=20,
        per_hop_limit=10,
        year_from=None,
        year_to=None,
    )
    assert failed == []
    child = next(row for row in rows if row.ids.get("doi") == "10.1000/cited")
    assert child.biblio["graph_links"] == [
        {"parent": "doi:10.1000/seed", "direction": "refs"}
    ]


def test_expand_merges_neighbours_and_keeps_summary(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed paper", 2019, 30, hop=0, direction="doi")
    state = tmp_path / "state"
    dest = state / "snowball" / "Rexpand"
    dest.mkdir(parents=True)
    (dest / "candidates.jsonl").write_text(
        json.dumps(seed.to_dict()) + "\n",
        encoding="utf-8",
    )
    (dest / "summary.json").write_text('{"run_id": "Rexpand"}\n', encoding="utf-8")
    cited = _work("W2", "10.1000/old", "Old classic", 1999, 800)
    citer = _work("W3", "10.1000/new", "New note", 2025, 2)
    seed_work = _work("W1", "10.1000/seed", "Seed paper", 2019, 30, refs=["W2"])
    client = _client(
        {"W1": seed_work, "W2": cited, "W3": citer},
        citing={"W1": ["W3"]},
    )
    graph = expand_queue(state, "Rexpand", seed.identity, "both", client, now_year=2026)
    by_role = {node["role"] for node in graph["nodes"]}
    assert "foundational" in by_role
    assert "emerging" in by_role
    assert json.loads((dest / "summary.json").read_text())["run_id"] == "Rexpand"
    again = expand_queue(state, "Rexpand", seed.identity, "both", client, now_year=2026)
    assert len(again["nodes"]) == len(graph["nodes"])


def test_expand_reports_an_openalex_failure(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2019, 30, hop=0, direction="doi")
    state = tmp_path / "state"
    write_queue(state, "Rfail", [seed], _client({}), library_unread=False)

    def getter(path: str, params: dict) -> dict:
        raise OpenAlexError("down")

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    with pytest.raises(CitationGraphError, match="look up"):
        expand_queue(state, "Rfail", seed.identity, "refs", client)


def test_expand_rejects_a_bad_direction(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2019, 30, hop=0, direction="doi")
    state = tmp_path / "state"
    write_queue(state, "Rbad", [seed], _client({}), library_unread=False)
    with pytest.raises(CitationGraphError):
        expand_queue(state, "Rbad", seed.identity, "keywords", _client({}))


def test_graph_for_run_rewrites_the_file(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2022, 5, hop=0, direction="search")
    state = tmp_path / "state"
    write_queue(state, "Rfile", [seed], _client({}), library_unread=False)
    path = state / "snowball" / "Rfile" / "citation_graph.json"
    assert path.is_file()
    path.unlink()
    graph = graph_for_run(state, "Rfile")
    assert graph["run_id"] == "Rfile"
    assert json.loads(path.read_text())["schema"] == SCHEMA
    with pytest.raises(CitationGraphError):
        graph_for_run(state, "../etc")


@pytest.mark.skipif(
    __import__("paperful.serve", fromlist=["fastapi_available"]).fastapi_available() is False,
    reason="paperful[serve] extra missing",
)
def test_discover_page_includes_the_map(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    seed = _candidate("10.1000/seed", "W1", "Seed paper", 2020, 9, hop=0, direction="search")
    write_queue(cfg.state_dir, "Rpage", [seed], _client({}), library_unread=False)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    page = client.get("/discover")
    assert page.status_code == 200
    assert 'id="citationMapApp"' in page.text
    graph = client.get("/discover/graph", params={"run_id": "Rpage"})
    assert graph.status_code == 200
    body = graph.json()
    assert body["schema"] == SCHEMA
    assert body["nodes"][0]["title"] == "Seed paper"
    missing = client.get("/discover/graph", params={"run_id": "no-such-run"})
    assert missing.status_code == 404
    bad = client.get("/discover/graph", params={"run_id": "../etc"})
    assert bad.status_code == 400


def _candidate(
    doi: str,
    oa: str,
    title: str,
    year: int,
    cited: int,
    *,
    hop: int,
    direction: str,
    links: list[dict[str, str]] | None = None,
) -> Candidate:
    biblio: dict[str, object] = {
        "title": title,
        "year": year,
        "cited_by_count": cited,
        "authors": ["Ada Lovelace"],
    }
    if links:
        biblio["graph_links"] = links
    return Candidate(
        run_id="R1",
        seed={"type": "doi", "value": "10.1000/seed"},
        hop=hop,
        direction=direction,
        ids={"doi": doi, "openalex": oa},
        biblio=biblio,
        why="test",
        status="new",
        provenance={"backend": "test"},
        gate="dry-run",
        score=float(cited),
    )


def _work(
    oa: str,
    doi: str,
    title: str,
    year: int,
    cites: int,
    refs: list[str] | None = None,
) -> dict:
    return {
        "id": f"https://openalex.org/{oa}",
        "doi": f"https://doi.org/{doi}",
        "display_name": title,
        "publication_year": year,
        "type": "article",
        "cited_by_count": cites,
        "referenced_works": [f"https://openalex.org/{ref}" for ref in (refs or [])],
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {"source": {"display_name": "Marine Policy"}},
    }


def _client(
    works: dict[str, dict],
    *,
    citing: dict[str, list[str]] | None = None,
) -> OpenAlexClient:
    citing = citing or {}

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
            return {"results": [works[i] for i in ids if i in works]}
        if "cites:" in filt:
            seed = ""
            for part in filt.split(","):
                if part.startswith("cites:"):
                    seed = part.split(":", 1)[1]
            ids = citing.get(seed, [])
            return {"results": [works[i] for i in ids if i in works]}
        return {"results": []}

    return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
