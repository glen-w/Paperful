"""Offline coverage for the 1.8 HTTP client, review exchange, and Review page."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from rich.console import Console

from paperful.config import Config
from paperful.doctor import _playbook_gap_check
from paperful.http import client
from paperful.serve import create_app, fastapi_available
from paperful.sr.exchange import (
    apply_import,
    create_included_parents,
    export_text,
    normalise_format,
    parse_import,
)
from paperful.sr.identify import identified_ids, load_identification, work_identity
from paperful.sr.protocol import save_protocol
from paperful.sr_cmd import run_sr_export, run_sr_import, run_sr_status


def test_http_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("paperful.http.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, text="ok")

    http = client(transport=httpx.MockTransport(handler), guard=False, retries=2)
    with http as session:
        response = session.get("https://example.test/a")
        posted = session.post("https://example.test/a", content=b"x")
        headed = session.head("https://example.test/a")
    assert response.status_code == 200
    assert posted.status_code == 200
    assert headed.status_code == 200
    assert calls["n"] == 5
    session.close()


def test_http_retries_transport_error_then_raises(monkeypatch):
    monkeypatch.setattr("paperful.http.time.sleep", lambda _s: None)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    http = client(transport=httpx.MockTransport(handler), guard=False, retries=1)
    with pytest.raises(httpx.ConnectError):
        http.get("https://example.test/a")


def test_log_file_redacts_and_second_configure_is_idempotent(tmp_path, monkeypatch):
    import paperful.log as logmod

    monkeypatch.delenv("PAPERFUL_VERBOSE", raising=False)
    logger = logging.getLogger("paperful")
    logger.handlers.clear()
    logger.filters.clear()
    logmod._configured = False
    path = tmp_path / "logs" / "paperful.log"
    logmod.configure(verbose=True, log_file=path)
    again = logmod.configure(verbose=True)
    again.info("Authorization: Bearer super-secret-token")
    for handler in logger.handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "super-secret-token" not in text
    assert "[redacted]" in text


def test_exchange_csv_roundtrip_and_bad_format(tmp_path: Path):
    assert normalise_format("included.csv") == "csv"
    with pytest.raises(ValueError):
        normalise_format("nope")
    text = export_text(
        [
            {
                "doi": "10.1000/z",
                "title": "Zed",
                "authors": "A",
                "year": "2020",
                "decision": "include",
            }
        ],
        fmt="covidence",
        only_included=False,
    )
    parsed = parse_import(text, fmt="rayyan")
    assert parsed[0]["identity"] == "10.1000/z"
    state = tmp_path / "state"
    save_protocol(state, "rev", {"title": "T", "question": "Q"})
    dry = apply_import(
        state,
        "rev",
        [
            {"identity": "", "decision": "include"},
            {"identity": "10.1000/z", "decision": "nope"},
        ],
        reviewer="",
        apply=False,
    )
    assert dry["written"] == 0 and dry["planned"] == 1
    assert dry["rows"][0]["decision"] == "include"
    applied = apply_import(state, "rev", dry["rows"], reviewer="r", apply=True)
    assert applied["written"] == 1


def test_create_included_parents_needs_a_collection_or_a_backend(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    skipped = create_included_parents(
        cfg, [{"decision": "exclude", "identity": "10.1/x"}], ""
    )
    assert skipped["skipped"] == "no collection"

    class Backend:
        def supports_write(self) -> bool:
            return True

        def ensure_collection_path(self, path: str) -> str:
            return "CKEY"

        def create_parent(self, payload: dict) -> str:
            assert payload
            return "NEW1"

    made = create_included_parents(
        cfg,
        [{"decision": "include", "identity": "10.1000/z", "title": "Zed"}],
        "Shelf",
        backend=Backend(),
    )
    assert made["created"] == 1


def test_identification_reads_both_packs_and_skips_torn_lines(tmp_path: Path):
    state = tmp_path / "state"
    snow = state / "snowball" / "s1"
    snow.mkdir(parents=True)
    (snow / "candidates.jsonl").write_text(
        '{"doi": "10.1000/A"}\nnot-json\n{"openalex_id": "W1"}\n{"url": ""}\n',
        encoding="utf-8",
    )
    rows = load_identification(state, {"snowball_run": "s1", "search_run": "missing"})
    assert work_identity({"DOI": "10.1000/B"}) == "10.1000/b"
    assert identified_ids(rows) == ["10.1000/a", "W1"]


def test_sr_status_export_and_import(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir()
    save_protocol(
        cfg.state_dir,
        "rev",
        {"title": "Review", "question": "Q", "search_run": "r1"},
    )
    pack = cfg.state_dir / "search" / "r1"
    pack.mkdir(parents=True)
    (pack / "candidates.jsonl").write_text(
        '{"doi": "10.1000/z", "title": "Zed"}\n', encoding="utf-8"
    )
    assert run_sr_status(cfg, slug="rev") == 0
    assert (cfg.state_dir / "sr" / "rev" / "prisma.svg").is_file()
    assert run_sr_export(cfg, slug="rev", fmt="csv", only_included=False) == 0
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "identity,decision,reason,title,doi,url,year\n10.1000/z,include,,Zed,10.1000/z,,2020\n",
        encoding="utf-8",
    )
    assert (
        run_sr_import(
            cfg,
            slug="rev",
            path=str(csv_path),
            fmt="asreview",
            apply=False,
            reviewer="r",
        )
        == 0
    )
    assert (
        run_sr_import(
            cfg,
            slug="rev",
            path=str(csv_path),
            fmt="csv",
            apply=True,
            reviewer="r",
        )
        == 0
    )


def test_playbook_gap_check_reads_the_newest_summary(tmp_path: Path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    assert _playbook_gap_check(cfg) is None
    run = cfg.state_dir / "search" / "run1"
    run.mkdir(parents=True)
    (run / "summary.json").write_text("{", encoding="utf-8")
    assert _playbook_gap_check(cfg) is None
    (run / "summary.json").write_text(
        json.dumps({"playbook_gaps": ["iucn.org"]}), encoding="utf-8"
    )
    watches = cfg.state_dir / "search" / "watches"
    watches.mkdir()
    (watches / "summary.json").write_text(
        json.dumps({"playbook_gaps": ["ignore.example"]}), encoding="utf-8"
    )
    check = _playbook_gap_check(cfg)
    assert check is not None and check.code == "playbook_gap"
    assert "iucn.org" in check.detail


def test_search_watch_due_prints_json(tmp_path: Path, capsys):
    from paperful.search.command import run_search_watch_due
    from paperful.search.watch import save_watch

    cfg_path = tmp_path / "config.toml"
    state = tmp_path / "state"
    out = tmp_path / "out"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{out}"\nstate_dir = "{state}"\n',
        encoding="utf-8",
    )
    cfg = Config(email="t@example.org", out_dir=out, state_dir=state)
    state.mkdir()
    save_watch(cfg, "gjerde", terms=["Gjerde"], interval_days=1)
    run_search_watch_due(Console(), fmt="json", config=cfg_path)
    captured = capsys.readouterr().out
    assert "gjerde" in captured


@pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")
def test_review_page_screen_preview_and_svg(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import paperful.agent_ops as ops

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir()
    save_protocol(
        cfg.state_dir,
        "rev",
        {
            "title": "Review",
            "question": "Q",
            "exclude_reasons": ["off_topic"],
            "search_run": "r1",
        },
    )
    pack = cfg.state_dir / "search" / "r1"
    pack.mkdir(parents=True)
    (pack / "candidates.jsonl").write_text(
        '{"doi": "10.1000/z", "title": "Zed"}\n', encoding="utf-8"
    )
    monkeypatch.setattr(ops, "doctor_payload", lambda *_a, **_k: [])
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda *_a, **_k: [])
    client_http = TestClient(create_app(cfg))
    page = client_http.get("/review?slug=rev")
    assert page.status_code == 200
    assert "10.1000/z" in page.text
    svg = client_http.get("/review/prisma.svg?slug=rev")
    assert svg.status_code == 200
    assert b"Identification" in svg.content
    bad = client_http.post(
        "/review/screen",
        data={"slug": "rev", "identity": "", "decision": "include"},
        follow_redirects=False,
    )
    assert bad.status_code == 303 and "error=decision" in bad.headers["location"]
    ok = client_http.post(
        "/review/screen",
        data={
            "slug": "rev",
            "identity": "10.1000/z",
            "decision": "exclude",
            "reason": "off_topic",
        },
        follow_redirects=False,
    )
    assert ok.status_code == 303
    preview = client_http.post(
        "/review/preview",
        data={"slug": "rev", "collection": "Shelf"},
        follow_redirects=False,
    )
    assert preview.status_code == 303
    again = client_http.get("/review?slug=rev")
    assert "Apply" in again.text
    apply = client_http.post(
        "/review/apply",
        data={"slug": "rev", "review_token": "missing-token"},
        follow_redirects=False,
    )
    assert apply.status_code == 303 and "error=" in apply.headers["location"]
