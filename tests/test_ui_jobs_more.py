"""Workbench job helpers: preview/grab/apply fingerprints (offline)."""

from __future__ import annotations

from types import SimpleNamespace

from paperful.config import Config
from paperful.ui import commands, jobs
from tests.conftest import make_item


def _cfg(tmp_path) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def test_item_filters_and_scope_for_fetch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    old = make_item(key="OLD", year=2010, item_type="journalArticle")
    new = make_item(key="NEW", year=2022, item_type="preprint")
    monkeypatch.setattr(
        "paperful.ui.jobs._load_scope_items",
        lambda *_a, **_k: ([old, new], SimpleNamespace()),
    )
    monkeypatch.setattr("paperful.ui.jobs.missing_items", lambda *_a, **_k: [old, new])
    items, _m = jobs.scope_for_fetch(
        cfg,
        "BBNJ",
        None,
        {"year_from": 2018, "year_to": 2025, "item_type": ["preprint"]},
    )
    assert [it.key for it in items] == ["NEW"]
    ticked, _m = jobs.scope_for_fetch(cfg, "BBNJ", ["OLD"], {})
    assert [it.key for it in ticked] == ["OLD"]
    assert (
        jobs._item_in_filters(old, year_from=2018, year_to=None, item_type=[]) is False
    )
    assert (
        jobs._item_in_filters(new, year_from=None, year_to=2020, item_type=[]) is False
    )


def test_load_scope_items_errors(tmp_path, monkeypatch):
    from paperful.library import LibraryError
    from paperful.scope import ScopeError

    cfg = _cfg(tmp_path)
    items, manifest = jobs._load_scope_items(cfg, "")
    assert items == []
    monkeypatch.setattr(
        "paperful.catalogue.open_library",
        lambda _c: (_ for _ in ()).throw(LibraryError("no zot")),
    )
    items, manifest = jobs._load_scope_items(cfg, "BBNJ")
    assert items == []
    monkeypatch.setattr(
        "paperful.catalogue.open_library",
        lambda _c: (_ for _ in ()).throw(ScopeError("bad")),
    )
    items, manifest = jobs._load_scope_items(cfg, "BBNJ")
    assert items == []


def test_preview_and_matching_and_grab(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    item = make_item(key="K1", year=2020)
    monkeypatch.setattr(
        "paperful.ui.jobs._load_scope_items",
        lambda *_a, **_k: ([item], SimpleNamespace()),
    )
    monkeypatch.setattr("paperful.ui.jobs.missing_items", lambda *_a, **_k: [item])

    def stub_fp(*_a, **_k):
        return "fp"

    monkeypatch.setattr("paperful.ui.jobs.scope_fingerprint", stub_fp)
    monkeypatch.setattr("paperful.ui.pages.scope_fingerprint", stub_fp)
    monkeypatch.setattr("paperful.ui.page_common.scope_fingerprint", stub_fp)
    jobs.run_fetch_fn = lambda *_a, **_k: None
    commands.write_command(cfg, {"id": "pv", "status": "running"})
    jobs.preview_run(cfg, "pv", collection="BBNJ", preset="oa", keys=["K1"], flags={})
    rec = commands.read_command(cfg, "pv")
    token = rec["review_token"]
    review, err = jobs.matching_preview(
        cfg,
        collection="BBNJ",
        preset="oa",
        posted_keys=["K1"],
        flags={},
        explicit_token=token,
    )
    assert err == "" and review is not None
    none, msg = jobs.matching_preview(
        cfg, collection="Other", preset="oa", posted_keys=["K1"], flags={}
    )
    assert none is None and "Preview" in msg
    ok, msg = jobs.grab_run(cfg, token=token)
    assert ok is True
    jobs.run_fetch_fn = None


def test_follow_person_and_import_hooks(tmp_path):
    cfg = _cfg(tmp_path)
    seen = {}
    jobs.authorwatch_run_fn = lambda *_a, **kw: seen.update(kw)
    jobs.follow_person(
        cfg, "c", orcid="0000-0002-1825-0097", list_name="L", backfill_from="2018"
    )
    assert seen["orcid"] == "0000-0002-1825-0097"
    jobs.authorwatch_run_fn = None
    jobs.authorwatch_import_fn = lambda *_a, **kw: seen.update(kw)
    jobs.authorwatch_import(cfg, list_name="L", path="x.csv", source="orcid")
    assert seen["source"] == "orcid"
    jobs.authorwatch_import_fn = None


def test_snowball_apply_fingerprint_and_discover(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    qdir = cfg.state_dir / "snowball" / "R1"
    qdir.mkdir(parents=True)
    (qdir / "candidates.jsonl").write_text(
        '{"keep": true, "ids": {"doi": "10.1/a"}}\nnot-json\n{"keep": false, "ids": {"doi": "10.1/b"}}\n',
        encoding="utf-8",
    )

    def _title_doi(data):
        return "T", (data.get("ids") or {}).get("doi")

    monkeypatch.setattr("paperful.ui.pages.candidate_title_doi", _title_doi)
    monkeypatch.setattr("paperful.ui.discover_rows.candidate_title_doi", _title_doi)
    fp = jobs._snowball_apply_fingerprint(cfg, "R1", "BBNJ")
    assert len(fp) == 64
    monkeypatch.setattr("paperful.authorwatch.inbox_count", lambda *_a, **_k: 2)
    monkeypatch.setattr("paperful.snowball.watch.inbox_count", lambda *_a, **_k: 3)
    commands.write_command(cfg, {"id": "d1", "status": "running"})
    token = jobs.discover_apply_preview(
        cfg, "d1", kind="snowball", run_id="R1", list_name="", collection="BBNJ"
    )
    jobs.snowball_apply_fn = lambda *_a, **_k: None
    ok, msg = jobs.discover_apply_consume(
        cfg, token=token, kind="snowball", run_id="R1", list_name="", collection="BBNJ"
    )
    assert ok is True
    jobs.snowball_apply_fn = None
    commands.write_command(cfg, {"id": "d2", "status": "running"})
    token2 = jobs.discover_apply_preview(
        cfg, "d2", kind="authorwatch", run_id="", list_name="L", collection="BBNJ"
    )
    jobs.authorwatch_apply_fn = lambda *_a, **_k: None
    ok, msg = jobs.discover_apply_consume(
        cfg,
        token=token2,
        kind="authorwatch",
        run_id="",
        list_name="L",
        collection="BBNJ",
    )
    assert ok is True
    jobs.authorwatch_apply_fn = None
    commands.write_command(cfg, {"id": "d3", "status": "running"})
    token3 = jobs.discover_apply_preview(
        cfg, "d3", kind="watch", run_id="W", list_name="", collection="BBNJ"
    )
    monkeypatch.setattr("paperful.snowball.watch.apply_watch", lambda *_a, **_k: None)
    ok, msg = jobs.discover_apply_consume(
        cfg, token=token3, kind="watch", run_id="W", list_name="", collection="BBNJ"
    )
    assert ok is True
    bad, msg = jobs.discover_apply_consume(
        cfg, token="nope", kind="snowball", run_id="R1", list_name="", collection="BBNJ"
    )
    assert bad is False


def test_authorwatch_accept_and_suggest(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen = {}
    monkeypatch.setattr(
        "paperful.authorwatch.accept_suggestions",
        lambda *_a, **kw: seen.update(kw),
    )
    monkeypatch.setattr(
        "paperful.authorwatch.run_list",
        lambda *_a, **kw: seen.update({"backfill": kw.get("backfill_from")}),
    )
    jobs.authorwatch_accept(cfg, list_name="L", suggestion_ids=["s1"], seed_from="2019")
    assert seen["backfill"] == "2019"
    monkeypatch.setattr(
        "paperful.authorwatch_suggest.suggest_people",
        lambda *_a, **kw: seen.update({"method": kw["method"]}),
    )
    jobs.authorwatch_suggest(
        cfg, list_name="L", collection="BBNJ", method="orcid", limit=5
    )
    assert seen["method"] == "orcid"
