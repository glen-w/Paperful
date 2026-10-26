"""Snowball publication-year trends (OpenAlex group_by)."""

from __future__ import annotations

import json

from rich.console import Console
from typer.testing import CliRunner

from paperful.cli import app
from paperful.snowball.openalex import OpenAlexClient
from paperful.snowball.trends import trends_for_scope

runner = CliRunner()
console = Console(record=True)


def test_counts_by_year_parses_group_by():
    def getter(path: str, params: dict) -> dict:
        assert path == "/works"
        assert params.get("group_by") == "publication_year"
        assert params.get("search") == "ocean treaty"
        return {
            "group_by": [
                {"key": 2022, "count": 12},
                {"key": 2023, "count": 30},
            ]
        }

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    rows = client.counts_by_year("ocean treaty")
    assert rows == [(2022, 12), (2023, 30)]


def test_trends_for_scope(cfg):
    def getter(path: str, params: dict) -> dict:
        return {"group_by": [{"key": 2024, "count": 5}]}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    report = trends_for_scope(cfg, query="bbnj", client=client)
    assert report.total == 5
    assert report.years[0].year == 2024


def test_snowball_trends_cli_json(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
    )

    def getter(path: str, params: dict) -> dict:
        return {"group_by": [{"key": 2020, "count": 2}, {"key": 2021, "count": 3}]}

    def patched(cfg, **kwargs):
        return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)

    monkeypatch.setattr("paperful.snowball.trends._openalex_client", patched)

    result = runner.invoke(
        app,
        ["snowball", "trends", "marine", "-c", str(cfg_file), "--format", "json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["total"] == 5
    assert payload["summary"]["years"][0]["year"] == 2020


def test_run_trends_error_and_empty_years(cfg, monkeypatch):
    from paperful.snowball.command import SnowballError
    from paperful.snowball.trends import TrendsReport, YearCount
    from paperful.snowball.trends_cmd import run_trends

    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _p: cfg)
    monkeypatch.setattr("paperful.cli_runtime._agent_json", lambda _fmt: False)
    printed = []
    monkeypatch.setattr(
        "paperful.cli_runtime._emit_agent",
        lambda payload, json_out=False, human=None: printed.append(
            (payload, human and human())
        ),
    )

    def boom(*_a, **_k):
        raise SnowballError("Pass a search query or --profile.")

    monkeypatch.setattr("paperful.snowball.trends_cmd.trends_for_scope", boom)
    run_trends(
        console,
        query=None,
        profile=None,
        year_from=None,
        year_to=None,
        config=None,
        fmt="text",
    )
    assert printed[0][0]["summary"]["error"]

    printed.clear()
    monkeypatch.setattr(
        "paperful.snowball.trends_cmd.trends_for_scope",
        lambda *_a, **_k: TrendsReport(query="x", total=0, years=(), profile="p1"),
    )
    run_trends(
        console,
        query="x",
        profile=None,
        year_from=None,
        year_to=None,
        config=None,
        fmt="text",
    )
    assert printed

    printed.clear()
    monkeypatch.setattr(
        "paperful.snowball.trends_cmd.trends_for_scope",
        lambda *_a, **_k: TrendsReport(
            query="x", total=3, years=(YearCount(2024, 3),), profile=None
        ),
    )
    run_trends(
        console,
        query="x",
        profile=None,
        year_from=None,
        year_to=None,
        config=None,
        fmt="text",
    )
    assert printed
