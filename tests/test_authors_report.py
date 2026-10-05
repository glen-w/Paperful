"""Authors/orgs frequency report and field author-pack seed. No network."""

from __future__ import annotations

import json
import types

from typer.testing import CliRunner

from paperful import cli
from paperful.authors_report import (
    SCHEMA,
    harvest,
    seed_proposed_pack,
    write_report,
)
from paperful.snowball.authors import (
    AuthorPack,
    PackAuthor,
    load_pack_file,
    pack_path,
    write_pack,
)
from paperful.zot import corporate_creator_names, item_from_json
from tests.conftest import make_item

runner = CliRunner()


def test_corporate_creator_names_skips_people():
    creators = [
        {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
        {"creatorType": "author", "name": "FAO"},
        {"creatorType": "author", "name": "UNESCO", "lastName": ""},
        {"creatorType": "editor", "firstName": "Bob", "lastName": "Smith"},
    ]
    assert corporate_creator_names(creators) == ["FAO", "UNESCO"]


def test_item_from_json_sets_corporate_creators():
    cols: dict = {}
    raw = {
        "key": "A1",
        "data": {
            "itemType": "report",
            "title": "State of World Fisheries",
            "creators": [
                {"creatorType": "author", "name": "FAO"},
                {"creatorType": "author", "firstName": "Jane", "lastName": "Doe"},
            ],
            "collections": [],
        },
        "meta": {},
    }
    item = item_from_json(raw, cols, None)
    assert item.corporate_creators == ["FAO"]
    assert "FAO" in item.creator_surnames
    assert "Doe" in item.creator_surnames


def test_harvest_splits_people_and_orgs_once_per_item():
    items = [
        make_item(
            key="A",
            creator_surnames=["Lovelace", "FAO"],
            corporate_creators=["FAO"],
            first_author="Ada Lovelace",
        ),
        make_item(
            key="B",
            creator_surnames=["Lovelace", "Miller"],
            corporate_creators=[],
            first_author="Ada Lovelace",
        ),
        make_item(
            key="C",
            creator_surnames=["FAO"],
            corporate_creators=["FAO"],
            first_author="FAO",
        ),
        make_item(
            key="D",
            creator_surnames=["Miller"],
            first_author="Miller",
        ),
    ]
    report = harvest(items, min_count=2)
    authors = {row.key: row for row in report.authors}
    orgs = {row.key: row for row in report.orgs}
    assert authors["lovelace|a"].count == 2
    assert authors["lovelace|a"].name == "Ada Lovelace"
    assert authors["miller|m"].count == 2
    assert "fao|" not in authors and "fao" not in authors
    assert orgs["fao"].count == 2
    assert orgs["fao"].name == "FAO"
    # Below min_count people are dropped.
    assert harvest(items, min_count=3).authors == []


def test_seed_proposed_pack_preserves_listing_and_sets_frequency(cfg):
    existing = AuthorPack(
        name="bbnj",
        collection="BBNJ",
        status="proposed",
        authors=[
            PackAuthor(
                name="Ada Lovelace",
                fingerprint="lovelace|a",
                listing_url="https://lovelace.github.io/papers/",
                base_host="lovelace.github.io",
                source="twenty",
                frequency=1,
            )
        ],
    )
    write_pack(pack_path(cfg, "bbnj", promoted=False), existing)
    from paperful.authors_report import FreqRow

    path = seed_proposed_pack(
        cfg,
        collection="BBNJ",
        authors=[
            FreqRow(name="Ada Lovelace", key="lovelace|a", count=5, kind="author"),
            FreqRow(name="Grace Hopper", key="hopper|g", count=3, kind="author"),
        ],
        max_authors=15,
    )
    assert path is not None
    pack = load_pack_file(path)
    assert pack is not None
    by_fp = {a.fingerprint: a for a in pack.authors}
    assert by_fp["lovelace|a"].frequency == 5
    assert by_fp["lovelace|a"].listing_url.endswith("/papers/")
    assert by_fp["lovelace|a"].source == "twenty"
    assert by_fp["hopper|g"].source == "corpus"
    assert by_fp["hopper|g"].frequency == 3


def test_write_report_schema(cfg):
    items = [
        make_item(
            key="A",
            creator_surnames=["Lovelace"],
            first_author="Ada Lovelace",
        ),
        make_item(
            key="B",
            creator_surnames=["Lovelace", "FAO"],
            corporate_creators=["FAO"],
            first_author="Ada Lovelace",
        ),
        make_item(
            key="C",
            creator_surnames=["FAO"],
            corporate_creators=["FAO"],
            first_author="FAO",
        ),
    ]
    report = harvest(items, min_count=2)
    path = write_report(
        cfg,
        "bbnj",
        scope="BBNJ",
        report=report,
        min_count=2,
        n_items=3,
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["schema"] == SCHEMA
    assert body["items"] == 3
    assert body["authors"][0]["fingerprint"] == "lovelace|a"
    assert body["orgs"][0]["name"] == "FAO"


def test_authors_cli_dry_run_and_apply(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )
    items = [
        make_item(
            key="A",
            creator_surnames=["Lovelace"],
            first_author="Ada Lovelace",
            collection_paths=["BBNJ"],
        ),
        make_item(
            key="B",
            creator_surnames=["Lovelace", "FAO"],
            corporate_creators=["FAO"],
            first_author="Ada Lovelace",
            collection_paths=["BBNJ"],
        ),
        make_item(
            key="C",
            creator_surnames=["FAO"],
            corporate_creators=["FAO"],
            first_author="FAO",
            collection_paths=["BBNJ"],
        ),
    ]
    loaded = types.SimpleNamespace(items=items, label="BBNJ")
    monkeypatch.setenv("PAPERFUL_PACK", "off")
    monkeypatch.setattr(cli, "_connect", lambda cfg, quiet=False: object())
    monkeypatch.setattr(cli, "_load_scope", lambda backend, **scope: loaded)

    dry = runner.invoke(
        cli.app, ["authors", "-C", "BBNJ", "--config", str(config)]
    )
    assert dry.exit_code == 0, dry.output
    assert "Ada Lovelace" in dry.output
    assert "FAO" in dry.output
    assert "Dry-run" in dry.output
    assert not (tmp_path / "state" / "reports").exists()

    applied = runner.invoke(
        cli.app,
        ["authors", "-C", "BBNJ", "--apply", "--config", str(config)],
    )
    assert applied.exit_code == 0, applied.output
    report = tmp_path / "state" / "reports" / "bbnj-authors.json"
    assert report.is_file()
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["schema"] == SCHEMA
    pack = tmp_path / "state" / "author-packs" / "bbnj.proposed.toml"
    assert pack.is_file()
    assert "lovelace|a" in pack.read_text(encoding="utf-8")
    assert "snowball packs promote" in applied.output

    js = runner.invoke(
        cli.app,
        [
            "authors",
            "-C",
            "BBNJ",
            "--format",
            "json",
            "--config",
            str(config),
        ],
    )
    assert js.exit_code == 0, js.output
    payload = json.loads(js.output)
    assert payload["command"] == "authors"
    assert payload["summary"]["authors"] >= 1
