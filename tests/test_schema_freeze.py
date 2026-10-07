"""Golden fixtures and frozenset contracts for 1.0 trust schemas."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.inbox_match import INBOX_PROPOSAL_KEYS, SCHEMA as INBOX_SCHEMA, write_proposal
from paperful.notehtml import NOTE_BLOCK_KEYS, SCHEMA as NOTE_SCHEMA, block, wrap, parse
from paperful.refs_gap import (
    REFS_GAP_PACK_KEYS,
    SCHEMA as REFS_SCHEMA,
    CiteRef,
    write_pack,
)
from paperful.runreport import (
    RUN_REPORT_ITEM_KEYS,
    RUN_REPORT_KEYS,
    RUN_REPORT_PATH_KEYS,
    RUN_REPORT_SUMMARY_KEYS,
    build_report,
)
from paperful.store import ITEM_RECORD_KEYS, empty_item_record
from tests.conftest import make_item

FIX = Path(__file__).parent / "fixtures"


def test_run_report_keys_match_golden_and_minimal():
    keys = json.loads((FIX / "run_report_v1" / "keys.json").read_text(encoding="utf-8"))
    assert keys["top"] == sorted(RUN_REPORT_KEYS)
    assert keys["summary"] == sorted(RUN_REPORT_SUMMARY_KEYS)
    assert keys["paths"] == sorted(RUN_REPORT_PATH_KEYS)
    assert keys["item"] == sorted(RUN_REPORT_ITEM_KEYS)
    minimal = json.loads((FIX / "run_report_v1" / "minimal.json").read_text(encoding="utf-8"))
    assert minimal["schema"] == "paperful.run_report.v1"
    assert RUN_REPORT_KEYS <= minimal.keys()
    assert RUN_REPORT_SUMMARY_KEYS <= minimal["summary"].keys()


def test_build_report_emits_frozen_summary_keys(cfg):
    class Stats:
        started_at = 0
        finished_at = 0
        items = []

    report = build_report(Stats(), cfg, command="run", scope="library", write_api=True)
    assert RUN_REPORT_KEYS <= report.keys()
    assert RUN_REPORT_SUMMARY_KEYS <= report["summary"].keys()
    for key in (
        "retryable",
        "browser_misses",
        "not_downloaded",
        "paywall_prices",
        "agent_after_playwright",
    ):
        assert key in report["summary"]


def test_refs_gap_pack_keys_match_golden(tmp_path: Path):
    keys = json.loads((FIX / "refs_gap_pack_v1" / "keys.json").read_text(encoding="utf-8"))
    assert keys == sorted(REFS_GAP_PACK_KEYS)
    golden = json.loads((FIX / "refs_gap_pack_v1" / "pack.json").read_text(encoding="utf-8"))
    assert golden["schema"] == REFS_SCHEMA
    assert REFS_GAP_PACK_KEYS <= golden.keys()
    folder = write_pack(
        tmp_path,
        "library",
        [
            CiteRef(
                doi="10.1000/a",
                title="A",
                year=2019,
                citing_keys=["SEED"],
                suggested_action="ingest-dois",
            )
        ],
        [],
    )
    pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert REFS_GAP_PACK_KEYS <= pack.keys()


def test_inbox_proposal_keys_match_golden(cfg, tmp_path: Path):
    keys = json.loads((FIX / "inbox_proposal_v1" / "keys.json").read_text(encoding="utf-8"))
    assert keys == sorted(INBOX_PROPOSAL_KEYS)
    golden = json.loads(
        (FIX / "inbox_proposal_v1" / "pending.json").read_text(encoding="utf-8")
    )
    assert golden["schema"] == INBOX_SCHEMA
    assert INBOX_PROPOSAL_KEYS <= golden.keys()
    cfg.inbox_dir = str(tmp_path / "drop")
    path = write_proposal(
        cfg,
        {
            "action": "create_parent",
            "pdf": str(tmp_path / "x.pdf"),
            "doi": "10.1000/x",
            "title": "X",
            "year": 2020,
            "how": "doi",
            "collection": "c",
        },
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    assert INBOX_PROPOSAL_KEYS <= body.keys()


def test_note_block_keys_match_golden():
    keys = json.loads((FIX / "note_v1" / "keys.json").read_text(encoding="utf-8"))
    assert keys == sorted(NOTE_BLOCK_KEYS)
    golden = json.loads((FIX / "note_v1" / "block.json").read_text(encoding="utf-8"))
    assert golden["schema"] == NOTE_SCHEMA
    assert NOTE_BLOCK_KEYS <= golden.keys()
    meta = block(
        note_type="summary",
        verb="summarize",
        model="qwen",
        run_id="r1",
        prompt_sha="abc",
    )
    assert NOTE_BLOCK_KEYS <= meta.keys()
    html = wrap("<p>x</p>", note_type="summary", verb="summarize", model="qwen")
    assert NOTE_BLOCK_KEYS <= parse(html).keys()


def test_item_empty_shell_covers_required_keys():
    keys = json.loads((FIX / "item_v1" / "keys.json").read_text(encoding="utf-8"))
    assert keys == sorted(ITEM_RECORD_KEYS)
    shell = json.loads((FIX / "item_v1" / "empty_shell.json").read_text(encoding="utf-8"))
    assert ITEM_RECORD_KEYS <= shell.keys()
    item = make_item(key="ARTICLE1", doi="10.1000/abc.1")
    live = empty_item_record(item)
    assert ITEM_RECORD_KEYS <= live.keys()
    assert set(live) >= ITEM_RECORD_KEYS
