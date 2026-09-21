"""Run-config merge, save, and the `all` sequence. Offline — Zotero is stubbed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, load_config
from paperful.run_config import (
    RunConfigError,
    list_profiles,
    resolve_run_config,
    save_profile,
)
from paperful.zot import Collection

runner = CliRunner()


def _write_config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'email = "t@example.org"\n'
        f'out_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        f"{extra}",
        encoding="utf-8",
    )
    return path


def test_table_then_file_then_cli(tmp_path):
    cfg_path = _write_config(
        tmp_path,
        """
[profiles.bbnj]
description = "from table"
collections = ["BBNJ"]
year_from = 2020
try_all = false
""",
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "bbnj.toml").write_text(
        'name = "bbnj"\nyear_from = 2021\ntypes = ["journalArticle"]\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    bare = resolve_run_config(cfg, profile="bbnj", use_run_policy=True)
    assert bare.collections == ["BBNJ"]
    assert bare.year_from == 2021
    assert bare.types == ["journalArticle"]
    assert bare.try_all is False
    assert bare.description == "from table"

    as_all = resolve_run_config(cfg, for_all=True, profile="bbnj")
    assert as_all.try_all is False  # profile explicitly turns the builtin off
    assert as_all.retry_failed is True
    assert as_all.upgrade_linked is True
    assert as_all.apply is True
    assert as_all.steps == ["gaps", "run", "lint", "fix-metadata", "summarize"]

    replaced = resolve_run_config(
        cfg,
        for_all=True,
        profile="bbnj",
        collection=["Other"],
        try_all=True,
    )
    assert replaced.collections == ["Other"]
    assert replaced.library is False
    assert replaced.year_from == 2021
    assert replaced.try_all is True


def test_all_defaults_do_not_apply_to_run_profile(tmp_path):
    cfg_path = _write_config(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "scope.toml").write_text(
        'name = "scope"\ncollections = ["BBNJ"]\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    run_only = resolve_run_config(cfg, profile="scope", use_run_policy=True)
    assert run_only.try_all is False
    assert run_only.retry_failed is False
    assert run_only.apply is False
    assert run_only.steps == []

    implied = resolve_run_config(cfg, for_all=True, profile="scope")
    assert implied.try_all is True
    assert implied.steps[0] == "gaps"


def test_unknown_profile_step_and_years(tmp_path):
    cfg = load_config(_write_config(tmp_path))
    with pytest.raises(RunConfigError, match="Unknown run profile"):
        resolve_run_config(cfg, profile="missing")

    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "bad.toml").write_text(
        'name = "bad"\nsteps = ["gaps", "nope"]\ncollections = ["BBNJ"]\n',
        encoding="utf-8",
    )
    with pytest.raises(RunConfigError, match="Unknown step"):
        resolve_run_config(cfg, for_all=True, profile="bad")

    (tmp_path / "profiles" / "years.toml").write_text(
        'name = "years"\ncollections = ["BBNJ"]\nyear_from = 2026\nyear_to = 2021\n',
        encoding="utf-8",
    )
    with pytest.raises(RunConfigError, match="year-from must be"):
        resolve_run_config(cfg, profile="years")


def test_save_round_trip_and_force(tmp_path):
    cfg = load_config(_write_config(tmp_path))
    body = {
        "description": "BBNJ journal articles",
        "collections": ["BBNJ"],
        "types": ["journalArticle"],
        "year_from": 2021,
        "year_to": 2026,
        "try_all": True,
        "steps": ["gaps", "run"],
        "apply": True,
    }
    path = save_profile(cfg, "bbnj-journal", body, force=False)
    assert path == tmp_path / "profiles" / "bbnj-journal.toml"
    again = resolve_run_config(cfg, for_all=True, profile="bbnj-journal")
    assert again.collections == ["BBNJ"]
    assert again.year_to == 2026
    assert again.steps == ["gaps", "run"]
    assert again.try_all is True
    with pytest.raises(RunConfigError, match="--force"):
        save_profile(cfg, "bbnj-journal", body, force=False)
    save_profile(cfg, "bbnj-journal", body, force=True)
    listed = {row.name: row.source for row in list_profiles(cfg)}
    assert listed["bbnj-journal"] == "file"


def test_file_overlays_same_name_in_config(tmp_path):
    cfg_path = _write_config(
        tmp_path,
        """
[profiles.bbnj]
collections = ["Table"]
description = "table"
""",
    )
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "bbnj.toml").write_text(
        'name = "bbnj"\ncollections = ["File"]\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    resolved = resolve_run_config(cfg, profile="bbnj")
    assert resolved.collections == ["File"]
    assert resolved.description == "table"
    sources = {row.name: row.source for row in list_profiles(cfg)}
    assert sources["bbnj"] == "config.toml+file"


class StubZL:
    def __init__(self):
        self.cols = {"A": Collection("A", "BBNJ", None, "BBNJ", "BBNJ")}

    def ping(self):
        return {"zotero_version": "10.0.1", "api_version": "3", "supports_write": True}

    def collections(self):
        return self.cols

    def resolve_collection(self, spec):
        for col in self.cols.values():
            if spec in (col.key, col.name, col.raw_path):
                return col
        raise LookupError(f"No collection matching '{spec}'")

    def subtree_keys(self, root):
        return [root.key]

    def items_lacking_pdf(self, keys, upgrade_linked=False):
        from tests.conftest import make_item

        return [
            make_item(key="I1", year=2024, collection_paths=["BBNJ"]),
            make_item(key="I2", year=2019, doi=None, collection_paths=["BBNJ"]),
        ]

    def items_in_scope(self, keys):
        from tests.conftest import make_item

        return [
            make_item(key="I1", year=2024, collection_paths=["BBNJ"]),
            make_item(key="I2", year=2019, doi=None, collection_paths=["BBNJ"]),
        ]

    def count_linked_url_only(self, keys):
        return 0


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: StubZL())
    monkeypatch.setattr("paperful.lint.lint_items", lambda *a, **k: [])
    monkeypatch.setattr("paperful.metadata.lint_item", lambda *a, **k: [])
    monkeypatch.setattr("paperful.metadata.propose_patch", lambda *a, **k: None)
    cfg = _write_config(tmp_path)
    return cfg


def test_profile_cli_fills_collection(stubbed):
    (stubbed.parent / "profiles").mkdir()
    (stubbed.parent / "profiles" / "bbnj.toml").write_text(
        'name = "bbnj"\ncollections = ["BBNJ"]\nyear_from = 2023\n',
        encoding="utf-8",
    )
    res = runner.invoke(
        cli.app,
        ["run", "-c", str(stubbed), "--profile", "bbnj", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert "BBNJ" in res.stdout
    assert "years ≥2023" in res.stdout
    assert "1 items without PDF" in res.stdout

    listed = runner.invoke(cli.app, ["profile", "list", "-c", str(stubbed)])
    assert listed.exit_code == 0, listed.stdout
    assert "bbnj" in listed.stdout

    shown = runner.invoke(cli.app, ["profile", "show", "bbnj", "-c", str(stubbed)])
    assert shown.exit_code == 0, shown.stdout
    assert "try_all = true" in shown.stdout
    assert 'collections = ["BBNJ"]' in shown.stdout


def test_profile_save_cli(stubbed):
    res = runner.invoke(
        cli.app,
        [
            "profile",
            "save",
            "bbnj-journal",
            "-c",
            str(stubbed),
            "-C",
            "BBNJ",
            "-T",
            "journalArticle",
            "--year-from",
            "2021",
            "--year-to",
            "2026",
            "--try-all",
            "--description",
            "BBNJ journals",
        ],
    )
    assert res.exit_code == 0, res.stdout
    path = stubbed.parent / "profiles" / "bbnj-journal.toml"
    text = path.read_text(encoding="utf-8")
    assert 'collections = ["BBNJ"]' in text
    assert "try_all = true" in text
    assert "BBNJ journals" in text
    again = runner.invoke(
        cli.app,
        ["profile", "save", "bbnj-journal", "-c", str(stubbed), "-C", "BBNJ"],
    )
    assert again.exit_code == 1
    assert "--force" in again.stdout
    forced = runner.invoke(
        cli.app,
        ["profile", "save", "bbnj-journal", "-c", str(stubbed), "-C", "AO", "--force"],
    )
    assert forced.exit_code == 0, forced.stdout
    assert 'collections = ["AO"]' in path.read_text(encoding="utf-8")


def test_all_dry_run_skips_summarize_and_closes_pack(stubbed, tmp_path):
    res = runner.invoke(
        cli.app,
        ["all", "-c", str(stubbed), "-C", "BBNJ", "--dry-run"],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0, res.stdout
    assert "Skipping summarize" in res.stdout
    assert "all" in res.stdout
    assert not (tmp_path / "state" / "packs" / "current").exists()
    packs = list((tmp_path / "state" / "packs").glob("*.json"))
    assert len(packs) == 1
    pack = json.loads(packs[0].read_text(encoding="utf-8"))
    assert pack["status"] == "closed"
    commands = [step["command"] for step in pack["steps"]]
    assert commands[0] == "gaps"
    assert "lint" in commands
    assert "fix-metadata" in commands
    assert "summarize" not in commands
    assert "run" not in commands  # dry-run exits before a run report


def test_all_stops_on_first_failure(stubbed, monkeypatch, tmp_path):
    order: list[str] = []

    def fail_run(**kwargs):
        order.append("run")
        raise typer.Exit(1)

    def lint_spy(**kwargs):
        order.append("lint")

    real_gaps = cli.gaps

    def gaps_spy(**kwargs):
        order.append("gaps")
        return real_gaps(**kwargs)

    monkeypatch.setattr(cli, "gaps", gaps_spy)
    monkeypatch.setattr(cli, "run", fail_run)
    monkeypatch.setattr(cli, "lint", lint_spy)
    res = runner.invoke(cli.app, ["all", "-c", str(stubbed), "-C", "BBNJ"])
    assert res.exit_code == 1, res.stdout
    assert order == ["gaps", "run"]
    assert not (tmp_path / "state" / "packs" / "current").exists()


def test_all_skips_summarize_when_llm_off(stubbed):
    res = runner.invoke(
        cli.app,
        ["all", "-c", str(stubbed), "-C", "BBNJ", "--steps", "summarize"],
    )
    assert res.exit_code == 0, res.stdout
    assert "llm.enabled is false" in res.stdout

    required = runner.invoke(
        cli.app,
        [
            "all",
            "-c",
            str(stubbed),
            "-C",
            "BBNJ",
            "--steps",
            "summarize",
            "--require-summarize",
        ],
    )
    assert required.exit_code == 1
    assert "require-summarize" in required.stdout


def test_all_joins_open_pack(stubbed, tmp_path):
    opened = runner.invoke(
        cli.app, ["pack", "open", "-c", str(stubbed), "--label", "keep"]
    )
    assert opened.exit_code == 0, opened.stdout
    res = runner.invoke(
        cli.app,
        ["all", "-c", str(stubbed), "-C", "BBNJ", "--dry-run", "--steps", "gaps"],
    )
    assert res.exit_code == 0, res.stdout
    assert "joined" in res.stdout
    current = (tmp_path / "state" / "packs" / "current").read_text(encoding="utf-8").strip()
    pack = json.loads(
        (tmp_path / "state" / "packs" / f"{current}.json").read_text(encoding="utf-8")
    )
    assert pack["status"] == "open"
    assert pack["label"] == "keep"
    assert pack["steps"][0]["command"] == "gaps"


def test_run_profile_does_not_imply_try_all(tmp_path):
    cfg = Config(config_path=tmp_path / "config.toml")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "scope.toml").write_text(
        'name = "scope"\ncollections = ["BBNJ"]\n',
        encoding="utf-8",
    )
    resolved = resolve_run_config(cfg, profile="scope", use_run_policy=True)
    assert resolved.try_all is False
    assert resolved.retry_failed is False
    assert resolved.upgrade_linked is False
