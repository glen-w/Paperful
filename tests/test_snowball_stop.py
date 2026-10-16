"""Saturation stopping rules. No live network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from paperful.snowball.command import SnowballError, SnowballRequest, run_continue, run_doi
from paperful.config import load_config
from paperful.snowball.stop import (
    IterationStat,
    StopParams,
    asymptotic_coverage,
    evaluate,
    marginal_yield,
    parse_stop_rule,
    terminating,
)
from tests.test_snowball import _cfg, _client, _work


def test_marginal_yield_cannot_fire_before_k_plus_one():
    params = StopParams(rule="marginal_yield", eps=0.01, k=2)
    early = [
        IterationStat(1, 10, 0),
        IterationStat(2, 10, 0),
    ]
    assert marginal_yield(early, params).triggered is False
    early.append(IterationStat(3, 40, 0))
    fired = marginal_yield(early, params)
    assert fired.triggered is True
    assert "below 0.01" in fired.rationale


def test_a_kept_hop_does_not_meet_marginal_yield():
    params = StopParams(eps=0.01, k=2)
    history = [IterationStat(iteration, 10, 4) for iteration in range(1, 5)]
    assert marginal_yield(history, params).triggered is False


def test_any_stops_on_budget_before_yield():
    params = StopParams(rule="any", max_screened=5, eps=0.01, k=2)
    history = [IterationStat(1, 5, 5)]
    decisions = evaluate(
        history,
        params,
        frontier_empty=False,
        next_hop=2,
        depth_ceiling=4,
        candidate_room=10,
    )
    chosen = terminating(decisions, "any")
    assert chosen is not None
    assert chosen.rule == "budget"


def test_selected_yield_still_stops_when_the_frontier_is_empty():
    params = StopParams(rule="marginal_yield", k=2, eps=0.01)
    history = [IterationStat(1, 3, 0)]
    decisions = evaluate(
        history,
        params,
        frontier_empty=True,
        next_hop=2,
        depth_ceiling=4,
        candidate_room=10,
    )
    chosen = terminating(decisions, "marginal_yield")
    assert chosen is not None
    assert chosen.rule == "exhaustion"


def test_parse_stop_rule_rejects_recall():
    assert parse_stop_rule("yield") == "marginal_yield"
    with pytest.raises(ValueError):
        parse_stop_rule("estimated_recall")


def test_iterative_crawl_stops_after_one_hop_until_continue(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 5, ["W2"]),
        "W2": _work("W2", "10.1000/hop1", "Hop one", 2019, 4, ["W3"]),
        "W3": _work("W3", "10.1000/hop2", "Hop two", 2018, 3),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    client = _client(works)
    first = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=3, stop_rule="marginal_yield"),
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    rows = [
        json.loads(line)
        for line in (first.run_dir / "candidates.jsonl").read_text().splitlines()
    ]
    assert {row["hop"] for row in rows} <= {0, 1}
    state = json.loads((first.run_dir / "stop.json").read_text())
    assert state["awaiting_labels"] is True
    assert state["depth_ceiling"] == 3
    run_id = first.run_dir.name
    with pytest.raises(SnowballError, match="Keep or Skip"):
        run_continue(cfg, run_id, console=console, client=client, lookup=lambda doi, title: None)

    rewritten = []
    for line in (first.run_dir / "candidates.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["hop"] == 1 and row["status"] == "new":
            row["keep"] = True
        rewritten.append(json.dumps(row))
    (first.run_dir / "candidates.jsonl").write_text("\n".join(rewritten) + "\n")

    second = run_continue(
        cfg, run_id, console=console, client=client, lookup=lambda doi, title: None
    )
    assert second.exit_code == 0
    again = [
        json.loads(line)
        for line in (first.run_dir / "candidates.jsonl").read_text().splitlines()
    ]
    assert any(row["hop"] == 2 and row["ids"]["doi"] == "10.1000/hop2" for row in again)
    waiting = json.loads((first.run_dir / "stop.json").read_text())
    assert waiting["awaiting_labels"] is True
    assert waiting["stopped_by"] is None


def test_skipping_the_hop_stops_on_exhaustion(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 5, ["W2"]),
        "W2": _work("W2", "10.1000/hop1", "Hop one", 2019, 4, ["W3"]),
        "W3": _work("W3", "10.1000/hop2", "Hop two", 2018, 3),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    client = _client(works)
    first = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=3, stop_rule="marginal_yield"),
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    rewritten = []
    for line in (first.run_dir / "candidates.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["hop"] == 1 and row["status"] == "new":
            row["keep"] = False
        rewritten.append(json.dumps(row))
    (first.run_dir / "candidates.jsonl").write_text("\n".join(rewritten) + "\n")
    done = run_continue(
        cfg,
        first.run_dir.name,
        console=console,
        client=client,
        lookup=lambda doi, title: None,
    )
    assert done.summary["stopped_by"] == "exhaustion"
    hops = {
        json.loads(line)["hop"]
        for line in (first.run_dir / "candidates.jsonl").read_text().splitlines()
    }
    assert 2 not in hops


def test_off_still_walks_the_configured_depth(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 5, ["W2"]),
        "W2": _work("W2", "10.1000/hop1", "Hop one", 2019, 4, ["W3"]),
        "W3": _work("W3", "10.1000/hop2", "Hop two", 2018, 3),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    result = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=2),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    hops = {
        json.loads(line)["hop"]
        for line in (result.run_dir / "candidates.jsonl").read_text().splitlines()
    }
    assert 2 in hops
    assert not (result.run_dir / "stop.json").is_file()


def test_asymptotic_coverage_fires_when_keeps_flatten():
    history = [
        IterationStat(1, 20, 8),
        IterationStat(2, 12, 3),
        IterationStat(3, 8, 1),
        IterationStat(4, 6, 0),
    ]
    fired = asymptotic_coverage(history, StopParams(rule="asymptotic_coverage", tau=0.95, min_points=4))
    assert fired.triggered is True
    assert fired.value is not None and fired.value >= 0.95


def test_depth_ceiling_stops_before_another_hop(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 5, ["W2"]),
        "W2": _work("W2", "10.1000/hop1", "Hop one", 2019, 4, ["W3"]),
        "W3": _work("W3", "10.1000/hop2", "Hop two", 2018, 3),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    first = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=1, stop_rule="marginal_yield"),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    rewritten = []
    for line in (first.run_dir / "candidates.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["hop"] == 1 and row["status"] == "new":
            row["keep"] = True
        rewritten.append(json.dumps(row))
    (first.run_dir / "candidates.jsonl").write_text("\n".join(rewritten) + "\n")
    done = run_continue(
        cfg,
        first.run_dir.name,
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    assert done.summary["stopped_by"] == "depth"
    hops = {
        json.loads(line)["hop"]
        for line in (first.run_dir / "candidates.jsonl").read_text().splitlines()
    }
    assert 2 not in hops


def test_continue_auto_keeps_unlabeled(tmp_path: Path):
    works = {
        "W1": _work("W1", "10.1000/seed", "Seed", 2020, 5, ["W2"]),
        "W2": _work("W2", "10.1000/hop1", "Hop one", 2019, 4, ["W3"]),
        "W3": _work("W3", "10.1000/hop2", "Hop two", 2018, 3),
    }
    cfg = _cfg(tmp_path)
    console = Console(highlight=False, width=120)
    first = run_doi(
        cfg,
        ["10.1000/seed"],
        SnowballRequest(depth=3, stop_rule="marginal_yield"),
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
    )
    done = run_continue(
        cfg,
        first.run_dir.name,
        console=console,
        client=_client(works),
        lookup=lambda doi, title: None,
        gate="auto",
    )
    hops = {
        json.loads(line)["hop"]
        for line in (done.run_dir / "candidates.jsonl").read_text().splitlines()
    }
    assert 2 in hops


def test_config_stop_rule_defaults_off_and_loads(tmp_path: Path):
    bare = tmp_path / "bare.toml"
    bare.write_text('email = "me@example.org"\n', encoding="utf-8")
    assert load_config(bare).snowball_stop_rule == "off"
    tuned = tmp_path / "tuned.toml"
    tuned.write_text(
        'email = "me@example.org"\n\n[snowball]\nstop_rule = "budget"\nstop_max_screened = 40\n',
        encoding="utf-8",
    )
    loaded = load_config(tuned)
    assert loaded.snowball_stop_rule == "budget"
    assert loaded.snowball_stop_max_screened == 40
