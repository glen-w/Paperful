"""Grey search watch: URL seen set, interval skip, inbox, apply dry-run."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from paperful import cli
from paperful.search.store import list_runs
from paperful.search.watch import (
    SCHEMA,
    apply_watch,
    inbox_count,
    load_seen,
    run_watch,
    save_watch,
    url_identity,
)
from tests.test_search import FakeSearXNG, StubLib, _cfg, _probe

runner = CliRunner()
console = Console(file=StringIO(), highlight=False, width=120)


def test_url_identity_strips_fragment_and_slash():
    assert url_identity("https://IUCN.org/doc/") == "https://iucn.org/doc"
    assert url_identity("https://iucn.org/doc#page") == "https://iucn.org/doc"


def test_watch_baseline_then_propose(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    save_watch(cfg, "iucn", terms=["Gjerde"], hosts="iucn.org", interval_days=0)
    first = run_watch(
        cfg,
        "iucn",
        console=console,
        getter=FakeSearXNG(),
        probe_getter=_probe,
    )
    assert first.baseline is True
    assert first.proposed == 0
    assert inbox_count(cfg, "iucn") == 0
    assert load_seen(cfg, "iucn")
    body = json.loads(
        (cfg.state_dir / "search" / "watches" / "iucn" / "watch.json").read_text()
    )
    assert body["schema"] == SCHEMA

    extra = {
        "results": [
            {
                "url": "https://portals.iucn.org/library/sites/library/files/documents/2019-new.pdf",
                "title": "New IUCN PDF 2019",
            }
        ]
    }

    class Later(FakeSearXNG):
        def __call__(self, query: str) -> dict:
            data = super().__call__(query)
            data["results"] = list(data["results"]) + extra["results"]
            return data

    second = run_watch(
        cfg,
        "iucn",
        console=console,
        getter=Later(),
        probe_getter=_probe,
        force=True,
    )
    assert second.baseline is False
    assert second.proposed == 1
    assert inbox_count(cfg, "iucn") == 1


def test_watch_interval_skips_without_force(tmp_path: Path):
    cfg = _cfg(tmp_path)
    save_watch(cfg, "iucn", terms=["Gjerde"], hosts="iucn.org", interval_days=7)
    run_watch(
        cfg,
        "iucn",
        console=console,
        getter=FakeSearXNG(),
        probe_getter=_probe,
    )
    skipped = run_watch(
        cfg,
        "iucn",
        console=console,
        getter=FakeSearXNG(),
        probe_getter=_probe,
    )
    assert skipped.skipped is True
    assert skipped.days_left >= 1


def test_watch_apply_dry_run_does_not_create(tmp_path: Path):
    cfg = _cfg(tmp_path)
    lib = StubLib()
    save_watch(cfg, "iucn", terms=["Gjerde"], hosts="iucn.org", interval_days=0)
    run_watch(
        cfg,
        "iucn",
        console=console,
        getter=FakeSearXNG(),
        probe_getter=_probe,
        backend=lib,
    )

    class Later(FakeSearXNG):
        def __call__(self, query: str) -> dict:
            data = super().__call__(query)
            data["results"] = data["results"] + [
                {
                    "url": "https://www.iucn.org/resources/publication/brand-new-2019",
                    "title": "Brand new landing 2019",
                }
            ]
            return data

    run_watch(
        cfg,
        "iucn",
        console=console,
        getter=Later(),
        probe_getter=_probe,
        backend=lib,
        force=True,
    )
    dry = apply_watch(
        cfg,
        "iucn",
        console=console,
        collection="Gjerde tribute/grey",
        apply=False,
        backend=lib,
    )
    assert dry.dry_run is True
    assert lib.created == []
    written = apply_watch(
        cfg,
        "iucn",
        console=console,
        collection="Gjerde tribute/grey",
        apply=True,
        backend=lib,
    )
    assert written.created >= 1
    assert lib.created


def test_list_runs_skips_watches_folder(tmp_path: Path):
    cfg = _cfg(tmp_path)
    save_watch(cfg, "iucn", terms=["Gjerde"], hosts="iucn.org")
    assert list_runs(cfg) == []


def test_cli_search_watch_save_show(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    res = runner.invoke(
        cli.app,
        [
            "search",
            "watch",
            "save",
            "iucn",
            "--query",
            "Gjerde IUCN",
            "--hosts",
            "iucn.org",
            "--interval-days",
            "7",
        ],
    )
    assert res.exit_code == 0, res.output
    show = runner.invoke(cli.app, ["search", "watch", "show", "iucn"])
    assert show.exit_code == 0, show.output
    assert "baseline · not yet" in show.output
    listed = runner.invoke(cli.app, ["search", "watch", "list"])
    assert listed.exit_code == 0, listed.output
    assert "iucn" in listed.output


def test_cli_search_still_runs_query(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    monkeypatch.setattr(
        "paperful.snowball.searxng.search_query",
        lambda _c, _q, **_k: FakeSearXNG()(_q)["results"],
    )
    res = runner.invoke(
        cli.app,
        ["search", "Gjerde", "--no-probe", "--run-id", "still-web", "--format", "json"],
    )
    assert res.exit_code == 0, res.output
    body = json.loads(res.stdout)
    assert body["command"] == "search"
    assert body["summary"]["run_id"] == "still-web"
