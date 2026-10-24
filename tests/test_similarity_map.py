"""Similarity map: co-citation + bibliographic coupling (no live network)."""

from __future__ import annotations

import json

import pytest

from paperful.config import Config
from paperful.snowball.citation_graph import (
    CitationGraphError,
    build_graph,
    expand_queue,
    graph_for_run,
)
from paperful.snowball.explore import start_similar_explore
from paperful.snowball.openalex import OpenAlexClient
from paperful.snowball.queue import load_queue
from paperful.snowball.similarity_map import (
    citer_index,
    connect_to_seed,
    origin_paths,
    pairwise_links,
    pick_top,
    score_to_seed,
    similarity,
)


def _refs() -> dict[str, set[str]]:
    # S is the seed. A shares refs with S. B is cited alongside S by C1 and C2.
    # Z shares nothing with S.
    return {
        "S": {"R1", "R2", "R3"},
        "A": {"R1", "R2", "R9"},
        "B": {"Q1"},
        "Z": {"Q7"},
        "C1": {"S", "B"},
        "C2": {"S", "B", "A"},
    }


def test_coupling_and_cocitation_both_count():
    refs = _refs()
    citers = citer_index(refs)
    score_a, shared_a, co_a = similarity("S", "A", refs, citers)
    assert shared_a == 2 and score_a > 0
    score_b, shared_b, co_b = similarity("S", "B", refs, citers)
    # B never cites S and S never cites B, but two works cite both.
    assert shared_b == 0 and co_b == 2 and score_b > 0
    assert similarity("S", "Z", refs, citers)[0] == 0


def test_score_to_seed_drops_unrelated_and_ranks():
    refs = _refs()
    citers = citer_index(refs)
    scores = score_to_seed("S", refs, citers, ["A", "B", "Z"])
    assert "Z" not in scores
    top = pick_top(scores, limit=1)
    assert len(top) == 1 and top[0] in {"A", "B"}


def test_pairwise_keeps_top_k():
    refs = {
        "a": {"1", "2", "3"},
        "b": {"1", "2", "3"},
        "c": {"1", "2"},
        "d": {"1"},
    }
    edges = pairwise_links(["a", "b", "c", "d"], refs, {}, k=1, floor=0.0)
    # a and b are identical, so each picks the other. c and d each keep one edge.
    assert ("a", "b") in edges
    assert all(len(key) == 2 for key in edges)
    assert len(edges) <= 4


def test_connect_to_seed_links_isolated_node():
    edges: dict = {}
    connect_to_seed("S", ["S", "x"], edges, {"x": (0.3, 1, 0)})
    assert ("S", "x") in edges


def test_origin_paths_prefers_strong_route():
    edges = [
        {"source": "O", "target": "X", "direction": "similar", "weight": 0.05},
        {"source": "O", "target": "M", "direction": "similar", "weight": 1.0},
        {"source": "M", "target": "X", "direction": "similar", "weight": 1.0},
    ]
    paths = origin_paths(edges, "O")
    assert paths["O"] == []
    # Two strong steps (cost 0.2) beat one weak step (cost 1.05).
    assert len(paths["X"]) == 2
    assert {paths["X"][0]["source"], paths["X"][0]["target"]} == {"M", "X"}


def _work(oa: str, refs: list[str], *, cited: int = 1, doi: str = "") -> dict:
    return {
        "id": f"https://openalex.org/{oa}",
        "doi": f"https://doi.org/{doi}" if doi else "",
        "display_name": f"Paper {oa}",
        "publication_year": 2020,
        "cited_by_count": cited,
        "referenced_works": [f"https://openalex.org/{r}" for r in refs],
    }


class _PoolClient(OpenAlexClient):
    """Seed W0 cites R1-R3. Citers C1/C2 also cite X (co-cited, not linked to W0)."""

    def __init__(self) -> None:
        super().__init__(email="test@example.com")
        self.works = {
            "W0": _work("W0", ["R1", "R2", "R3"], cited=10, doi="10.1000/seed"),
            "R1": _work("R1", ["Q1"]),
            "R2": _work("R2", ["Q1"]),
            "R3": _work("R3", ["Q2"]),
            "C1": _work("C1", ["W0", "X", "R1"], cited=4),
            "C2": _work("C2", ["W0", "X"], cited=3),
            "P1": _work("P1", ["R1", "R2"], cited=5),
            "X": _work("X", ["Q9"], cited=7),
        }

    def work_by_doi(self, doi: str):
        return self.works["W0"] if doi == "10.1000/seed" else None

    def works_by_ids(self, openalex_ids, *, search=None):
        return [self.works[i] for i in openalex_ids if i in self.works]

    def works_citing(self, openalex_id, *, limit, **kwargs):
        sid = openalex_id.rsplit("/", 1)[-1]
        out = []
        for oa, work in self.works.items():
            refs = [r.rsplit("/", 1)[-1] for r in work["referenced_works"]]
            if sid in refs and oa != sid:
                out.append(work)
        return out[:limit]


def _start(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr("paperful.snowball.explore.get_backend", lambda _c: None)
    return cfg, start_similar_explore(cfg, _PoolClient(), query="10.1000/seed")


def test_start_similar_explore_builds_similarity_graph(tmp_path, monkeypatch):
    cfg, (run_id, graph) = _start(tmp_path, monkeypatch)
    assert run_id.startswith("similar-")
    summary = json.loads(
        (cfg.state_dir / "snowball" / run_id / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["mode"] == "similar"
    assert graph["layout"] == "similarity"
    ids = {node["id"] for node in graph["nodes"]}
    seed = next(node for node in graph["nodes"] if node["seed"])
    assert seed["id"] == "doi:10.1000/seed"
    # X never touches the seed directly, but its co-citation puts it on the map.
    assert "openalex:X" in ids
    assert graph["edges"]
    for edge in graph["edges"]:
        assert edge["direction"] == "similar"
        assert 0 < edge["weight"] <= 1
        assert edge["source"] in ids and edge["target"] in ids
    for node in graph["nodes"]:
        assert "origin_path" in node
        if not node["seed"]:
            assert node["origin_path"], node["id"]


def test_similarity_layout_survives_rebuild(tmp_path, monkeypatch):
    cfg, (run_id, _graph) = _start(tmp_path, monkeypatch)
    rebuilt = graph_for_run(cfg.state_dir, run_id)
    assert rebuilt["layout"] == "similarity"


def test_expand_rejects_similarity_queue(tmp_path, monkeypatch):
    cfg, (run_id, graph) = _start(tmp_path, monkeypatch)
    with pytest.raises(CitationGraphError, match="citation maps"):
        expand_queue(cfg.state_dir, run_id, graph["nodes"][0]["id"], "both", _PoolClient())


def test_no_shared_citations_is_an_error(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    monkeypatch.setattr("paperful.snowball.explore.get_backend", lambda _c: None)
    client = _PoolClient()
    client.works = {"W0": _work("W0", [], doi="10.1000/seed")}
    with pytest.raises(CitationGraphError, match="Not enough shared citations"):
        start_similar_explore(cfg, client, query="10.1000/seed")


def test_citation_queue_keeps_citation_layout(tmp_path, monkeypatch):
    cfg, (run_id, _graph) = _start(tmp_path, monkeypatch)
    _, rows = load_queue(cfg.state_dir, run_id)
    for row in rows:
        row.biblio.pop("sim_links", None)
    assert build_graph(rows, run_id=run_id)["layout"] == "citation"
