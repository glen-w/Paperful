"""Similar map: invariants on random corpora, degenerate inputs, and settings."""

from __future__ import annotations

import json
import random

import pytest

from paperful.config import Config
from paperful.snowball.citation_graph import CitationGraphError, graph_for_run
from paperful.snowball.openalex import OpenAlexClient
from paperful.snowball.similar_explore import start_similar_explore
from paperful.snowball.similar_settings import DEFAULT, SimilarSettings, from_mapping
from paperful.snowball.similarity_map import (
    citer_index,
    connect_to_seed,
    origin_paths,
    pairwise_links,
    similarity,
)


def _u(oa: str) -> str:
    return f"https://openalex.org/{oa}"


class CorpusClient(OpenAlexClient):
    """In-memory OpenAlex over a dict of works keyed by short id."""

    def __init__(self, works: dict[str, dict]) -> None:
        super().__init__(email="t@example.com", getter=self._no_http)
        self.works = works
        self.by_doi = {
            str(w.get("doi") or "").lower().replace("https://doi.org/", ""): w
            for w in works.values()
            if w.get("doi")
        }

    @staticmethod
    def _no_http(path, query):
        raise AssertionError(f"unexpected HTTP {path}")

    def work_by_doi(self, doi):
        return self.by_doi.get(doi.lower())

    def works_by_ids(self, ids, *, search=None):
        out = []
        for i in ids:
            work = self.works.get(i.rsplit("/", 1)[-1])
            if work is not None:
                out.append(work)
        return out

    def works_citing(self, openalex_id, *, limit, sort=None, **kwargs):
        sid = openalex_id.rsplit("/", 1)[-1]
        hits = [
            w
            for oa, w in self.works.items()
            if oa != sid and _u(sid) in (w.get("referenced_works") or [])
        ]
        if sort == "cited_by_count:desc":
            hits.sort(key=lambda w: -int(w.get("cited_by_count") or 0))
        return hits[:limit]


def random_corpus(rng: random.Random, size: int) -> dict[str, dict]:
    works: dict[str, dict] = {}
    ids = [f"W{i}" for i in range(size)]
    for index, oa in enumerate(ids):
        # Cite only earlier works, a few clusters, with some empty lists.
        pool = ids[:index]
        k = 0 if not pool or rng.random() < 0.1 else rng.randint(1, min(12, len(pool)))
        refs = rng.sample(pool, k)
        works[oa] = {
            "id": _u(oa),
            "doi": f"https://doi.org/10.1000/{oa.lower()}" if rng.random() < 0.85 else None,
            "display_name": f"Paper {oa}",
            "publication_year": None if rng.random() < 0.05 else 1990 + index % 35,
            "type": "article",
            "cited_by_count": rng.randint(0, 500),
            "referenced_works": [_u(r) for r in refs] if rng.random() > 0.03 else None,
        }
    return works


def _cfg(tmp_path, monkeypatch, **similar) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.similar_map = from_mapping(similar)
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)
    return cfg


def check_graph(graph: dict, settings: SimilarSettings) -> None:
    """Structural guarantees every Similar map must meet."""
    json.dumps(graph)  # serialisable
    assert graph["layout"] == "similarity"
    nodes = graph["nodes"]
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), "duplicate node ids"
    seeds = [n for n in nodes if n["seed"]]
    assert len(seeds) == 1
    origin = seeds[0]["id"]
    assert 2 <= len(nodes) <= settings.nodes + 1
    pairs = set()
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        assert a != b and a in ids and b in ids
        assert a < b, "edges are stored with sorted endpoints"
        assert (a, b) not in pairs, "duplicate edge"
        pairs.add((a, b))
        assert edge["direction"] == "similar"
        assert 0 < edge["weight"] <= 1
    if graph["edges"]:
        assert max(e["weight"] for e in graph["edges"]) == 1
    for node in nodes:
        assert 0 <= node["similarity"] <= 1
        path = node["origin_path"]
        if node["seed"]:
            assert path == []
            continue
        # Every paper reaches the origin through edges that exist, end to end.
        assert path, f"{node['id']} has no path to the origin"
        cur = node["id"]
        for step in path:
            assert (min(step["source"], step["target"]), max(step["source"], step["target"])) in pairs
            assert cur in (step["source"], step["target"])
            cur = step["target"] if cur == step["source"] else step["source"]
        assert cur == origin
    report = graph["similar"]
    for key in ("prior", "derivative"):
        assert all(item["id"] not in ids for item in report[key])
    assert len(report["prior"]) <= settings.prior_works
    assert len(report["derivative"]) <= settings.derivative_works


@pytest.mark.parametrize("seed", range(25))
def test_random_corpora_meet_invariants(tmp_path, monkeypatch, seed):
    rng = random.Random(seed)
    works = random_corpus(rng, rng.randint(40, 220))
    with_doi = [w for w in works.values() if w.get("doi") and w.get("referenced_works")]
    origin = rng.choice(with_doi[len(with_doi) // 3 :])
    settings = from_mapping(
        {
            "nodes": rng.choice([5, 12, 40, 150]),
            "peers": rng.randint(1, 10),
            "coupling_weight": rng.choice([0, 0.2, 0.5, 1]),
            "min_similarity": rng.choice([0, 0.02, 0.1]),
            "pool": rng.choice(["small", "standard", "large"]),
        }
    )
    cfg = _cfg(tmp_path, monkeypatch)
    doi = origin["doi"].replace("https://doi.org/", "")
    try:
        run_id, graph = start_similar_explore(
            cfg, CorpusClient(works), query=doi, settings=settings
        )
    except CitationGraphError as exc:
        assert "Not enough shared citations" in str(exc)
        return
    check_graph(graph, settings)
    # A rebuild from disk gives the same map.
    rebuilt = graph_for_run(cfg.state_dir, run_id)
    assert {n["id"] for n in rebuilt["nodes"]} == {n["id"] for n in graph["nodes"]}
    assert rebuilt["edges"] == graph["edges"]


@pytest.mark.parametrize("seed", range(30))
def test_similarity_is_symmetric_and_bounded(seed):
    rng = random.Random(seed)
    names = [f"n{i}" for i in range(12)]
    refs = {n: set(rng.sample(names + ["x", "y", "z"], rng.randint(0, 6))) for n in names}
    citers = citer_index(refs)
    w = rng.random()
    for a in names:
        for b in names:
            s_ab = similarity(a, b, refs, citers, w)
            s_ba = similarity(b, a, refs, citers, w)
            assert s_ab == s_ba
            assert 0 <= s_ab[0] <= 1 + 1e-9
            if a == b:
                assert s_ab == (0.0, 0, 0)


@pytest.mark.parametrize("seed", range(30))
def test_connect_to_seed_makes_everything_reachable(seed):
    rng = random.Random(seed)
    ids = ["S"] + [f"n{i}" for i in range(rng.randint(1, 25))]
    refs = {n: set(rng.sample(["a", "b", "c", "d", "e", "f"], rng.randint(0, 3))) for n in ids}
    citers = citer_index(refs)
    links = pairwise_links(ids, refs, citers, k=rng.randint(1, 4), floor=0.0)
    scores = {n: (0.1, 0, 0) for n in ids[1:]}
    connect_to_seed("S", ids, links, scores)
    edges = [{"source": a, "target": b, "weight": s[0] or 0.01} for (a, b), s in links.items()]
    paths = origin_paths(edges, "S")
    assert set(paths) == set(ids)


def test_peers_degree_bound():
    refs = {f"n{i}": {"a", "b", f"own{i}"} for i in range(10)}
    links = pairwise_links(list(refs), refs, {}, k=2, floor=0.0)
    degree: dict[str, int] = {}
    for a, b in links:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    # Each node picked two peers; it can be picked by others too, but never zero.
    assert all(d >= 2 for d in degree.values())
    assert len(links) <= 10 * 2


# --- degenerate corpora ----------------------------------------------------------


def _corpus(spec: dict[str, list[str]], **extra) -> dict[str, dict]:
    works = {}
    for oa, refs in spec.items():
        works[oa] = {
            "id": _u(oa),
            "doi": f"https://doi.org/10.1000/{oa.lower()}",
            "display_name": oa,
            "publication_year": 2020,
            "cited_by_count": 1,
            "referenced_works": [_u(r) for r in refs],
        }
    for oa, fields in extra.items():
        works[oa].update(fields)
    return works


def test_seed_with_no_references_uses_cocitation(tmp_path, monkeypatch):
    # S cites nothing. C1, C2 cite S and X, so X is co-cited with S.
    works = _corpus({"S": [], "X": [], "C1": ["S", "X"], "C2": ["S", "X"]})
    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")
    assert "doi:10.1000/x" in {n["id"] for n in graph["nodes"]}


def test_seed_never_cited_uses_coupling(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1", "R2"]})
    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")
    assert "doi:10.1000/p" in {n["id"] for n in graph["nodes"]}


def test_isolated_seed_is_a_clear_error(tmp_path, monkeypatch):
    works = _corpus({"S": [], "Z": []})
    cfg = _cfg(tmp_path, monkeypatch)
    with pytest.raises(CitationGraphError, match="Not enough shared citations"):
        start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")


def test_min_similarity_one_filters_everything(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1"]})
    cfg = _cfg(tmp_path, monkeypatch, min_similarity=1)
    with pytest.raises(CitationGraphError):
        start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")


def test_null_and_missing_fields_do_not_crash(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "S": ["R1"], "P": ["R1"], "Q": ["R1"]})
    works["P"].update({"referenced_works": [_u("R1"), None, "", "not-a-url"], "cited_by_count": None})
    works["Q"].update({"publication_year": "unknown", "display_name": None, "doi": None})
    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")
    check_graph(graph, from_mapping({}))
    assert "openalex:Q" in {n["id"] for n in graph["nodes"]}


def test_duplicate_doi_and_seed_alias_are_collapsed(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1", "R2"], "P2": ["R1", "R2"], "S2": ["R1", "R2"]})
    works["P2"]["doi"] = works["P"]["doi"]  # same paper, two OpenAlex ids
    works["S2"]["doi"] = works["S"]["doi"]  # an alias of the origin
    client = CorpusClient(works)
    client.by_doi["10.1000/s"] = works["S"]
    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, client, query="10.1000/s")
    ids = [n["id"] for n in graph["nodes"]]
    assert ids.count("doi:10.1000/p") == 1
    assert ids.count("doi:10.1000/s") == 1
    check_graph(graph, from_mapping({}))


def test_origin_without_doi_by_node_id(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1", "R2"]})
    works["S"]["doi"] = None
    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, CorpusClient(works), node_id="openalex:S")
    seed = next(n for n in graph["nodes"] if n["seed"])
    assert seed["id"] == "openalex:S"


def test_full_150_nodes_plus_origin_all_drawn(tmp_path, monkeypatch):
    spec = {f"R{i}": [] for i in range(5)}
    spec["S"] = [f"R{i}" for i in range(5)]
    for i in range(200):
        spec[f"P{i}"] = [f"R{i % 5}", f"R{(i + 1) % 5}"]
    works = _corpus(spec)

    class Big(CorpusClient):
        pass

    cfg = _cfg(tmp_path, monkeypatch, nodes=150, partners_per_ref=200, partner_refs=5)
    run_id, graph = start_similar_explore(cfg, Big(works), query="10.1000/s")
    assert len(graph["nodes"]) == 151
    assert len(graph_for_run(cfg.state_dir, run_id)["nodes"]) == 151


def test_year_filter_excludes_undated(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1", "R2"], "Q": ["R1", "R2"]})
    works["Q"]["publication_year"] = None
    cfg = _cfg(tmp_path, monkeypatch, year_from=2000)
    _, graph = start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")
    ids = {n["id"] for n in graph["nodes"]}
    assert "doi:10.1000/p" in ids and "doi:10.1000/q" not in ids


def test_hide_everything_is_a_clear_error(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "S": ["R1"], "P": ["R1"]})

    def mark(rows, finder, **kwargs):
        for row in rows:
            row.status = "exists"

    cfg = _cfg(tmp_path, monkeypatch, hide_in_library=True)
    monkeypatch.setattr("paperful.snowball.command._library_lookup", lambda *a, **k: None)
    monkeypatch.setattr("paperful.snowball.command._mark_exists", mark)
    with pytest.raises(CitationGraphError, match="already in your library"):
        start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")


def test_unreadable_library_with_hide_warns(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "S": ["R1"], "P": ["R1"]})
    cfg = _cfg(tmp_path, monkeypatch, hide_in_library=True)

    def boom(_c):
        raise RuntimeError("zotero down")

    monkeypatch.setattr("paperful.snowball.command.get_backend", boom)
    _, graph = start_similar_explore(cfg, CorpusClient(works), query="10.1000/s")
    assert any("library papers were not hidden" in w for w in graph["similar"]["warnings"])


def test_store_failure_becomes_warning(tmp_path, monkeypatch):
    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1", "R2"]})

    class BrokenStore:
        has_cites_index = True

        def work_by_doi(self, doi):
            return works["S"] if doi == "10.1000/s" else None

        def works_by_dois(self, dois, *, select=""):
            return []

        def works_by_ids(self, ids):
            raise RuntimeError("duckdb timed out")

        def works_citing(self, oa, **kwargs):
            raise RuntimeError("duckdb timed out")

    client = OpenAlexClient(email="t@example.com", getter=CorpusClient._no_http, store=BrokenStore())
    cfg = _cfg(tmp_path, monkeypatch, source="store")
    with pytest.raises(CitationGraphError) as exc:
        start_similar_explore(cfg, client, query="10.1000/s")
    assert "store failed" in str(exc.value)


# --- settings -------------------------------------------------------------------


def test_settings_round_trip_and_idempotent():
    rng = random.Random(7)
    for _ in range(200):
        raw = {
            key: rng.choice([None, "", "abc", -5, 0, 1, 3.7, 10**9, True, "large", "year", "store"])
            for key in DEFAULT.to_dict()
        }
        s = from_mapping(raw)
        assert from_mapping(s.to_dict()) == s
        assert s.merged(s.to_dict()) == s
        assert 5 <= s.nodes <= 150 and 1 <= s.peers <= 10
        assert 0 <= s.coupling_weight <= 1 and 0 <= s.min_similarity <= 1
        assert s.source in ("auto", "store", "api") and s.color in ("map", "role", "year", "category")
        if s.year_from is not None and s.year_to is not None:
            assert s.year_from <= s.year_to


def test_settings_reject_unknown_table_types(tmp_path):
    from paperful.config import load_config
    from paperful.snowball.similar_settings import for_config

    path = tmp_path / "config.toml"
    path.write_text('email = "t@example.com"\nsimilar_map = "oops"\n', encoding="utf-8")
    assert for_config(load_config(path)) == DEFAULT


def test_api_outage_in_auto_mode_falls_back_to_store_once(tmp_path, monkeypatch):
    """After one network failure the map finishes from the store, without more API calls."""
    from paperful.snowball.openalex import OpenAlexError

    works = _corpus({"R1": [], "R2": [], "S": ["R1", "R2"], "P": ["R1", "R2"], "C": ["S", "P"]})
    calls = {"api": 0}

    class Store:
        has_cites_index = True

        def work_by_doi(self, doi):
            return works["S"] if doi == "10.1000/s" else None

        def works_by_dois(self, dois, *, select=""):
            return []

        def works_by_ids(self, ids):
            return [works[i.rsplit("/", 1)[-1]] for i in ids if i.rsplit("/", 1)[-1] in works]

        def works_citing(self, oa, **kwargs):
            sid = oa.rsplit("/", 1)[-1]
            if sid == "S":
                return []  # empty: the client falls through to the API
            return [w for k, w in works.items() if k != sid and _u(sid) in w["referenced_works"]]

    def down(path, query):
        calls["api"] += 1
        raise OpenAlexError("network down")

    client = OpenAlexClient(email="t@example.com", getter=down, store=Store())
    cfg = _cfg(tmp_path, monkeypatch)
    _, graph = start_similar_explore(cfg, client, query="10.1000/s")
    assert calls["api"] == 1
    assert any("used your store only" in w for w in graph["similar"]["warnings"])
    assert "doi:10.1000/p" in {n["id"] for n in graph["nodes"]}
