"""Offline snowball: fake OpenAlex responses, no Zotero, no network."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from paperful import cli
from paperful.config import load_config
from paperful.snowball import (
    SNOWBALL_TAG,
    SnowballError,
    apply_snowball,
    expand,
    parent_payload,
    proposals,
)

runner = CliRunner()


def _work(
    wid: str,
    doi: str | None,
    title: str,
    *,
    refs: list[str] | None = None,
    year: int = 2020,
    cited: int = 1,
    kind: str = "article",
) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "display_name": title,
        "publication_year": year,
        "type": kind,
        "cited_by_count": cited,
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {
            "landing_page_url": f"https://example.org/{wid}",
            "source": {"display_name": "Nature"},
        },
        "abstract_inverted_index": {"Hello": [0], "world": [1]},
        "referenced_works": [f"https://openalex.org/{r}" for r in (refs or [])],
    }


class FakeOpenAlex:
    def __init__(self, works: dict[str, dict], citing: dict[str, list[dict]]):
        self.works = works
        self.citing = citing
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, params: dict):
        self.calls.append((url, dict(params)))
        if "/works/https://doi.org/" in url:
            doi = url.rsplit("/doi.org/", 1)[-1]
            for work in self.works.values():
                if work.get("doi") and doi in str(work["doi"]):
                    return work
            return None
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            ids = filt.split(":", 1)[1].split("|")
            return {"results": [self.works[i] for i in ids if i in self.works]}
        if filt.startswith("cites:"):
            wid = filt.split(":", 1)[1]
            rows = self.citing.get(wid, [])
            return {"meta": {"count": len(rows)}, "results": rows}
        return None


def _graph():
    works = {
        "W0": _work("W0", "10.1000/seed", "Seed paper", refs=["W1", "W2", "W3"], cited=9),
        "W1": _work("W1", "10.1000/ref-a", "Ref A", refs=["W4"], year=2018),
        "W2": _work("W2", "10.1000/ref-b", "Ref B", refs=[]),
        "W3": _work("W3", None, "No DOI ref", refs=["W4"]),
        "W4": _work("W4", "10.1000/deep", "Depth 2", refs=[]),
        "WC": _work("WC", "10.1000/cite", "Citer", refs=[], cited=4),
    }
    citing = {"W0": [works["WC"], works["W3"]]}
    return FakeOpenAlex(works, citing)


def test_depth_one_keeps_hop_cap_and_skips_doi_less():
    api = _graph()
    plan = expand("https://doi.org/10.1000/seed", api, depth=1, max_per_hop=2, max_nodes=80)
    dois = [n.doi for n in plan.nodes]
    assert plan.seed_doi == "10.1000/seed"
    assert "10.1000/ref-a" in dois
    assert "10.1000/ref-b" in dois
    assert "10.1000/cite" in dois
    assert "10.1000/deep" not in dois
    assert plan.skipped_no_doi == 1
    assert plan.truncated  # three refs, cap 2; citer list is within cap
    ref_calls = [c for c in api.calls if str(c[1].get("filter", "")).startswith("openalex:")]
    assert ref_calls
    assert "W3" not in ref_calls[0][1]["filter"]


def test_direction_references_does_not_ask_for_citations():
    api = _graph()
    plan = expand("10.1000/seed", api, depth=1, direction="references", max_per_hop=25)
    assert all(not str(c[1].get("filter", "")).startswith("cites:") for c in api.calls)
    assert "10.1000/cite" not in plan.by_doi()
    assert "10.1000/ref-a" in plan.by_doi()


def test_hop_cap_still_expands_kept_neighbours():
    api = _graph()
    plan = expand("10.1000/seed", api, depth=2, max_per_hop=1, max_nodes=80, direction="references")
    assert plan.truncated
    assert "10.1000/ref-a" in plan.by_doi()
    assert "10.1000/deep" in plan.by_doi()
    assert "10.1000/ref-b" not in plan.by_doi()


def test_depth_two_stops_at_max_nodes():
    api = _graph()
    plan = expand("10.1000/SEED", api, depth=2, max_nodes=2, max_per_hop=25)
    assert len(plan.nodes) == 2
    assert plan.truncated
    assert plan.nodes[0].depth == 0


def test_missing_seed_and_bad_limits():
    api = _graph()
    try:
        expand("10.1000/missing", api)
        raise AssertionError("expected missing seed")
    except SnowballError as exc:
        assert "no work" in str(exc)
    try:
        expand("10.1000/seed", api, depth=4)
        raise AssertionError("expected depth error")
    except SnowballError:
        pass


def test_payload_and_apply_skip_known_dois():
    api = _graph()
    plan = expand("10.1000/seed", api, depth=1, max_per_hop=25)
    seed = plan.nodes[0]
    payload = parent_payload(seed, ["COL"], seed_doi=plan.seed_doi)
    assert payload["DOI"] == "10.1000/seed"
    assert payload["tags"] == [{"tag": SNOWBALL_TAG}]
    assert payload["abstractNote"] == "Hello world"
    assert payload["creators"][0]["lastName"] == "Lovelace"
    assert "snowball seed=10.1000/seed" in payload["extra"]

    class Backend:
        def __init__(self):
            self.created = []

        def ensure_collection_path(self, path):
            assert path == "snowball/nature"
            return "COL"

        def create_parent(self, data):
            self.created.append(data["DOI"])
            return "NEW"

    known = {"10.1000/ref-a": "HAVE"}
    rows = proposals(plan, known, include_seed=True)
    assert any(r["doi"] == "10.1000/ref-a" and r["status"] == "in_library" for r in rows)
    backend = Backend()
    done = apply_snowball(plan, backend, "snowball/nature", known, include_seed=False)
    assert "10.1000/seed" not in backend.created
    assert "10.1000/ref-a" not in backend.created
    assert "10.1000/cite" in backend.created
    assert done["skipped_in_library"] >= 1
    assert done["created"] == len(backend.created)


def test_config_snowball_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[snowball]\ndepth = 2\nmax_nodes = 10\nmax_per_hop = 3\ndirection = "citations"\n'
    )
    cfg = load_config(path)
    assert cfg.snowball_depth == 2
    assert cfg.snowball_max_nodes == 10
    assert cfg.snowball_max_per_hop == 3
    assert cfg.snowball_direction == "citations"


def test_cli_dry_run_json(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
    )
    api = _graph()

    def _expand(seed, fetch, **kwargs):
        return expand(seed, api, **kwargs)

    monkeypatch.setattr("paperful.snowball.expand", _expand)
    monkeypatch.setattr(cli, "_snowball_library", lambda cfg: (None, {"10.1000/cite": "C1"}, ""))
    result = runner.invoke(
        cli.app,
        ["snowball", "10.1000/seed", "--json", "--config", str(cfg_path), "--no-include-seed"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["summary"]["proposed"] >= 1
    assert payload["summary"]["created"] == 0
    assert all(row["doi"] != "10.1000/seed" for row in payload["items"])
    cite = next(row for row in payload["items"] if row["doi"] == "10.1000/cite")
    assert cite["status"] == "in_library"
    reports = list((tmp_path / "state" / "runs").glob("*-snowball.json"))
    assert len(reports) == 1


def test_cli_apply_needs_collection(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
    )
    result = runner.invoke(
        cli.app, ["snowball", "10.1000/seed", "--apply", "--config", str(cfg_path)]
    )
    assert result.exit_code == 1
    assert "--collection" in result.output
