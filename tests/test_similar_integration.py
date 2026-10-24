"""Similar map runs flowing through the rest of Paperful (apply, digest, export, GUI routes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from paperful.config import Config, load_config
from paperful.snowball.openalex import OpenAlexClient
from paperful.snowball.queue import load_queue
from paperful.snowball.similar_explore import start_similar_explore


def _u(oa: str) -> str:
    return f"https://openalex.org/{oa}"


def _work(oa: str, refs: list[str], *, year: int = 2020, cited: int = 1, doi: bool = True) -> dict:
    return {
        "id": _u(oa),
        "doi": f"https://doi.org/10.1000/{oa.lower()}" if doi else None,
        "display_name": f"Paper {oa}",
        "publication_year": year,
        "type": "article",
        "cited_by_count": cited,
        "referenced_works": [_u(r) for r in refs],
        "authorships": [{"author": {"display_name": f"Author {oa}"}}],
    }


WORKS = {
    "S": _work("S", ["R1", "R2", "R3"], cited=90),
    "R1": _work("R1", ["Q1"], year=2001, cited=400),
    "R2": _work("R2", ["Q1", "R1"], year=2003, cited=300),
    "R3": _work("R3", ["Q2"], year=2005, cited=200),
    "A": _work("A", ["R1", "R2", "R9"], cited=40),
    "B": _work("B", ["R1", "R2"], cited=30),
    "C1": _work("C1", ["S", "X", "A"], year=2022, cited=5),
    "C2": _work("C2", ["S", "X", "B"], year=2023, cited=4),
    "X": _work("X", ["Q9"], year=2015, cited=70),
}


class FakeClient(OpenAlexClient):
    def __init__(self) -> None:
        super().__init__(email="t@example.com", getter=self._no_http)

    @staticmethod
    def _no_http(path, query):
        raise AssertionError(f"unexpected HTTP {path}")

    def work_by_doi(self, doi):
        oa = doi.rsplit("/", 1)[-1].upper()
        return WORKS.get(oa)

    def works_by_ids(self, ids, *, search=None):
        return [WORKS[i.rsplit("/", 1)[-1]] for i in ids if i.rsplit("/", 1)[-1] in WORKS]

    def works_citing(self, openalex_id, *, limit, **kwargs):
        sid = openalex_id.rsplit("/", 1)[-1]
        return [w for oa, w in WORKS.items() if oa != sid and _u(sid) in w["referenced_works"]][:limit]


def _cfg(tmp_path: Path) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n[snowball]\nenabled = true\n',
        encoding="utf-8",
    )
    return load_config(path)


@pytest.fixture
def similar_run(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)
    run_id, graph = start_similar_explore(cfg, FakeClient(), query="10.1000/s")
    return cfg, run_id, graph


class _Lib:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.notes: list[tuple] = []

    def ensure_collection_path(self, path: str) -> str:
        return "COL1"

    def create_parent(self, data: dict) -> str:
        self.created.append(data)
        return f"ITEM{len(self.created)}"

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        self.notes.append((item_key, html, tag))
        return "NOTE"


def _keep(cfg: Config, run_id: str, dois: set[str]) -> None:
    dest, rows = load_queue(cfg.state_dir, run_id)
    lines = []
    for row in rows:
        data = row.to_dict()
        data["keep"] = (row.ids.get("doi") or "") in dois
        lines.append(json.dumps(data))
    (dest / "candidates.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_snowball_apply_creates_clean_items_from_similar_run(similar_run):
    from paperful.snowball.command import SnowballRequest, run_apply

    cfg, run_id, graph = similar_run
    _keep(cfg, run_id, {"10.1000/a", "10.1000/x"})
    lib = _Lib()
    result = run_apply(
        cfg,
        run_id,
        SnowballRequest(collection="Inbox/Similar"),
        console=Console(highlight=False, width=160),
        lookup=lambda doi, title: None,
        backend=lib,
    )
    assert result.exit_code == 0
    assert {item["DOI"] for item in lib.created} == {"10.1000/a", "10.1000/x"}
    for item in lib.created:
        blob = json.dumps(item)
        # Map internals never leak into library records.
        for key in ("sim_links", "similar_report", "origin_path", "similarity"):
            assert key not in blob
        assert item.get("title")


def test_digest_briefing_and_bibtex_on_similar_run(similar_run):
    from paperful.pack_bib import export_pack_text
    from paperful.snowball.briefing import write_run_briefing
    from paperful.snowball.digest import write_run_digest

    cfg, run_id, graph = similar_run
    digest = write_run_digest(cfg, run_id)
    assert run_id in Path(digest.path).read_text(encoding="utf-8")
    briefing = write_run_briefing(cfg, run_id)
    assert Path(briefing.path).is_file()
    text, _jsonl, count = export_pack_text(cfg.state_dir / "snowball" / run_id, "bibtex")
    assert count == len(graph["nodes"])
    assert "10.1000/x" in text.lower()


def test_map_library_actions_keep_similarity_layout(similar_run, monkeypatch):
    from paperful.snowball.citation_graph import CitationGraphError, repair_queue_links
    from paperful.snowball.graph_library import add_one_to_library, annotate_queue, remove_from_library

    cfg, run_id, graph = similar_run
    node = next(n for n in graph["nodes"] if n["id"] == "doi:10.1000/x")

    class Item:
        key = "ITEMX"

    class LiveLib:
        def __init__(self):
            self.notes: list[tuple] = []

        def create_or_update_note(self, key, body, tag):
            self.notes.append((key, body, tag))

        def add_tags(self, key, tags):
            pass

        def ensure_collection_path(self, path):
            return "COL"

        def add_to_collection(self, key, coll):
            pass

    live = LiveLib()
    monkeypatch.setattr("paperful.library.get_backend", lambda _cfg: live)
    monkeypatch.setattr(
        "paperful.snowball.ingest.create_new",
        lambda backend, rows, collection, **kwargs: ([Item()], {"created": 1, "failed": 0}),
    )
    added = add_one_to_library(cfg, run_id, node["id"], collection="Inbox")
    after = added["graph"]
    assert after["layout"] == "similarity"
    assert next(n for n in after["nodes"] if n["id"] == node["id"])["in_library"] is True
    assert after["edges"] == graph["edges"]
    assert after["similar"]["prior"] == graph["similar"]["prior"]

    annotated = annotate_queue(cfg, run_id, node["id"], tags=["to-read"], note="looks close", collection="")
    assert annotated["layout"] == "similarity"
    assert next(n for n in annotated["nodes"] if n["id"] == node["id"])["tags"] == ["to-read"]

    class Backend:
        trashed: list[str] = []

        def trash_item(self, key):
            self.trashed.append(key)

    monkeypatch.setattr("paperful.library.get_backend", lambda _cfg: Backend())
    removed = remove_from_library(cfg, run_id, node["id"])
    assert removed["layout"] == "similarity"

    with pytest.raises(CitationGraphError, match="citation maps"):
        repair_queue_links(cfg.state_dir, run_id, FakeClient())


# --- GUI routes ------------------------------------------------------------------


@pytest.fixture
def gui(similar_run, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app

    cfg, run_id, graph = similar_run
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    return TestClient(create_app(cfg)), cfg, run_id, graph


def test_queue_tab_and_graph_routes(gui):
    client, cfg, run_id, graph = gui
    page = client.get("/discover?tab=queue")
    assert page.status_code == 200
    assert run_id in page.text
    assert "citationLedeSimilar" in page.text
    assert "Paper X" in page.text  # candidate list shows similar rows

    data = client.get(f"/discover/graph?run_id={run_id}").json()
    assert data["layout"] == "similarity"
    assert {n["id"] for n in data["nodes"]} == {n["id"] for n in graph["nodes"]}

    # Overlays from the citation map still work on a Similar map.
    over = client.get(f"/discover/graph?run_id={run_id}&compare_run={run_id}&watch_name=none").json()
    assert all(n["compare_new"] is False for n in over["nodes"])
    assert all("watch_new" in n for n in over["nodes"])

    assert client.get("/discover/graph/meta").status_code == 200


def test_keep_json_and_expand_refusal(gui):
    client, cfg, run_id, graph = gui
    resp = client.post(
        "/discover/keep",
        data={"run_id": run_id, "doi": "10.1000/x", "keep": "1", "format": "json"},
    )
    body = resp.json()
    assert body["ok"] is True and body["graph"]["layout"] == "similarity"
    _, rows = load_queue(cfg.state_dir, run_id)
    assert next(r for r in rows if r.ids.get("doi") == "10.1000/x").keep is True

    expand = client.post(
        "/discover/graph/expand",
        json={"run_id": run_id, "node_id": "doi:10.1000/x", "direction": "both"},
    )
    assert expand.status_code == 400
    assert "citation maps" in expand.json()["error"]
    repair = client.post("/discover/graph/repair", json={"run_id": run_id})
    assert repair.status_code == 400


def test_annotate_route_on_similar_map(gui):
    client, cfg, run_id, graph = gui
    resp = client.post(
        "/discover/graph/annotate",
        json={"run_id": run_id, "node_id": "doi:10.1000/x", "tags": "a, b", "note": "n"},
    )
    assert resp.status_code == 200
    assert resp.json()["graph"]["layout"] == "similarity"


def test_explore_route_end_to_end_with_overrides(gui, monkeypatch):
    client, cfg, run_id, graph = gui
    monkeypatch.setattr(
        "paperful.snowball.similar_explore.similar_client",
        lambda _cfg, settings, client=None: (FakeClient(), []),
    )
    resp = client.post(
        "/discover/explore",
        data={"query": "10.1000/s", "map": "similar", "nodes": "5", "year_from": "2010", "year_to": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and "tab=queue" in resp.headers["location"]
    page = client.get("/discover?tab=queue")
    new_run = page.text.split('data-run-id="')[1].split('"')[0]
    assert new_run != run_id and new_run.startswith("similar-")
    data = client.get(f"/discover/graph?run_id={new_run}").json()
    assert data["similar"]["settings"]["nodes"] == 5
    assert data["similar"]["settings"]["year_from"] == 2010
    assert all((n["year"] or 0) >= 2010 for n in data["nodes"] if not n["seed"])


def test_explore_route_error_is_shown_in_full(gui, monkeypatch):
    client, cfg, run_id, graph = gui
    from paperful.snowball.citation_graph import CitationGraphError

    long = "Not enough shared citations. " + "x" * 300 + " END"

    def boom(*a, **k):
        raise CitationGraphError(long)

    monkeypatch.setattr("paperful.snowball.similar_explore.start_similar_explore", boom)
    resp = client.post("/discover/explore", data={"query": "10.1000/s", "map": "similar"})
    assert resp.status_code == 200
    assert "Not enough shared citations" in resp.text
    assert "END" in resp.text


def test_citation_explore_after_similar_is_citation_layout(gui, monkeypatch):
    from paperful.snowball.citation_graph import build_graph, write_graph_file

    client, cfg, run_id, graph = gui

    def fake_expand(state_dir, run, node_id, direction, oa, **kwargs):
        _, rows = load_queue(state_dir, run)
        g = build_graph(rows, run_id=run, focus=node_id)
        write_graph_file(Path(state_dir) / "snowball" / run, g)
        return g

    monkeypatch.setattr("paperful.snowball.explore.expand_queue", fake_expand)
    monkeypatch.setattr("paperful.snowball.command._openalex_client", lambda _c: FakeClient())
    resp = client.post("/discover/explore", data={"query": "10.1000/s", "map": "citation"}, follow_redirects=False)
    assert resp.status_code == 303
    page = client.get("/discover?tab=queue")
    new_run = page.text.split('data-run-id="')[1].split('"')[0]
    assert new_run.startswith("explore-")
    assert client.get(f"/discover/graph?run_id={new_run}").json()["layout"] == "citation"


# --- review fixes ----------------------------------------------------------------


def test_explore_overrides_respect_config_caps(tmp_path):
    from starlette.datastructures import FormData

    from paperful.snowball.similar_settings import from_mapping
    from paperful.ui.discover_routes import similar_overrides

    cfg = Config(out_dir=tmp_path / "o", state_dir=tmp_path / "s")
    cfg.similar_map = from_mapping({"pool": "standard", "ref_cap": 33, "year_from": 2000})
    form = FormData([("pool", "standard"), ("nodes", "9"), ("year_from", ""), ("year_to", "")])
    over = similar_overrides(cfg, form)
    assert "pool" not in over  # unchanged depth keeps ref_cap = 33
    merged = cfg.similar_map.merged(over)
    assert merged.ref_cap == 33 and merged.nodes == 9
    assert merged.year_from is None  # cleared for this map
    form2 = FormData([("pool", "large")])
    assert cfg.similar_map.merged(similar_overrides(cfg, form2)).ref_cap == 400


def test_settings_save_keeps_file_caps_consistent(tmp_path, monkeypatch):
    import tomllib

    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app
    from paperful.snowball.similar_settings import for_config

    path = tmp_path / "config.toml"
    path.write_text(
        'email = "t@example.com"\n[similar_map]\npool = "standard"\nref_cap = 33\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    cfg.state_dir = tmp_path / "state"
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    client = TestClient(create_app(cfg))
    base = {"nodes": "40", "pool": "standard", "source": "auto", "color": "role"}
    client.post("/settings/similar-map", data=base, follow_redirects=False)
    assert for_config(cfg).ref_cap == 33
    assert tomllib.loads(path.read_text())["similar_map"]["ref_cap"] == 33
    client.post("/settings/similar-map", data={**base, "pool": "small"}, follow_redirects=False)
    assert for_config(cfg).ref_cap == 100
    assert tomllib.loads(path.read_text())["similar_map"]["ref_cap"] == 100
    assert for_config(load_config(path)) == for_config(cfg)


def test_picker_carries_cleared_years(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops
    from paperful.serve import create_app
    from paperful.snowball.explore import ExploreAmbiguous, ExplorePick
    from paperful.snowball.similar_settings import from_mapping

    cfg = Config(out_dir=tmp_path / "o", state_dir=tmp_path / "s")
    cfg.similar_map = from_mapping({"year_from": 2000})
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})

    def ambiguous(*a, **k):
        raise ExploreAmbiguous([ExplorePick("openalex:W1", "One", 2020, 1, ""), ExplorePick("openalex:W2", "Two", 2021, 1, "")])

    monkeypatch.setattr("paperful.snowball.similar_explore.start_similar_explore", ambiguous)
    page = TestClient(create_app(cfg)).post(
        "/discover/explore", data={"query": "some title", "map": "similar", "year_from": ""}
    )
    assert 'name="year_from" value=""' in page.text
    assert 'name="map" value="similar"' in page.text


def test_run_ids_never_collide(tmp_path):
    from paperful.snowball.explore import new_run_id

    ids = [new_run_id(tmp_path, "similar") for _ in range(5)]
    assert len(set(ids)) == 5
    assert all((tmp_path / "snowball" / i).is_dir() for i in ids)


def test_failed_map_leaves_no_empty_run(tmp_path, monkeypatch):
    from paperful.snowball.citation_graph import CitationGraphError
    from paperful.snowball.similar_settings import from_mapping

    cfg = _cfg(tmp_path)
    cfg.similar_map = from_mapping({"hide_in_library": True})

    def mark(rows, finder, **kwargs):
        for row in rows:
            row.status = "exists"

    monkeypatch.setattr("paperful.snowball.command.get_backend", lambda _c: None)
    monkeypatch.setattr("paperful.snowball.command._library_lookup", lambda *a, **k: None)
    monkeypatch.setattr("paperful.snowball.command._mark_exists", mark)
    with pytest.raises(CitationGraphError):
        start_similar_explore(cfg, FakeClient(), query="10.1000/s")
    root = cfg.state_dir / "snowball"
    assert not root.exists() or not any(root.iterdir())
