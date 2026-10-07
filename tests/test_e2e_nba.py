"""Hermetic coverage for the NBA all-in E2E harness (no network / Zotero)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from paperful.e2e_nba import (
    DEFAULT_FETCH_PDFS,
    PHASES,
    SCHEMA,
    E2ERunner,
    build_e2e_plan,
    collection_for_topic,
    extract_orcids_from_candidates,
    main,
    normalize_effort,
    pack_slug_for_topic,
    phase_index,
    soft_skip_matrix,
)


def test_e2e_plan_effort_caps():
    low = build_e2e_plan("ocean governance", "low", year_from=2024, year_to=2025)
    assert low.max_candidates == 25
    assert low.depth == 1
    assert low.collection == "e2e/ocean governance"
    assert low.pack_slug == "e2e-ocean-governance"
    high = build_e2e_plan("BBNJ", "high", year_from=2020, year_to=2026)
    assert high.max_candidates == 3000
    assert high.depth == 2
    assert normalize_effort("MED") == "med"
    assert low.fetch_pdfs == DEFAULT_FETCH_PDFS


def test_e2e_plan_query_override():
    plan = build_e2e_plan(
        "eco-surveys",
        "low",
        query='survey AND ("climate policy" OR degrowth)',
        year_from=2020,
        year_to=2026,
    )
    assert plan.topic == "eco-surveys"
    assert plan.collection == "e2e/eco-surveys"
    assert plan.query == 'survey AND ("climate policy" OR degrowth)'
    assert plan.max_orcids == 2


def test_collection_for_topic_nba():
    assert collection_for_topic("NBA") == "e2e/NBA"
    assert pack_slug_for_topic("NBA") == "e2e-nba"


def test_phase_order_stable():
    assert PHASES[0] == "doctor"
    assert PHASES[-1] == "report"
    assert phase_index("snowball_orcid") > phase_index("snowball_search")
    assert phase_index("reachout") < phase_index("handoff_tabs")


def test_extract_orcids_from_author_records(tmp_path: Path):
    queue = tmp_path / "candidates.jsonl"
    rows = [
        {
            "biblio": {
                "author_records": [
                    {"orcid": "https://orcid.org/0000-0002-1825-0097", "display_name": "A"},
                    {"orcid": "", "display_name": "B"},
                ]
            }
        },
        {
            "biblio": {
                "author_records": [
                    {"orcid": "0000-0002-1825-0097"},
                    {"orcid": "0000-0001-2345-6789"},
                ]
            }
        },
    ]
    queue.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    got = extract_orcids_from_candidates(queue, limit=3)
    assert got[0] == "0000-0002-1825-0097"
    assert "0000-0001-2345-6789" in got
    assert len(got) == 2


def test_extract_orcids_empty_queue(tmp_path: Path):
    assert extract_orcids_from_candidates(tmp_path / "missing.jsonl") == []


def test_soft_skip_matrix():
    skips = soft_skip_matrix(
        twenty_ready=False,
        searx_ready=False,
        llm_enabled=False,
        tabs_live=False,
    )
    assert "twenty" in skips
    assert "searxng" in skips
    assert "summarize" in skips
    assert "handoff_tabs" in skips
    assert soft_skip_matrix(
        twenty_ready=True, searx_ready=True, llm_enabled=True, tabs_live=True
    ) == {}


def test_main_refuses_without_env(monkeypatch):
    monkeypatch.delenv("PAPERFUL_E2E", raising=False)
    assert main([]) == 2


def test_report_schema_and_resume(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PAPERFUL_E2E", "1")
    calls: list[list[str]] = []

    def fake_paperful(args, **kwargs):
        calls.append(list(args))
        from subprocess import CompletedProcess

        if args[:2] == ["snowball", "search"]:
            run_dir = tmp_path / "snowball" / "20260101T000000Z"
            run_dir.mkdir(parents=True)
            (run_dir / "candidates.jsonl").write_text(
                json.dumps(
                    {
                        "biblio": {
                            "author_records": [
                                {"orcid": "0000-0002-1825-0097"}
                            ]
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            body = {
                "schema": "paperful.agent.json.v1",
                "command": "snowball search",
                "exit": 0,
                "ok": True,
                "partial": False,
                "summary": {"run_id": "20260101T000000Z", "candidates": 1},
                "items": [],
                "paths": {"run": str(run_dir)},
                "flags": {},
            }
            return CompletedProcess(args, 0, json.dumps(body), "")
        if args[0] == "reachout":
            # script writes --to path
            to = None
            if "--to" in args:
                to = Path(args[args.index("--to") + 1])
                to.write_text("email,title\n", encoding="utf-8")
            return CompletedProcess(args, 0, "{}", "")
        if args[0] == "doctor":
            return CompletedProcess(args, 0, "ok\n", "")
        return CompletedProcess(args, 0, '{"ok": true, "exit": 0, "summary": {}, "paths": {}, "items": [], "flags": {}, "schema": "paperful.agent.json.v1", "command": "x", "partial": false}', "")

    # Point runner state + snowball under tmp
    state = tmp_path / "e2e"
    snowball_root = tmp_path / "snowball"

    class Runner(E2ERunner):
        def _newest_snowball_run(self):
            dirs = [
                p
                for p in snowball_root.iterdir()
                if p.is_dir() and (p / "candidates.jsonl").is_file()
            ]
            return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None

    runner = Runner(
        state_dir=state / "run1",
        run_id="run1",
        from_phase="doctor",
        dry_run_search=False,
        paperful=fake_paperful,
        env={"PAPERFUL_E2E": "1"},
    )
    # Redirect snowball path lookups
    monkeypatch.setattr(runner, "root", tmp_path)
    (tmp_path / "state" / "snowball").mkdir(parents=True, exist_ok=True)
    # fake writes under tmp_path/snowball — also mirror under state/snowball for artifacts
    def paperful_with_state(args, **kwargs):
        proc = fake_paperful(args, **kwargs)
        if args[:2] == ["snowball", "search"]:
            src = tmp_path / "snowball" / "20260101T000000Z"
            dest = tmp_path / "state" / "snowball" / "20260101T000000Z"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "candidates.jsonl").write_text(
                (src / "candidates.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        return proc

    runner._paperful = paperful_with_state
    code = runner.run()
    assert code == 0
    snowball_search = [
        c for c in calls if len(c) >= 2 and c[0] == "snowball" and c[1] == "search"
    ]
    assert snowball_search
    assert "--gate" in snowball_search[0]
    assert snowball_search[0][snowball_search[0].index("--gate") + 1] == "auto"
    assert "--fetch-pdfs" in snowball_search[0]
    assert (
        snowball_search[0][snowball_search[0].index("--fetch-pdfs") + 1]
        == DEFAULT_FETCH_PDFS
    )
    report = json.loads((state / "run1" / "report.json").read_text(encoding="utf-8"))
    assert report["schema"] == SCHEMA
    assert report["ok"] is True
    names = [p["name"] for p in report["phases"]]
    assert "doctor" in names
    assert "snowball_search" in names
    assert "report" in names


@pytest.mark.e2e_live
def test_e2e_live_opt_in():
    if os.environ.get("PAPERFUL_E2E") != "1":
        pytest.skip("set PAPERFUL_E2E=1 for the live all-in E2E")
    code = main([])
    assert code == 0
