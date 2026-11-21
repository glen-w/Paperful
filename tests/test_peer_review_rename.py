"""Hard-break: manuscript pack is peer-review, not critique."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from paperful.config_check import check_config
from paperful.notehtml import wrap
from paperful.notes import identify
from paperful.config import Config
from paperful.peer_review import SCHEMA, latest_pack_dir, load_pack, write_pack
from paperful.serve import create_app, fastapi_available

import pytest

runner = CliRunner()


def test_cli_drops_critique_verb():
    from paperful.cli import app

    gone = runner.invoke(app, ["critique", "--help"])
    assert gone.exit_code != 0
    keep = runner.invoke(app, ["peer-review", "--help"])
    assert keep.exit_code == 0
    assert "peer-review" in keep.output.lower()


def test_config_rejects_legacy_critique_table(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[critique]\nllm = true\n", encoding="utf-8")
    issues = check_config(cfg_path)
    assert any("critique" in line for line in issues)
    assert not any("unknown section 'peer_review'" in line for line in issues)


def test_load_pack_rejects_legacy_schema(tmp_path: Path):
    folder = tmp_path / "stamp"
    folder.mkdir()
    (folder / "pack.json").write_text(
        json.dumps(
            {
                "schema": "paperful.critique.pack.v1",
                "critique_id": "file-draft",
                "findings": [],
            }
        ),
        encoding="utf-8",
    )
    assert load_pack(folder) is None
    (folder / "pack.json").write_text(
        json.dumps({"schema": SCHEMA, "peer_review_id": "file-draft", "findings": []}),
        encoding="utf-8",
    )
    pack = load_pack(folder)
    assert pack is not None
    assert pack["schema"] == SCHEMA


def test_latest_pack_dir_ignores_legacy_critiques_folder(tmp_path: Path):
    cfg = Config(state_dir=tmp_path / "state")
    old = tmp_path / "state" / "critiques" / "file-draft" / "oldstamp"
    old.mkdir(parents=True)
    (old / "pack.json").write_text(
        json.dumps({"schema": "paperful.critique.pack.v1", "findings": []}),
        encoding="utf-8",
    )
    assert latest_pack_dir(cfg, "file-draft") is None
    write_pack(cfg, cid="file-draft", payload={"findings": []}, stamp="newstamp")
    found = latest_pack_dir(cfg, "file-draft")
    assert found is not None
    assert "peer-reviews" in found.parts
    assert load_pack(found) is not None


def test_synthesize_review_note_type_unchanged():
    cfg = Config()
    html = wrap("<p>lit</p>", note_type="review", verb="synthesize")
    assert identify(html, ("paperful-report",), cfg)[0] == "review"


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_workbench_keeps_sr_review_and_drops_critique_path(tmp_path):
    from fastapi.testclient import TestClient

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    client = TestClient(create_app(cfg))
    client.cookies.set("pf_advanced", "1")
    gone = client.get("/critique")
    assert gone.status_code == 404
    peer = client.get("/peer-review")
    assert peer.status_code == 200
    assert "Peer review" in peer.text
    sr = client.get("/review")
    assert sr.status_code == 200
    assert "Peer review — Paperful" not in sr.text
