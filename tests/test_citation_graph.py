"""Citation map roles, edges, and one-hop expand. No live network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.snowball.candidate import Candidate
from paperful.snowball.citation_graph import (
    MAX_NODES,
    NEIGHBOR_CAP,
    REF_FETCH_CAP,
    SCHEMA,
    CitationGraphError,
    build_graph,
    build_triage,
    expand_queue,
    graph_for_run,
    path_between,
    repair_queue_links,
    role_for,
    select_nodes,
)
from paperful.snowball.crawl import doi_candidates
from paperful.snowball.openalex import (
    OpenAlexBudgetExceeded,
    OpenAlexClient,
    OpenAlexError,
)
from paperful.snowball.queue import write_queue


def test_roles_follow_year_and_citations():
    assert role_for(2010, 80, now_year=2026, threshold=50) == "foundational"
    assert role_for(2024, 80, now_year=2026, threshold=50) == "influential"
    assert role_for(2024, 3, now_year=2026, threshold=50) == "emerging"
    assert role_for(2010, 3, now_year=2026, threshold=50) == "other"
    assert role_for(None, 500, now_year=2026, threshold=50) == "other"


def test_map_categories_from_study_designs():
    from paperful.snowball.map_categories import (
        categories_for,
        parse_category_def,
        resolve_catalog,
    )

    catalog = resolve_catalog()
    assert [item.id for item in catalog] == [
        "evidence-synthesis",
        "trials",
        "clinical-trials",
        "observational",
        "case-reports",
        "protocols",
        "narrative-reviews",
        "preprints",
        "books",
        "commentary",
    ]
    assert categories_for(
        {"study_designs": ["meta-analysis", "systematic-review"]}, catalog
    ) == ["evidence-synthesis"]
    assert categories_for(
        {"study_designs": ["randomized-controlled-trial", "clinical-trial"]}, catalog
    ) == ["trials", "clinical-trials"]
    assert categories_for({"study_designs": ["clinical-trial"]}, catalog) == [
        "clinical-trials"
    ]
    assert categories_for({"type": "preprint"}, catalog) == ["preprints"]
    assert categories_for({"type": "review"}, catalog) == ["narrative-reviews"]
    assert categories_for({"type": "book-chapter"}, catalog) == ["books"]
    assert categories_for({"type": "letter"}, catalog) == ["commentary"]
    custom = resolve_catalog(
        enabled=["grey-reports"],
        custom_defs=[
            {
                "id": "grey-reports",
                "label": "Reports",
                "any_types": ["report"],
            }
        ],
    )
    assert categories_for({"type": "report"}, custom) == ["grey-reports"]
    parsed = parse_category_def(
        {"id": "rcts", "label": "RCTs", "any_study_designs": ["rct"]}
    )
    assert parsed.any_study_designs == ("randomized-controlled-trial",)


def test_graph_nodes_carry_categories_and_legend():
    seed = _candidate("10.1000/seed", "W1", "Seed paper", 2024, 12, hop=0, direction="search")
    meta = _candidate(
        "10.1000/meta",
        "W2",
        "A meta-analysis",
        2018,
        200,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        study_designs=["meta-analysis"],
    )
    trial = _candidate(
        "10.1000/rct",
        "W3",
        "An RCT",
        2024,
        5,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        study_designs=["randomized-controlled-trial"],
    )
    graph = build_graph([seed, meta, trial], run_id="R1", now_year=2026)
    assert graph["category_legend"]
    assert {row["id"] for row in graph["category_legend"]} >= {
        "evidence-synthesis",
        "trials",
    }
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id[meta.identity]["study_designs"] == ["meta-analysis"]
    assert by_id[meta.identity]["categories"] == ["evidence-synthesis"]
    assert by_id[meta.identity]["role"] == "foundational"
    assert by_id[trial.identity]["categories"] == ["trials"]
    assert by_id[trial.identity]["role"] == "emerging"


def test_graph_nodes_carry_type_based_categories():
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 9, hop=0, direction="search")
    preprint = _candidate(
        "10.1000/pre",
        "W2",
        "Early draft",
        2024,
        2,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        work_type="preprint",
    )
    chapter = _candidate(
        "10.1000/ch",
        "W3",
        "A book chapter",
        2019,
        10,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        work_type="book-chapter",
    )
    letter = _candidate(
        "10.1000/let",
        "W4",
        "A letter",
        2023,
        1,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        work_type="letter",
    )
    clinical = _candidate(
        "10.1000/ct",
        "W5",
        "A non-RCT trial",
        2022,
        8,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        study_designs=["clinical-trial"],
    )
    graph = build_graph(
        [seed, preprint, chapter, letter, clinical], run_id="Rtypes", now_year=2026
    )
    legend_ids = {row["id"] for row in graph["category_legend"]}
    assert legend_ids >= {"preprints", "books", "commentary", "clinical-trials"}
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id[preprint.identity]["categories"] == ["preprints"]
    assert by_id[chapter.identity]["categories"] == ["books"]
    assert by_id[letter.identity]["categories"] == ["commentary"]
    assert by_id[clinical.identity]["categories"] == ["clinical-trials"]


def test_config_defaults_include_ten_map_categories():
    cfg = Config()
    assert "preprints" in cfg.snowball_map_categories
    assert "clinical-trials" in cfg.snowball_map_categories
    assert "books" in cfg.snowball_map_categories
    assert "commentary" in cfg.snowball_map_categories
    assert "narrative-reviews" in cfg.snowball_map_categories
    assert len(cfg.snowball_map_categories) == 10


def test_build_graph_respects_enabled_map_categories():
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 1, hop=0, direction="search")
    meta = _candidate(
        "10.1000/meta",
        "W2",
        "Meta",
        2012,
        90,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        study_designs=["meta-analysis"],
    )
    graph = build_graph(
        [seed, meta],
        run_id="Rcat",
        now_year=2026,
        map_categories=["trials"],
    )
    assert [row["id"] for row in graph["category_legend"]] == ["trials"]
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id[meta.identity]["categories"] == []
    assert by_id[meta.identity]["study_designs"] == ["meta-analysis"]


def test_graph_for_run_reads_map_categories_from_summary(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 1, hop=0, direction="search")
    meta = _candidate(
        "10.1000/meta",
        "W2",
        "Meta",
        2012,
        90,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        study_designs=["meta-analysis"],
    )
    dest = write_queue(
        cfg.state_dir,
        "Rsum",
        [seed, meta],
        _client({}),
        library_unread=False,
        meta={"map_categories": ["evidence-synthesis"]},
    )
    summary = json.loads((dest / "summary.json").read_text(encoding="utf-8"))
    assert summary["map_categories"] == ["evidence-synthesis"]
    graph = graph_for_run(
        cfg.state_dir,
        "Rsum",
        map_categories=["trials"],  # live cfg must not override the run summary
    )
    assert [row["id"] for row in graph["category_legend"]] == ["evidence-synthesis"]
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id[meta.identity]["categories"] == ["evidence-synthesis"]


def test_annotate_queue_stages_tags_and_keeps_categories(tmp_path: Path):
    """Map annotate writes operator tags and rebuilds categories (no live library)."""
    from paperful.snowball.graph_library import annotate_queue

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.snowball_map_categories = ("evidence-synthesis", "trials")
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 9, hop=0, direction="search")
    meta = _candidate(
        "10.1000/meta",
        "W2",
        "Meta",
        2015,
        120,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
        study_designs=["meta-analysis"],
    )
    write_queue(cfg.state_dir, "Rann", [seed, meta], _client({}), library_unread=False)
    graph = annotate_queue(
        cfg, "Rann", meta.identity, tags=["paperful:frontier"], note="read next"
    )
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id[meta.identity]["categories"] == ["evidence-synthesis"]
    from paperful.snowball.queue import load_queue

    _, rows = load_queue(cfg.state_dir, "Rann")
    row = next(r for r in rows if r.identity == meta.identity)
    assert row.operator is not None
    assert "paperful:frontier" in (row.operator.get("tags") or [])
    assert row.operator.get("note") == "read next"
    assert by_id[meta.identity]["tags"] == ["paperful:frontier"]
    assert by_id[meta.identity]["note"] == "read next"
    assert by_id[meta.identity]["staged"] is True


def test_graph_nodes_carry_library_and_operator_fields(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 9, hop=0, direction="search")
    seed.status = "exists"
    seed.exists_match = {"item_key": "ABCD1234", "doi": "10.1000/seed"}
    new = _candidate("10.1000/new", "W2", "New work", 2024, 3, hop=1, direction="refs")
    new.operator = {
        "tags": ["to-read"],
        "note": "check methods",
        "collection": "Inbox/Snowball",
    }
    out = tmp_path / "out"
    out.mkdir()
    graph = build_graph([seed, new], run_id="Rlib", now_year=2026, out_dir=out)
    by_id = {node["id"]: node for node in graph["nodes"]}
    lib = by_id[seed.identity]
    assert lib["in_library"] is True
    assert lib["item_key"] == "ABCD1234"
    assert lib["has_pdf"] is False
    staged = by_id[new.identity]
    assert staged["in_library"] is False
    assert staged["tags"] == ["to-read"]
    assert staged["note"] == "check methods"
    assert staged["target_collection"] == "Inbox/Snowball"
    assert staged["staged"] is True


def test_discover_graph_meta_and_annotate_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    row = _candidate("10.1000/a", "W1", "Paper A", 2021, 4, hop=0, direction="search")
    write_queue(cfg.state_dir, "Rlib", [row], _client({}), library_unread=False)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(
        "paperful.snowball.graph_library.list_collection_paths",
        lambda *_a, **_k: ["Inbox"],
    )
    monkeypatch.setattr(
        "paperful.snowball.graph_library.list_tag_names",
        lambda *_a, **_k: ["to-read"],
    )
    client = TestClient(create_app(cfg))
    meta = client.get("/discover/graph/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["edit"] == "both"
    assert body["auto_search"] is False
    assert body["remove_mode"] == "trash"
    assert "Inbox" in body["collections"]
    ann = client.post(
        "/discover/graph/annotate",
        json={
            "run_id": "Rlib",
            "node_id": row.identity,
            "tags": ["x"],
            "note": "n",
            "collection": "Inbox",
        },
    )
    assert ann.status_code == 200
    payload = ann.json()
    assert payload["ok"] is True
    assert payload["graph"]["nodes"][0]["staged"] is True


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
    assert graph["thresholds"]["citation_floor"] == 50
    assert graph["triage"]
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


def test_expand_propagates_openalex_budget(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2019, 30, hop=0, direction="doi")
    state = tmp_path / "state"
    write_queue(state, "Rbudget", [seed], _client({}), library_unread=False)

    def getter(path: str, params: dict) -> dict:
        raise OpenAlexBudgetExceeded("daily cap", reset_at="soon")

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    with pytest.raises(OpenAlexBudgetExceeded, match="daily cap"):
        expand_queue(state, "Rbudget", seed.identity, "refs", client)


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


def test_triage_orders_influential_before_library():
    nodes = [
        {"id": "a", "role": "influential", "in_library": False, "seed": False, "cited_by_count": 10},
        {"id": "b", "role": "foundational", "in_library": False, "seed": False, "cited_by_count": 100},
        {"id": "c", "role": "emerging", "in_library": True, "seed": False, "cited_by_count": 2},
    ]
    triage = build_triage(nodes)
    assert triage[0]["id"] == "a"
    assert triage[-1]["id"] == "c"


def test_path_between_finds_a_short_chain():
    edges = [
        {"source": "a", "target": "b", "direction": "refs"},
        {"source": "b", "target": "c", "direction": "refs"},
    ]
    path = path_between(edges, "a", "c")
    assert path is not None and len(path) == 2


def test_library_halo_returns_ghosts_without_queue_rows():
    from paperful.snowball.citation_graph import library_halo

    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 9, hop=0, direction="doi")
    in_lib = _work("W2", "10.1000/lib", "Already mine", 2018, 4)
    outside = _work("W3", "10.1000/out", "Not mine", 2019, 2)
    seed_work = _work("W1", "10.1000/seed", "Seed", 2020, 9, refs=["W2", "W3"])
    client = _client({"W1": seed_work, "W2": in_lib, "W3": outside})
    overlay = library_halo(client, seed, {"10.1000/lib"}, cap=15)
    assert [n["id"] for n in overlay["nodes"]] == ["doi:10.1000/lib"]
    assert all(n.get("ghost") for n in overlay["nodes"])
    assert overlay["edges"]


def test_add_and_remove_library_from_queue(tmp_path: Path, monkeypatch):
    from paperful.snowball.graph_library import add_one_to_library, remove_from_library
    from paperful.snowball.queue import load_queue

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    row = _candidate("10.1000/new", "W1", "New paper", 2024, 3, hop=0, direction="search")
    write_queue(cfg.state_dir, "Radd", [row], _client({}), library_unread=False)

    class Item:
        key = "ITEMKEY1"

    monkeypatch.setattr(
        "paperful.library.get_backend",
        lambda _cfg: object(),
    )
    monkeypatch.setattr(
        "paperful.snowball.ingest.create_new",
        lambda backend, rows, collection, **kwargs: ([Item()], {"created": 1, "failed": 0}),
    )
    result = add_one_to_library(cfg, "Radd", row.identity, collection="Inbox")
    assert result["item_key"] == "ITEMKEY1"
    assert result["auto_search"] is False
    node = next(n for n in result["graph"]["nodes"] if n["id"] == row.identity)
    assert node["in_library"] is True
    assert node["item_key"] == "ITEMKEY1"

    class Backend:
        def __init__(self):
            self.trashed = []

        def trash_item(self, key):
            self.trashed.append(key)

    backend = Backend()
    monkeypatch.setattr("paperful.library.get_backend", lambda _cfg: backend)
    graph = remove_from_library(cfg, "Radd", row.identity)
    assert backend.trashed == ["ITEMKEY1"]
    node = next(n for n in graph["nodes"] if n["id"] == row.identity)
    assert node["in_library"] is False
    _, rows = load_queue(cfg.state_dir, "Radd")
    assert rows[0].exists_match is None
    assert rows[0].status == "new"


def test_select_nodes_prefers_focus_neighbours():
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 1, hop=0, direction="doi")
    near = _candidate(
        "10.1000/near",
        "W2",
        "Near",
        2020,
        50,
        hop=1,
        direction="refs",
        links=[{"parent": seed.identity, "direction": "refs"}],
    )
    far = _candidate("10.1000/far", "W99", "Far", 2020, 1, hop=1, direction="refs")
    rows = [seed, near, far]
    chosen = select_nodes(rows, focus=near.identity, max_nodes=2)
    ids = {row.identity for row in chosen}
    assert seed.identity in ids
    assert near.identity in ids


def test_neighbor_cap_limits_expand(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2019, 30, hop=0, direction="doi")
    state = tmp_path / "state"
    write_queue(state, "Rcap", [seed], _client({}), library_unread=False)
    refs = [f"W{i}" for i in range(2, 2 + REF_FETCH_CAP)]
    children = {
        f"W{i}": _work(f"W{i}", f"10.1000/{i}", f"P{i}", 2000, i)
        for i in range(2, 2 + NEIGHBOR_CAP + 10)
    }
    seed_work = _work("W1", "10.1000/seed", "Seed", 2019, 30, refs=refs[:REF_FETCH_CAP])
    client = _client({"W1": seed_work, **children})
    graph = expand_queue(state, "Rcap", seed.identity, "refs", client, now_year=2026)
    added = [n for n in graph["nodes"] if not n.get("seed")]
    assert len(added) <= NEIGHBOR_CAP


def test_repair_queue_links_writes_graph_links(tmp_path: Path):
    seed = _candidate("10.1000/seed", "W1", "Seed", 2019, 30, hop=0, direction="doi")
    child = _candidate("10.1000/child", "W2", "Child", 2010, 5, hop=1, direction="refs")
    state = tmp_path / "state"
    write_queue(state, "Rrepair", [seed, child], _client({}), library_unread=False)
    cited = _work("W2", "10.1000/child", "Child", 2010, 5)
    seed_work = _work("W1", "10.1000/seed", "Seed", 2019, 30, refs=["W2"])
    client = _client({"W1": seed_work, "W2": cited})
    graph = repair_queue_links(state, "Rrepair", client)
    assert any(
        edge["source"] == seed.identity and edge["target"] == child.identity
        for edge in graph["edges"]
    )


def test_build_graph_marks_watch_and_compare_overlays():
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 5, hop=0, direction="search")
    child = _candidate("10.1000/new", "W2", "New", 2024, 2, hop=1, direction="refs")
    graph = build_graph(
        [seed, child],
        run_id="R1",
        watch_seen={seed.identity},
        compare_ids={seed.identity},
    )
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id[seed.identity]["watch_seen"] is True
    assert by_id[child.identity]["watch_new"] is True
    assert by_id[child.identity]["compare_new"] is True


def test_discover_graph_repair_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    seed = _candidate("10.1000/seed", "W1", "Seed", 2020, 9, hop=0, direction="search")
    write_queue(cfg.state_dir, "Rrepair", [seed], _client({}), library_unread=False)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    monkeypatch.setattr(
        "paperful.snowball.citation_graph.repair_queue_links",
        lambda state_dir, run_id, client, **kwargs: graph_for_run(
            state_dir, run_id, **kwargs
        ),
    )
    client = TestClient(create_app(cfg))
    resp = client.post("/discover/graph/repair", json={"run_id": "Rrepair"})
    assert resp.status_code == 200
    assert resp.json()["schema"] == SCHEMA


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
    assert 'id="citationCategoryFilters"' in page.text
    graph = client.get("/discover/graph", params={"run_id": "Rpage"})
    assert graph.status_code == 200
    body = graph.json()
    assert body["schema"] == SCHEMA
    assert body["nodes"][0]["title"] == "Seed paper"
    assert "category_legend" in body
    assert "categories" in body["nodes"][0]
    assert "study_designs" in body["nodes"][0]
    missing = client.get("/discover/graph", params={"run_id": "no-such-run"})
    assert missing.status_code == 404
    bad = client.get("/discover/graph", params={"run_id": "../etc"})
    assert bad.status_code == 400

    monkeypatch.setattr(
        "paperful.snowball.citation_graph.expand_queue",
        lambda state_dir, run_id, node_id, direction, client, **kw: graph_for_run(state_dir, run_id),
    )
    expand = client.post(
        "/discover/graph/expand",
        json={"run_id": "Rpage", "node_id": seed.identity, "direction": "refs"},
    )
    assert expand.status_code == 200
    assert expand.json()["schema"] == SCHEMA
    keep = client.post(
        "/discover/keep",
        data={"run_id": "Rpage", "doi": "10.1000/seed", "keep": "1", "format": "json"},
        headers={"Accept": "application/json"},
    )
    assert keep.status_code == 200
    body = keep.json()
    assert body["ok"] is True and body["graph"]["schema"] == SCHEMA


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
    study_designs: list[str] | None = None,
    work_type: str | None = None,
) -> Candidate:
    biblio: dict[str, object] = {
        "title": title,
        "year": year,
        "cited_by_count": cited,
        "authors": ["Ada Lovelace"],
    }
    if links:
        biblio["graph_links"] = links
    if study_designs:
        biblio["study_designs"] = list(study_designs)
    if work_type:
        biblio["type"] = work_type
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
