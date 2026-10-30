"""ORCID ego co-authorship network: phases, build, metrics, store (offline)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, load_config
from paperful.network.attributes import apply_attributes, seed_attributes
from paperful.network.build import build_ego_graph
from paperful.network.metrics import compute_graph_metrics, gould_fernandez
from paperful.network.phases import BBNJ_PHASES, load_phases, slice_graph
from paperful.network.run import refresh_metrics, run_orcid
from paperful.network.store import GRAPH_KEYS, META_KEYS, SCHEMA, load_run, write_run

ORCID = "0000-0001-9025-7632"
FIXTURES = Path(__file__).parent / "fixtures" / "network" / "gjerde_ego"
runner = CliRunner()


def _cfg(tmp_path: Path) -> Config:
    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.out_dir.mkdir(parents=True)
    return cfg


def _author(name: str, orcid: str, oa: str, country: str = "US", inst_type: str = "education"):
    return {
        "author": {
            "id": f"https://openalex.org/{oa}",
            "display_name": name,
            "orcid": f"https://orcid.org/{orcid}" if orcid else None,
        },
        "institutions": [{"country_code": country, "type": inst_type}],
    }


def _work(wid: str, year: int, authorships: list, topic: str = "Oceanography"):
    return {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "authorships": authorships,
        "topics": [{"subfield": {"display_name": topic}}],
    }


EGO = _author("Kristina M. Gjerde", ORCID, "A1", "US", "nonprofit")
ADA = _author("Ada Ocean", "0000-0002-0000-0001", "A2", "GB", "education")
BEA = _author("Bea Law", "0000-0002-0000-0002", "A3", "KE", "government")
CAM = _author("Cam Science", "0000-0002-0000-0003", "A4", "AU", "education")

WORKS = [
    _work("W1", 2008, [EGO, ADA]),
    _work("W2", 2016, [EGO, ADA, BEA], "Law"),
    _work("W3", 2020, [EGO, CAM]),
]


class FakeOA:
    def author_by_orcid(self, orcid):
        return {
            "id": "https://openalex.org/A1",
            "display_name": "Kristina M. Gjerde",
            "orcid": f"https://orcid.org/{orcid}",
        }

    def works_by_author(self, **kwargs):
        return list(WORKS)


def test_bbnj_preset_and_custom_toml():
    phases = load_phases("bbnj")
    assert [p.id for p in phases] == [p.id for p in BBNJ_PHASES]
    custom = load_phases(FIXTURES / "phases.toml")
    assert [p.id for p in custom] == ["early", "late"]
    assert custom[0].contains(2008)
    assert not custom[0].contains(2016)


def test_unknown_preset_errors():
    with pytest.raises(ValueError, match="Unknown phase preset"):
        load_phases("not-a-preset")


def test_build_ego_graph_from_works():
    graph = build_ego_graph(WORKS, orcid=ORCID, max_alters=10)
    assert graph["schema"] == SCHEMA
    assert graph["ego"]["orcid"] == ORCID
    ids = {n["id"] for n in graph["nodes"]}
    assert any(ORCID in i or n.get("ego") for n, i in ((n, n["id"]) for n in graph["nodes"]))
    ego = next(n for n in graph["nodes"] if n["ego"])
    assert ego["degree"] == 3
    assert ego["frequency"] == 3
    assert len(graph["edges"]) >= 3
    ada = next(n for n in graph["nodes"] if "Ada" in n["display_name"])
    assert ada["country"] == "GB"
    assert ada["sector"] == "academia"


def test_phase_slice_drops_out_of_window_edges():
    graph = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    early, late = load_phases(FIXTURES / "phases.toml")
    sliced = slice_graph(graph, early)
    years = {y for e in sliced["edges"] for y in e["years"]}
    assert years == {2008}
    assert sliced["phase"]["id"] == "early"
    sliced_late = slice_graph(graph, late)
    assert {y for e in sliced_late["edges"] for y in e["years"]} == {2016, 2020}


def test_gould_fernandez_undirected_roles():
    edges = [
        {"a": "ego", "b": "a"},
        {"a": "ego", "b": "b"},
        {"a": "ego", "b": "c"},
    ]
    groups = {"ego": "ngo", "a": "ngo", "b": "academia", "c": "academia"}
    result = gould_fernandez("ego", edges, groups)
    # alter pairs: a-b mixed (boundary), a-c mixed, b-c itinerant (both academia, ego ngo)
    assert result["alter_pairs"] == 3
    assert result["roles"]["itinerant"] == 1
    assert result["roles"]["gatekeeper"] == 2
    assert result["roles"]["representative"] == 2
    assert result["roles"]["liaison"] == 0
    assert result["roles"]["coordinator"] == 0


def test_metrics_degree_without_advanced():
    graph = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    metrics = compute_graph_metrics(graph, partition="none", advanced=False)
    ego = metrics["ego"]
    assert ego["degree"] == 3
    assert ego["betweenness"] is None
    assert metrics["advanced"] is False


@pytest.mark.skipif(
    importlib.util.find_spec("networkx") is None,
    reason="paperful[network] extra missing",
)
def test_metrics_betweenness_and_partition():
    graph = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    graph = apply_attributes(graph, seed_attributes(graph))
    metrics = compute_graph_metrics(graph, partition="region", advanced=True)
    assert metrics["advanced"] is True
    assert metrics["ego"]["betweenness"] is not None
    assert metrics["ego"]["constraint"] is not None
    assert metrics["brokerage"]["roles"]


def test_run_orcid_writes_state(tmp_path: Path):
    cfg = _cfg(tmp_path)
    bundle = run_orcid(
        cfg,
        ORCID,
        phases=str(FIXTURES / "phases.toml"),
        partition="sector",
        max_works=10,
        max_alters=10,
        client=FakeOA(),
        run_id="gjerde-test",
    )
    assert bundle["run_id"] == "gjerde-test"
    dest = Path(bundle["path"])
    assert (dest / "meta.json").is_file()
    assert (dest / "graph.json").is_file()
    assert (dest / "metrics.json").is_file()
    assert (dest / "attributes.csv").is_file()
    assert (dest / "phases" / "early.json").is_file()
    loaded = load_run(cfg, "gjerde-test")
    assert loaded["meta"]["schema"] == SCHEMA
    assert loaded["meta"]["orcid"] == ORCID
    assert loaded["metrics"]["nodes"] >= 2


def test_cli_orcid_and_show(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)

    def fake_cfg(_path=None):
        return cfg

    monkeypatch.setattr("paperful.cli_runtime._cfg", fake_cfg)
    monkeypatch.setattr("paperful.network.run.openalex_client", lambda cfg, client=None: FakeOA())
    result = runner.invoke(
        cli.app,
        [
            "network",
            "orcid",
            ORCID,
            "--phases",
            str(FIXTURES / "phases.toml"),
            "--run-id",
            "cli-gjerde",
            "--max-works",
            "10",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "cli-gjerde" in result.output
    shown = runner.invoke(cli.app, ["network", "show", "cli-gjerde"])
    assert shown.exit_code == 0, shown.output
    listed = runner.invoke(cli.app, ["network", "list", "--format", "json"])
    assert listed.exit_code == 0
    payload = json.loads(listed.output)
    assert payload["schema"] == "paperful.agent.json.v1"
    assert payload["summary"]["runs"] >= 1
    exported = runner.invoke(cli.app, ["network", "export", "cli-gjerde", "--format", "csv"])
    assert exported.exit_code == 0, exported.output


def test_write_run_schema_roundtrip(tmp_path: Path):
    graph = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    dest = tmp_path / "run"
    write_run(
        dest,
        meta={"schema": SCHEMA, "run_id": "x", "orcid": ORCID, "phases": []},
        graph=graph,
        phases={},
        metrics={"ego": {"degree": 3}},
        attributes=seed_attributes(graph),
    )
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema"] == SCHEMA
    assert (dest / "attributes.csv").is_file()


@pytest.mark.e2e_live
def test_live_gjerde_orcid(tmp_path: Path):
    """Opt-in OpenAlex pull for Kristina Gjerde. Artifacts stay under state/ (gitignored)."""
    if os.environ.get("PAPERFUL_E2E") != "1":
        pytest.skip("set PAPERFUL_E2E=1 for the live Gjerde network dogfood")
    cfg = _cfg(tmp_path)
    bundle = run_orcid(
        cfg,
        ORCID,
        phases="bbnj",
        partition="region",
        max_works=80,
        max_alters=40,
        run_id="gjerde-live",
    )
    assert bundle["meta"]["orcid"] == ORCID
    assert bundle["meta"]["nodes"] >= 2
    assert (Path(bundle["path"]) / "graph.json").is_file()


def test_ui_coauthor_network_toml(tmp_path: Path):
    bare = Config()
    assert bare.ui_coauthor_network == "on"
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[ui]\ncoauthor_network = "off"\n',
        encoding="utf-8",
    )
    assert load_config(p).ui_coauthor_network == "off"


def test_schema_v1_keys_frozen_on_run(tmp_path: Path):
    cfg = _cfg(tmp_path)
    bundle = run_orcid(
        cfg,
        ORCID,
        phases=str(FIXTURES / "phases.toml"),
        client=FakeOA(),
        run_id="schema-gjerde",
        max_works=10,
        max_alters=10,
    )
    assert META_KEYS <= bundle["meta"].keys()
    assert GRAPH_KEYS <= bundle["graph"].keys()
    golden = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    assert golden["schema"] == SCHEMA
    assert GRAPH_KEYS <= golden.keys()
    phase = json.loads((FIXTURES / "phases" / "early.json").read_text(encoding="utf-8"))
    assert phase["schema"] == SCHEMA
    assert "graph" in phase and "metrics" in phase


def test_out_dir_override(tmp_path: Path):
    cfg = _cfg(tmp_path)
    dest = tmp_path / "custom-network"
    bundle = run_orcid(
        cfg,
        ORCID,
        phases=str(FIXTURES / "phases.toml"),
        client=FakeOA(),
        run_id="out-dir-run",
        dest=dest,
        max_works=10,
        max_alters=10,
    )
    assert Path(bundle["path"]) == dest
    assert (dest / "graph.json").is_file()
    assert (dest / "phases" / "early.json").is_file()


def test_partition_none_skips_brokerage():
    graph = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    metrics = compute_graph_metrics(graph, partition="none", advanced=False)
    assert metrics["partition"] == "none"
    assert metrics["brokerage"] == {}


def test_attributes_reload_after_csv_edit(tmp_path: Path):
    cfg = _cfg(tmp_path)
    run_orcid(
        cfg,
        ORCID,
        phases=str(FIXTURES / "phases.toml"),
        partition="region",
        client=FakeOA(),
        run_id="attr-gjerde",
        max_works=10,
        max_alters=10,
    )
    csv_path = cfg.state_dir / "network" / "attr-gjerde" / "attributes.csv"
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    cols = lines[1].split(",")
    cols[5] = "Africa"
    lines[1] = ",".join(cols)
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    updated = refresh_metrics(cfg, "attr-gjerde")
    assert any(n.get("region") == "Africa" for n in updated["graph"]["nodes"])


def test_cli_out_dir_and_json(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    monkeypatch.setattr("paperful.network.run.openalex_client", lambda cfg, client=None: FakeOA())
    dest = tmp_path / "cli-out"
    result = runner.invoke(
        cli.app,
        [
            "network",
            "orcid",
            ORCID,
            "--phases",
            str(FIXTURES / "phases.toml"),
            "--out-dir",
            str(dest),
            "--run-id",
            "cli-out",
            "--format",
            "json",
            "--max-works",
            "10",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "paperful.agent.json.v1"
    assert payload["ok"] is True
    assert (dest / "graph.json").is_file()


@pytest.mark.skipif(
    importlib.util.find_spec("matplotlib") is None
    or importlib.util.find_spec("networkx") is None,
    reason="paperful[network] extra missing",
)
def test_figures_write_png(tmp_path: Path):
    from paperful.network.figures import write_phase_figures

    graph = json.loads((FIXTURES / "graph.json").read_text(encoding="utf-8"))
    dest = tmp_path / "figures"
    written = write_phase_figures(dest, {"early": {"graph": graph, "phase": {"label": "Early"}}})
    assert len(written) == 1
    assert written[0].is_file()
    assert written[0].suffix == ".png"
    assert written[0].stat().st_size > 0


@pytest.mark.skipif(
    importlib.util.find_spec("networkx") is None,
    reason="paperful[network] extra missing",
)
def test_cli_export_gexf(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    monkeypatch.setattr("paperful.network.run.openalex_client", lambda cfg, client=None: FakeOA())
    built = runner.invoke(
        cli.app,
        [
            "network",
            "orcid",
            ORCID,
            "--phases",
            str(FIXTURES / "phases.toml"),
            "--run-id",
            "gexf-gjerde",
            "--max-works",
            "10",
        ],
    )
    assert built.exit_code == 0, built.output
    dest = tmp_path / "graph.gexf"
    exported = runner.invoke(
        cli.app,
        ["network", "export", "gexf-gjerde", "--format", "gexf", "--dest", str(dest)],
    )
    assert exported.exit_code == 0, exported.output
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8")
    assert "<gexf" in text.lower() or "gexf" in text.lower()


def test_cli_export_unknown_format(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    monkeypatch.setattr("paperful.network.run.openalex_client", lambda cfg, client=None: FakeOA())
    built = runner.invoke(
        cli.app,
        [
            "network",
            "orcid",
            ORCID,
            "--phases",
            str(FIXTURES / "phases.toml"),
            "--run-id",
            "bad-export",
            "--max-works",
            "10",
        ],
    )
    assert built.exit_code == 0, built.output
    bad = runner.invoke(cli.app, ["network", "export", "bad-export", "--format", "dot"])
    assert bad.exit_code != 0
