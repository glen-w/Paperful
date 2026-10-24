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
from paperful.snowball.similar_explore import start_similar_explore
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
            # R1 also cites R2, so it shares a reference with the seed.
            "R1": _work("R1", ["Q1", "R2"]),
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
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)
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
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)
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


# --- settings ---------------------------------------------------------------

from paperful.snowball.similar_settings import (  # noqa: E402
    DEFAULT,
    POOL_PRESETS,
    from_mapping,
    toml_literal,
)
from paperful.snowball.similarity_map import derivative_works, prior_works  # noqa: E402


def test_settings_clamp_and_presets():
    s = from_mapping(
        {
            "nodes": 9999,
            "peers": 0,
            "coupling_weight": "2",
            "min_similarity": "nan",
            "pool": "large",
            "year_from": 2020,
            "year_to": 2010,
            "source": "bogus",
            "color": "YEAR",
            "hide_in_library": "true",
        }
    )
    assert s.nodes == 150 and s.peers == 1
    assert s.coupling_weight == 1.0
    assert s.min_similarity == DEFAULT.min_similarity
    assert (s.ref_cap, s.citer_cap) == POOL_PRESETS["large"][:2]
    assert (s.year_from, s.year_to) == (2010, 2020)
    assert s.source == "auto" and s.color == "year" and s.hide_in_library is True
    # An explicit cap beats the preset; year 0 means "any".
    s2 = from_mapping({"pool": "small", "ref_cap": 50, "year_from": 0})
    assert s2.ref_cap == 50 and s2.citer_cap == POOL_PRESETS["small"][1]
    assert s2.year_from is None


def test_toml_literal_round_trips():
    import tomllib

    values = {"a": "x\"y", "b": None, "c": 0.25, "d": True, "e": 7}
    text = "\n".join(f"{k} = {toml_literal(v)}" for k, v in values.items())
    parsed = tomllib.loads(text)
    assert parsed == {"a": "x\"y", "b": 0, "c": 0.25, "d": True, "e": 7}


def test_config_reads_similar_map_table(tmp_path):
    from paperful.config import load_config
    from paperful.snowball.similar_settings import for_config

    path = tmp_path / "config.toml"
    path.write_text(
        'email = "t@example.com"\n[similar_map]\nnodes = 25\nsource = "store"\npool = "small"\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    s = for_config(cfg)
    assert (s.nodes, s.source, s.pool) == (25, "store", "small")


def test_coupling_weight_extremes():
    refs = _refs()
    citers = citer_index(refs)
    # B shares no refs with S, so it vanishes under coupling only.
    assert similarity("S", "B", refs, citers, 1.0)[0] == 0
    assert similarity("S", "B", refs, citers, 0.0)[0] > 0
    # A: 2 of 3 refs shared; co-cited by C2, one of S's two citers.
    assert similarity("S", "A", refs, citers, 1.0)[0] == pytest.approx(2 / 3)
    assert similarity("S", "A", refs, citers, 0.0)[0] == pytest.approx(1 / 2**0.5)


def test_prior_and_derivative_lists():
    refs = {"a": {"r1", "r2"}, "b": {"r1"}, "c": {"r1", "r2"}, "k": {"a", "b", "c"}, "j": {"a"}}
    assert prior_works(["a", "b", "c"], refs, limit=5) == [("r1", 3), ("r2", 2)]
    assert derivative_works(["a", "b", "c"], refs, limit=5) == [("k", 3)]
    assert prior_works(["a"], refs, limit=0) == []


# --- self-hosted store and failures ------------------------------------------


class _FakeStore:
    """Snapshot store serving the _PoolClient works."""

    def __init__(self, works: dict, *, cites: bool = True) -> None:
        self.works = works
        self.cites = cites
        self.calls = 0

    @property
    def has_cites_index(self) -> bool:
        return self.cites

    def work_by_doi(self, doi):
        self.calls += 1
        return self.works["W0"] if doi == "10.1000/seed" else None

    def works_by_dois(self, dois, *, select="id,doi,referenced_works"):
        return [w for d in dois if (w := self.work_by_doi(d))]

    def works_by_ids(self, ids):
        self.calls += 1
        return [self.works[i.rsplit("/", 1)[-1]] for i in ids if i.rsplit("/", 1)[-1] in self.works]

    def works_citing(self, openalex_id, *, limit, **kwargs):
        self.calls += 1
        if not self.cites:
            raise AssertionError("no cites index")
        sid = openalex_id.rsplit("/", 1)[-1]
        return [
            w
            for oa, w in self.works.items()
            if oa != sid and any(r.endswith("/" + sid) for r in w["referenced_works"])
        ][:limit]


def _no_api(path, query):
    raise AssertionError(f"live API called: {path}")


def _store_client(*, cites: bool = True) -> OpenAlexClient:
    works = _PoolClient().works
    return OpenAlexClient(email="t@example.com", getter=_no_api, store=_FakeStore(works, cites=cites))


def _cfg(tmp_path, monkeypatch, **similar):
    from paperful.snowball.similar_settings import from_mapping

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.similar_map = from_mapping(similar)
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)
    return cfg


def test_store_only_never_calls_live_api(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, source="store")
    client = _store_client()
    run_id, graph = start_similar_explore(cfg, client, query="10.1000/seed")
    report = graph["similar"]
    assert report["source"] == "store"
    assert report["api_calls"] == 0
    assert client.store.calls > 0
    assert "openalex:X" in {n["id"] for n in graph["nodes"]}


def test_store_only_without_cites_index_warns_and_still_maps(tmp_path, monkeypatch):
    from paperful.snowball.similar_explore import NO_CITES_INDEX

    cfg = _cfg(tmp_path, monkeypatch, source="store")
    client = _store_client(cites=False)
    _, graph = start_similar_explore(cfg, client, query="10.1000/seed")
    assert NO_CITES_INDEX in graph["similar"]["warnings"]
    assert graph["nodes"]


def test_store_only_rejects_title_search(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, source="store")
    with pytest.raises(CitationGraphError, match="paste a DOI"):
        start_similar_explore(cfg, _store_client(), query="some title words")


def test_store_source_without_store_configured(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, source="store")
    with pytest.raises(CitationGraphError, match="not configured"):
        start_similar_explore(cfg, query="10.1000/seed")


def test_auto_source_skips_misconfigured_store(tmp_path, monkeypatch):
    from paperful.snowball.similar_explore import similar_client
    from paperful.snowball.similar_settings import from_mapping

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.openalex_store_backend = "local_duckdb"  # no parquet_glob → misconfigured
    client, warnings = similar_client(cfg, from_mapping({"source": "auto"}))
    assert client.store is None
    assert warnings and "store skipped" in warnings[0]
    with pytest.raises(CitationGraphError, match="misconfigured"):
        similar_client(cfg, from_mapping({"source": "store"}))


def test_api_source_drops_store(tmp_path, monkeypatch):
    from paperful.snowball.similar_explore import similar_client
    from paperful.snowball.similar_settings import from_mapping

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    client, _ = similar_client(cfg, from_mapping({"source": "api"}), client=_store_client())
    assert client.store is None


def test_failing_step_becomes_warning(tmp_path, monkeypatch):
    from paperful.snowball.openalex import OpenAlexError

    class Flaky(_PoolClient):
        def works_citing(self, openalex_id, *, limit, **kwargs):
            raise OpenAlexError("boom")

    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, Flaky(), query="10.1000/seed")
    assert any("Citing papers: failed" in w for w in graph["similar"]["warnings"])
    assert graph["nodes"]


def test_budget_mid_pool_keeps_partial(tmp_path, monkeypatch):
    from paperful.snowball.openalex import OpenAlexBudgetExceeded

    class Budget(_PoolClient):
        def works_citing(self, openalex_id, *, limit, **kwargs):
            raise OpenAlexBudgetExceeded("spent")

    cfg = _cfg(tmp_path, monkeypatch)
    run_id, graph = start_similar_explore(cfg, Budget(), query="10.1000/seed")
    assert graph["similar"]["budget_hit"] is True
    summary = json.loads(
        (cfg.state_dir / "snowball" / run_id / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["budget_hit"] is True


def test_year_filter_and_node_cap(tmp_path, monkeypatch):
    client = _PoolClient()
    client.works["X"]["publication_year"] = 1990
    cfg = _cfg(tmp_path, monkeypatch, year_from=2000, nodes=5)
    _, graph = start_similar_explore(cfg, client, query="10.1000/seed")
    ids = {n["id"] for n in graph["nodes"]}
    assert "openalex:X" not in ids
    assert len(graph["nodes"]) <= 6


def test_hide_in_library(tmp_path, monkeypatch):
    def mark(rows, finder, **kwargs):
        for row in rows:
            if row.identity == "openalex:X":
                row.status = "exists"

    cfg = _cfg(tmp_path, monkeypatch, hide_in_library=True)
    monkeypatch.setattr("paperful.snowball.command._library_lookup", lambda *a, **k: None)
    monkeypatch.setattr("paperful.snowball.command._mark_exists", mark)
    _, graph = start_similar_explore(cfg, _PoolClient(), query="10.1000/seed")
    assert "openalex:X" not in {n["id"] for n in graph["nodes"]}
    assert graph["similar"]["hidden_in_library"] == 1


def test_report_and_extras_survive_rebuild(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, color="year")
    run_id, graph = start_similar_explore(cfg, _PoolClient(), query="10.1000/seed")
    rebuilt = graph_for_run(cfg.state_dir, run_id)
    assert rebuilt["similar"]["color"] == "year"
    on_map = {n["id"] for n in rebuilt["nodes"]}
    for item in rebuilt["similar"]["prior"] + rebuilt["similar"]["derivative"]:
        assert item["id"] not in on_map


# --- settings page -----------------------------------------------------------


def test_settings_page_saves_similar_map(tmp_path, monkeypatch):
    import tomllib

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.config import load_config
    from paperful.serve import create_app
    from paperful.snowball.similar_settings import for_config

    path = tmp_path / "config.toml"
    path.write_text('email = "t@example.com"\n', encoding="utf-8")
    cfg = load_config(path)
    cfg.out_dir = tmp_path / "out"
    cfg.state_dir = tmp_path / "state"
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    page = client.get("/settings")
    assert 'id="similar-map"' in page.text
    resp = client.post(
        "/settings/similar-map",
        data={
            "nodes": "30",
            "coupling_weight": "0.7",
            "peers": "3",
            "pool": "large",
            "source": "api",
            "color": "year",
            "year_from": "2015",
            "year_to": "",
            "hide_in_library": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    s = for_config(cfg)
    assert (s.nodes, s.coupling_weight, s.peers, s.pool, s.source) == (30, 0.7, 3, "large", "api")
    assert s.hide_in_library is True and s.year_from == 2015 and s.year_to is None
    saved = tomllib.loads(path.read_text(encoding="utf-8"))["similar_map"]
    assert saved["nodes"] == 30 and saved["source"] == "api" and saved["year_to"] == 0
    assert for_config(load_config(path)) == s
    client.post("/settings/similar-map", data={"reset": "1"}, follow_redirects=False)
    assert for_config(cfg) == DEFAULT
