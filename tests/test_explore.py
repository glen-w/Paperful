"""OpenAlex explore map seeding (no live network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.snowball.explore import ExploreAmbiguous, resolve_work, start_explore
from paperful.snowball.openalex import OpenAlexClient


class _FakeClient(OpenAlexClient):
    def __init__(self) -> None:
        super().__init__(email="test@example.com")
        self.requests = 0

    def work_by_doi(self, doi: str):
        if doi == "10.1000/seed":
            return {
                "id": "https://openalex.org/Wseed",
                "doi": "https://doi.org/10.1000/seed",
                "display_name": "Seed paper",
                "publication_year": 2020,
                "cited_by_count": 12,
            }
        return None

    def search(self, query: str, *, limit: int, year_from, year_to, **kwargs):
        if query == "unique title":
            return [
                {
                    "id": "https://openalex.org/Wone",
                    "doi": "https://doi.org/10.1000/one",
                    "display_name": "Only hit",
                    "publication_year": 2019,
                    "cited_by_count": 3,
                }
            ]
        return [
            {
                "id": "https://openalex.org/Wa",
                "display_name": "Paper A",
                "publication_year": 2018,
                "cited_by_count": 1,
            },
            {
                "id": "https://openalex.org/Wb",
                "display_name": "Paper B",
                "publication_year": 2017,
                "cited_by_count": 2,
            },
        ]


def test_resolve_work_doi_and_ambiguous_title():
    client = _FakeClient()
    work = resolve_work(client, query="10.1000/seed")
    assert work["display_name"] == "Seed paper"
    with pytest.raises(ExploreAmbiguous) as exc:
        resolve_work(client, query="many hits")
    assert len(exc.value.picks) == 2


def test_start_explore_writes_queue_and_expands(monkeypatch, tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client = _FakeClient()

    def fake_expand(state_dir, run_id, node_id, direction, oa, **kwargs):
        from paperful.snowball.citation_graph import build_graph, write_graph_file
        from paperful.snowball.queue import load_queue

        _, rows = load_queue(state_dir, run_id)
        graph = build_graph(rows, run_id=run_id, focus=node_id)
        write_graph_file(Path(state_dir) / "snowball" / run_id, graph)
        return graph

    monkeypatch.setattr(
        "paperful.snowball.explore.expand_queue",
        fake_expand,
    )
    monkeypatch.setattr(
        "paperful.snowball.explore.get_backend",
        lambda _c: None,
    )

    run_id, graph = start_explore(cfg, client, query="10.1000/seed")
    assert run_id.startswith("explore-")
    dest = cfg.state_dir / "snowball" / run_id
    assert (dest / "candidates.jsonl").is_file()
    summary = json.loads((dest / "summary.json").read_text(encoding="utf-8"))
    assert summary.get("mode") == "explore"
    assert graph["schema"] == "paperful.citation_graph.v1"


def test_discover_explore_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})

    def fake_start(_cfg, _client, **kwargs):
        from paperful.snowball.candidate import Candidate
        from paperful.snowball.queue import write_queue

        run_id = "explore-test"
        row = Candidate(
            run_id=run_id,
            seed={"type": "explore", "value": "x"},
            hop=0,
            direction="explore",
            ids={"doi": "10.1000/seed"},
            biblio={"title": "Seed", "year": 2020, "cited_by_count": 1},
            why="test",
            status="new",
            provenance={"backend": "openalex"},
            gate="dry-run",
        )
        write_queue(_cfg.state_dir, run_id, [row], _FakeClient(), library_unread=False, meta={"mode": "explore"})
        return run_id, {"schema": "paperful.citation_graph.v1", "nodes": [], "edges": []}

    monkeypatch.setattr("paperful.snowball.explore.start_explore", fake_start)
    client = TestClient(create_app(cfg))
    page = client.get("/discover?tab=explore")
    assert "discoverExploreSection" in page.text
    resp = client.post("/discover/explore", data={"query": "10.1000/seed"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "/discover?tab=queue" in resp.headers["location"]


def test_discover_explore_route_similar(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    calls: list[str] = []

    def fake_similar(_cfg, _client, **kwargs):
        calls.append("similar")
        return "similar-test", {"layout": "similarity", "nodes": [], "edges": []}

    def fake_citation(_cfg, _client, **kwargs):
        calls.append("citation")
        return "explore-test", {"nodes": [], "edges": []}

    monkeypatch.setattr("paperful.snowball.explore.start_similar_explore", fake_similar)
    monkeypatch.setattr("paperful.snowball.explore.start_explore", fake_citation)
    client = TestClient(create_app(cfg))
    page = client.get("/discover?tab=explore")
    assert 'name="map" value="similar"' in page.text
    resp = client.post(
        "/discover/explore",
        data={"query": "10.1000/seed", "map": "similar"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/discover?tab=queue" in resp.headers["location"]
    assert calls == ["similar"]
