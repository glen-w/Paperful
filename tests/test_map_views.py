"""[map] settings, the author layer and author view, and queue robustness."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from paperful.config import Config, load_config
from paperful.snowball.candidate import Candidate
from paperful.snowball.citation_graph import build_graph, expand_queue, graph_for_run
from paperful.snowball.map_authors import (
    author_network,
    author_summary,
    follow_author,
    followed_keys,
    mark_followed,
    node_authors,
)
from paperful.snowball.map_settings import DEFAULT, MapSettings, from_mapping
from paperful.snowball.openalex import OpenAlexClient
from paperful.snowball.queue import (
    atomic_write_text,
    load_queue,
    load_queue_checked,
    write_queue,
)


def _row(
    doi: str,
    *,
    hop: int = 1,
    year: int = 2020,
    cited: int = 10,
    authors: list[tuple[str, str]] | None = None,
    links: list[dict] | None = None,
    direction: str = "refs",
) -> Candidate:
    records = [
        {"openalex": oa, "orcid": "", "display_name": name, "fingerprint": ""}
        for name, oa in (authors or [])
    ]
    biblio = {
        "title": f"Paper {doi}",
        "year": year,
        "cited_by_count": cited,
        "authors": [name for name, _ in (authors or [])],
        "author_records": records,
    }
    if links:
        biblio["graph_links"] = links
    return Candidate(
        run_id="R1",
        seed={"type": "doi", "value": "seed"},
        hop=hop,
        direction=direction if hop else "doi",
        ids={"doi": doi, "openalex": ""},
        biblio=biblio,
        why="test",
        status="new",
        provenance={"backend": "openalex"},
        gate="dry-run",
    )


def _queue() -> list[Candidate]:
    seed = _row("10.1/seed", hop=0, year=2015, cited=900, authors=[("Ada Lovelace", "A1"), ("Bob Babbage", "A2")])
    p1 = _row("10.1/p1", year=2010, cited=400, authors=[("Ada Lovelace", "A1"), ("Cy Clarke", "A3")],
              links=[{"parent": "doi:10.1/seed", "direction": "refs"}])
    p2 = _row("10.1/p2", year=2023, cited=5, authors=[("Dee Dodd", "A4")],
              links=[{"parent": "doi:10.1/seed", "direction": "cites"}])
    p3 = _row("10.1/p3", year=2024, cited=2, authors=[("Cy Clarke", "A3"), ("Dee Dodd", "A4")],
              links=[{"parent": "doi:10.1/seed", "direction": "cites"}])
    return [seed, p1, p2, p3]


# --- settings --------------------------------------------------------------------


def test_map_settings_clamp_and_round_trip():
    rng = random.Random(3)
    for _ in range(200):
        raw = {
            key: rng.choice([None, "", "x", -1, 0, 3, 99999, True, "year", "authors", "coauthor", "uniform"])
            for key in DEFAULT.to_dict()
        }
        s = from_mapping(raw)
        assert from_mapping(s.to_dict()) == s
        assert 20 <= s.max_nodes <= 400 and 5 <= s.neighbors <= 100
        assert 5 <= s.author_nodes <= 300 and 1 <= s.author_peers <= 15
        assert s.color in ("role", "year", "category")
        assert s.default_view in ("papers", "authors")
        assert s.author_links in ("both", "coauthor")


def test_config_reads_map_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'email = "t@example.com"\n[map]\ncolor = "year"\nmax_nodes = 60\ndefault_view = "authors"\n',
        encoding="utf-8",
    )
    from paperful.snowball.map_settings import for_config

    s = for_config(load_config(path))
    assert (s.color, s.max_nodes, s.default_view) == ("year", 60, "authors")


def test_build_graph_uses_settings():
    rows = _queue()
    default = build_graph(rows, run_id="R1", now_year=2025)
    assert default["view"]["color"] == "role"
    roles = {n["id"]: n["role"] for n in default["nodes"]}
    assert roles["doi:10.1/p1"] == "foundational"
    # A huge floor makes nothing "highly cited"; a 20-year window makes 2010 recent.
    tuned = build_graph(
        rows, run_id="R1", now_year=2025,
        settings=MapSettings(citation_floor=100_000, recent_years=20, color="year", max_nodes=20),
    )
    assert tuned["view"]["color"] == "year"
    assert tuned["thresholds"]["citation_floor"] == 100_000
    assert {n["id"]: n["role"] for n in tuned["nodes"]}["doi:10.1/p1"] == "emerging"
    capped = build_graph(rows * 1, run_id="R1", settings=MapSettings(max_nodes=20), max_nodes=2)
    assert len(capped["nodes"]) == 2


def test_expand_respects_neighbors_setting(tmp_path):
    works = {"W0": {"id": "https://openalex.org/W0", "doi": "https://doi.org/10.1/seed", "display_name": "Seed",
                    "publication_year": 2020, "cited_by_count": 1, "referenced_works": []}}
    for i in range(40):
        works[f"C{i}"] = {"id": f"https://openalex.org/C{i}", "doi": f"https://doi.org/10.1/c{i}",
                          "display_name": f"C{i}", "publication_year": 2021, "cited_by_count": i,
                          "referenced_works": ["https://openalex.org/W0"]}

    class Client(OpenAlexClient):
        def __init__(self):
            super().__init__(email="t@example.com")

        def work_by_doi(self, doi):
            return works["W0"]

        def works_by_ids(self, ids, *, search=None):
            return [works[i] for i in ids if i in works]

        def works_citing(self, oa, *, limit, **kw):
            return [w for k, w in works.items() if k != "W0"][:limit]

    seed = _row("10.1/seed", hop=0)
    write_queue(tmp_path, "Rx", [seed], Client(), library_unread=False)
    graph = expand_queue(tmp_path, "Rx", seed.identity, "cites", Client(), settings=MapSettings(neighbors=7))
    assert len(graph["nodes"]) == 8


# --- authors ---------------------------------------------------------------------


def test_node_authors_and_summary_merge_people():
    rows = _queue()
    names, keys = node_authors(rows[0])
    assert names == ["Ada Lovelace", "Bob Babbage"]
    assert keys == ["openalex:A1", "openalex:A2"]
    graph = build_graph(rows, run_id="R1")
    summary = {a["name"]: a for a in graph["authors"]}
    assert summary["Ada Lovelace"]["count"] == 2
    assert summary["Cy Clarke"]["count"] == 2
    assert set(summary["Dee Dodd"]["node_ids"]) == {"doi:10.1/p2", "doi:10.1/p3"}


def test_summary_falls_back_to_plain_names():
    row = _row("10.1/x", hop=0)
    row.biblio["author_records"] = []
    row.biblio["authors"] = ["Jane Q. Public", "", None]
    names, keys = node_authors(row)
    assert names == ["Jane Q. Public"] and keys == ["name:public|j"]
    graph = build_graph([row], run_id="R1")
    assert graph["authors"][0]["name"] == "Jane Q. Public"


def test_author_network_weights_and_kinds():
    rows = _queue()
    graph = build_graph(rows, run_id="R1")
    net = graph["author_network"]
    ids = {n["id"] for n in net["nodes"]}
    assert ids == {"author:openalex:A1", "author:openalex:A2", "author:openalex:A3", "author:openalex:A4"}
    seeds = {n["name"] for n in net["nodes"] if n["seed"]}
    assert seeds == {"Ada Lovelace", "Bob Babbage"}
    pairs = {(e["source"], e["target"]): e for e in net["edges"]}
    ada_bob = pairs[("author:openalex:A1", "author:openalex:A2")]
    assert ada_bob["coauthored"] == 1 and ada_bob["direction"] == "coauthor"
    # Dee and Bob never wrote together; p2 (Dee) cites the seed (Bob) → linked.
    dee_bob = pairs.get(("author:openalex:A2", "author:openalex:A4"))
    assert dee_bob and dee_bob["direction"] == "linked" and dee_bob["linked"] >= 1
    assert max(e["weight"] for e in net["edges"]) == 1
    only = author_network(graph["nodes"], rows, graph["edges"], max_authors=10, links="coauthor")
    assert all(e["coauthored"] for e in only["edges"])


def test_author_network_caps_keep_seed_authors():
    rows = _queue()
    graph = build_graph(rows, run_id="R1")
    net = author_network(graph["nodes"], rows, graph["edges"], max_authors=2)
    assert {n["name"] for n in net["nodes"]} == {"Ada Lovelace", "Bob Babbage"}
    assert net["truncated"] == 2
    rows[2].biblio["author_records"].append({"openalex": "A5", "display_name": "Eve Early"})
    graph = build_graph(rows, run_id="R1")
    strict = author_network(graph["nodes"], rows, graph["edges"], max_authors=10, min_papers=2)
    # min_papers drops one-paper authors (Eve), but never authors of the starting paper (Bob).
    assert {n["name"] for n in strict["nodes"]} == {"Ada Lovelace", "Bob Babbage", "Cy Clarke", "Dee Dodd"}
    assert author_network(graph["nodes"], rows, graph["edges"], max_authors=0)["nodes"] == []


@pytest.mark.parametrize("seed", range(20))
def test_author_network_invariants_on_random_maps(seed):
    rng = random.Random(seed)
    people = [(f"Person {i}", f"A{i}") for i in range(rng.randint(1, 40))]
    rows = [_row("10.1/s", hop=0, authors=rng.sample(people, min(len(people), rng.randint(0, 4))))]
    for i in range(rng.randint(0, 60)):
        parent = rng.choice(rows).identity
        rows.append(
            _row(
                f"10.1/p{i}",
                authors=rng.sample(people, min(len(people), rng.randint(0, 6))),
                links=[{"parent": parent, "direction": rng.choice(["refs", "cites"])}],
            )
        )
    peers = rng.randint(1, 6)
    graph = build_graph(rows, run_id="R1", settings=MapSettings(author_nodes=rng.randint(5, 50), author_peers=peers))
    net = graph["author_network"]
    json.dumps(net)
    ids = [n["id"] for n in net["nodes"]]
    assert len(ids) == len(set(ids))
    seen = set()
    for e in net["edges"]:
        assert e["source"] in ids and e["target"] in ids and e["source"] < e["target"]
        assert (e["source"], e["target"]) not in seen
        seen.add((e["source"], e["target"]))
        assert 0 < e["weight"] <= 1
        assert e["direction"] in ("coauthor", "linked")
        assert (e["coauthored"] > 0) == (e["direction"] == "coauthor")
    seed_authors = {k for k in node_authors(rows[0])[1]}
    drawn = {n["key"] for n in net["nodes"]}
    assert seed_authors <= drawn or len(seed_authors) > len(drawn)
    for n in net["nodes"]:
        assert n["count"] == len(n["node_ids"]) >= 1


# --- following -------------------------------------------------------------------


def _cfg(tmp_path: Path) -> Config:
    return Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")


def test_follow_author_stores_ids_without_network(tmp_path, monkeypatch):
    def no_net(*a, **k):
        raise AssertionError("network")

    monkeypatch.setattr("paperful.snowball.openalex.OpenAlexClient.get", no_net)
    cfg = _cfg(tmp_path)
    person = follow_author(cfg, name="Ada Lovelace", openalex="https://openalex.org/A1", orcid="0000-0002-1825-0097")
    assert person["openalex"] == "A1" and person["orcid"] == "0000-0002-1825-0097"
    again = follow_author(cfg, name="Ada Lovelace", openalex="A1")
    assert again["openalex"] == "A1"
    keys = followed_keys(cfg)
    assert "openalex:A1" in keys and "orcid:0000-0002-1825-0097" in keys
    with pytest.raises(ValueError):
        follow_author(cfg)
    graph = mark_followed(build_graph(_queue(), run_id="R1"), keys)
    assert {a["name"]: a["followed"] for a in graph["authors"]}["Ada Lovelace"] is True
    assert {n["name"]: n["followed"] for n in graph["author_network"]["nodes"]}["Cy Clarke"] is False


# --- queue robustness ------------------------------------------------------------


def test_damaged_queue_lines_are_skipped_and_reported(tmp_path):
    rows = _queue()
    write_queue(tmp_path, "R1", rows, OpenAlexClient(email="t@example.com"), library_unread=False)
    path = tmp_path / "snowball" / "R1" / "candidates.jsonl"
    text = path.read_text(encoding="utf-8").splitlines()
    text.insert(2, '{"run_id": "R1", "truncated')
    text.insert(3, "[1, 2, 3]")
    text.append('{"oops": ')
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    _, loaded, skipped = load_queue_checked(tmp_path, "R1")
    assert len(loaded) == 4 and skipped == 3
    assert len(load_queue(tmp_path, "R1")[1]) == 4
    graph = graph_for_run(tmp_path, "R1")
    assert len(graph["nodes"]) == 4
    assert "3 damaged line" in graph["warnings"][0]


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "q" / "candidates.jsonl"
    atomic_write_text(target, "a\n")
    atomic_write_text(target, "b\n")
    assert target.read_text() == "b\n"
    assert [p.name for p in target.parent.iterdir()] == ["candidates.jsonl"]


# --- GUI routes ------------------------------------------------------------------


@pytest.fixture
def gui(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    path = tmp_path / "config.toml"
    path.write_text(
        f'email = "t@example.com"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    write_queue(cfg.state_dir, "R1", _queue(), OpenAlexClient(email="t@example.com"), library_unread=False)
    return TestClient(create_app(cfg)), cfg, path


def test_graph_route_has_views_authors_and_follow(gui):
    client, cfg, _ = gui
    page = client.get("/discover?tab=queue")
    for marker in ('data-map-view="authors"', 'id="citationSearch"', 'id="citationFit"', 'id="citationExport"',
                   'id="citationAuthorLegend"', 'id="citationLedeAuthors"'):
        assert marker in page.text
    graph = client.get("/discover/graph?run_id=R1").json()
    assert graph["view"]["default_view"] == "papers"
    assert graph["author_network"]["nodes"]
    assert all(a["followed"] is False for a in graph["authors"])
    resp = client.post("/discover/graph/follow", json={"name": "Cy Clarke", "openalex": "A3"})
    assert resp.json()["ok"] is True
    graph = client.get("/discover/graph?run_id=R1").json()
    assert {a["name"]: a["followed"] for a in graph["author_network"]["nodes"]}["Cy Clarke"] is True
    bad = client.post("/discover/graph/follow", json={})
    assert bad.status_code == 400
    junk = client.post("/discover/graph/follow", content=b"not json", headers={"content-type": "application/json"})
    assert junk.status_code == 400


def test_settings_map_save_reset_and_effect(gui):
    import tomllib

    from paperful.snowball.map_settings import for_config

    client, cfg, path = gui
    assert 'id="maps"' in client.get("/settings").text
    client.post(
        "/settings/map",
        data={"color": "category", "size_by": "uniform", "labels": "none", "max_nodes": "20",
              "default_view": "authors", "author_nodes": "7", "author_links": "coauthor", "fit": "1"},
        follow_redirects=False,
    )
    s = for_config(cfg)
    assert (s.color, s.size_by, s.labels, s.default_view, s.author_nodes, s.author_links, s.fit) == (
        "category", "uniform", "none", "authors", 7, "coauthor", True)
    saved = tomllib.loads(path.read_text())["map"]
    assert saved["default_view"] == "authors" and saved["max_nodes"] == 20
    assert for_config(load_config(path)) == s
    graph = client.get("/discover/graph?run_id=R1").json()
    assert graph["view"]["default_view"] == "authors" and graph["view"]["color"] == "category"
    assert all(e["coauthored"] for e in graph["author_network"]["edges"])
    client.post("/settings/map", data={"color": "role"}, follow_redirects=False)
    assert for_config(cfg).fit is False  # unchecked box saves as off
    client.post("/settings/map", data={"reset": "1"}, follow_redirects=False)
    assert for_config(cfg) == DEFAULT


def test_similar_color_follows_map_unless_set():
    seed = _row("10.1/seed", hop=0)
    other = _row("10.1/p1")
    seed.biblio["sim_links"] = [{"peer": other.identity, "score": 0.5}]
    other.biblio["sim_links"] = [{"peer": seed.identity, "score": 0.5}]
    seed.biblio["similar_report"] = {"color": "map", "prior": [], "derivative": []}
    graph = build_graph([seed, other], run_id="S1", settings=MapSettings(color="category"))
    assert graph["layout"] == "similarity" and graph["view"]["color"] == "category"
    seed.biblio["similar_report"]["color"] = "year"
    graph = build_graph([seed, other], run_id="S1", settings=MapSettings(color="category"))
    assert graph["view"]["color"] == "year"
    assert graph["author_network"]["nodes"] == [] or all(n["count"] >= 1 for n in graph["author_network"]["nodes"])


def test_discover_page_survives_damaged_queue_line(gui):
    client, cfg, _ = gui
    path = cfg.state_dir / "snowball" / "R1" / "candidates.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"run_id": "broken\n[1, 2]\n')
    page = client.get("/discover?tab=queue")
    assert page.status_code == 200
    assert "Paper 10.1/p1" in page.text
    graph = client.get("/discover/graph?run_id=R1").json()
    assert "2 damaged line" in graph["warnings"][0]
