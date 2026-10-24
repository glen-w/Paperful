"""Read-only wanted/discover row builders (wave 2)."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.config import Config
from paperful.miss_surface import project_miss_surface
from paperful.store import Manifest, Record, STATUS_OK
from paperful.ui.pages import (
    briefs_synth_form,
    dest_for_form,
    job_view,
    last_job_result,
    library_items_page,
    nest_collection_rows,
    newest_snowball_queue,
    resolve_wanted_tab,
    wanted_items_page,
    wanted_rows,
)
from paperful.ui.verify import file_verification


class _Item:
    def __init__(self, key: str, title: str, doi: str | None, has_pdf: bool):
        self.key = key
        self.title = title
        self.doi = doi
        self.has_pdf = has_pdf
        self.arxiv_id = None
        self.url = ""
        self.year = 2024


def test_file_verification_buckets():
    rec = Record(
        itemKey="K1",
        status=STATUS_OK,
        doi="10.1/a",
        pdf_doi="10.1/a",
        source="unpaywall",
        path="x.pdf",
    )
    assert file_verification(rec, item_doi="10.1/a")["state"] == "doi_match"
    rec2 = Record(
        itemKey="K2",
        status=STATUS_OK,
        doi="10.1/a",
        pdf_doi="10.9/b",
        source="unpaywall",
        path="y.pdf",
    )
    assert file_verification(rec2, item_doi="10.1/a")["state"] == "doi_mismatch"
    rec3 = Record(
        itemKey="K3",
        status=STATUS_OK,
        doi="10.1/c",
        pdf_doi=None,
        source="grey:undocs",
        path="z.pdf",
    )
    assert file_verification(rec3, item_doi="10.1/c")["state"] == "unverified"
    assert file_verification(rec3)["reason"] == "grey"


def test_import_ok_not_miss_row():
    code = project_miss_surface(doi="10.1/x", has_pdf=True, status=STATUS_OK, source="unpaywall")
    assert code == "import_ok"


def test_wanted_rows_counts(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    from paperful.store import Manifest

    manifest = Manifest(cfg.manifest_path)
    items = [
        _Item("A", "Match", "10.1/a", True),
        _Item("B", "Miss", "10.2/b", False),
    ]
    manifest.write(
        Record(
            itemKey="A",
            status=STATUS_OK,
            doi="10.1/a",
            pdf_doi="10.1/a",
            source="unpaywall",
            path="a.pdf",
        )
    )
    data = wanted_rows(cfg, items, manifest)
    assert data["counts"]["have"] == 1
    assert data["counts"]["missing"] == 1
    assert data["counts"]["attach"] == 1
    assert "%" not in str(data["counts"])


def test_wanted_rows_ghost_pdf_on_missing_not_held(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    manifest = Manifest(cfg.manifest_path)
    ghost = _Item("G", "Ghost PDF", "10.3/g", True)
    data = wanted_rows(cfg, [ghost], manifest)
    assert data["counts"]["held"] == 0
    assert data["counts"]["missing"] == 1
    row = data["missing"][0]
    assert row["miss_surface"] == "missing"
    assert "No PDF file on disk" in row["miss_plain"]


def test_resolve_wanted_tab_defaults_to_first_non_empty():
    assert resolve_wanted_tab(None, {"missing": 0, "held": 4, "have": 0}) == "held"
    assert resolve_wanted_tab(None, {"missing": 2, "held": 4, "have": 0}) == "missing"
    assert resolve_wanted_tab("held", {"missing": 2, "held": 0, "have": 0}) == "held"


def test_resolve_discover_tab_defaults_and_guards_grow():
    from paperful.ui.pages import resolve_discover_tab

    assert (
        resolve_discover_tab(
            None,
            advanced=False,
            has_candidates=True,
            has_following=True,
            explore_picks=False,
            list_requested=False,
        )
        == "queue"
    )
    assert (
        resolve_discover_tab(
            "grow",
            advanced=False,
            has_candidates=False,
            has_following=False,
            explore_picks=False,
            list_requested=False,
        )
        == "topic"
    )
    assert (
        resolve_discover_tab(
            "grow",
            advanced=True,
            has_candidates=False,
            has_following=False,
            explore_picks=False,
            list_requested=False,
        )
        == "grow"
    )
    assert (
        resolve_discover_tab(
            None,
            advanced=False,
            has_candidates=False,
            has_following=False,
            explore_picks=False,
            list_requested=True,
        )
        == "people"
    )


def test_nest_collection_rows_groups_paths():
    tree = nest_collection_rows(
        [
            {"path": "AO", "name": "AO", "key": "1", "items": 267, "missing_pdf": 10},
            {
                "path": "AO/Mini meta studies",
                "name": "Mini meta studies",
                "key": "2",
                "items": 0,
                "missing_pdf": 0,
            },
            {
                "path": "AO/Mini meta studies/Coffee",
                "name": "Coffee",
                "key": "3",
                "items": 0,
                "missing_pdf": 0,
            },
            {"path": "degrowth", "name": "degrowth", "key": "4", "items": 683, "missing_pdf": 1},
        ],
        active="AO/Mini meta studies/Coffee",
    )
    assert [n["name"] for n in tree] == ["AO", "degrowth"]
    ao = tree[0]
    assert ao["item_count"] == 267
    assert ao["open"] is True
    mini = next(c for c in ao["children"] if c["name"] == "Mini meta studies")
    assert mini["open"] is True
    assert mini["children"][0]["name"] == "Coffee"
    assert mini["children"][0]["open"] is True
    assert tree[1]["open"] is False
    assert tree[1]["children"] == []


def test_wanted_items_page_filters_sorts_and_slices():
    rows = [
        {"key": "C", "title": "Charlie", "year": 2020, "doi": "", "has_summary": False},
        {"key": "A", "title": "Alpha", "year": 2024, "doi": "10.1/a", "has_summary": True},
        {"key": "B", "title": "Bravo", "year": 2022, "doi": "", "has_summary": False},
        {"key": "D", "title": "Delta", "year": 2018, "doi": "", "has_summary": True},
        {"key": "E", "title": "Echo", "year": None, "doi": "", "has_summary": False},
    ]
    page, total, index, count = wanted_items_page(
        rows, page=2, per_page=2, order="title"
    )
    assert total == 5
    assert index == 2
    assert count == 3
    assert [row["title"] for row in page] == ["Charlie", "Delta"]

    newest, *_rest = wanted_items_page(rows, page=1, per_page=10, order="year_new")
    assert [row["title"] for row in newest] == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]

    summaries, total_sum, _, _ = wanted_items_page(
        rows, page=1, per_page=10, filt="summary"
    )
    assert total_sum == 2
    assert [row["key"] for row in summaries] == ["A", "D"]

    search, total_q, _, _ = wanted_items_page(
        rows, page=1, per_page=10, query="10.1/a"
    )
    assert total_q == 1
    assert search[0]["key"] == "A"


def test_library_items_page_slices(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    manifest = Manifest(cfg.manifest_path)
    items = [
        _Item(f"K{i}", f"Title {i:02d}", None, False)
        for i in range(5)
    ]
    rows, total, page, page_count = library_items_page(
        cfg, items, manifest, page=2, per_page=2
    )
    assert total == 5
    assert page == 2
    assert page_count == 3
    assert len(rows) == 2
    assert rows[0]["title"] == "Title 02"


def test_discover_queue_fixture(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    run = cfg.state_dir / "snowball" / "run1"
    run.mkdir(parents=True)
    rows = [
        {"schema": "paperful.snowball.candidate.v1", "title": "One", "doi": "10.1/1"},
        {"schema": "paperful.snowball.candidate.v1", "title": "Two", "doi": "10.1/2"},
    ]
    (run / "candidates.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    run_id, candidates = newest_snowball_queue(cfg)
    assert run_id == "run1"
    assert len(candidates) == 2
    assert candidates[0]["title"] == "One"


def test_discover_queue_reads_nested_biblio(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    run = cfg.state_dir / "snowball" / "run-nested"
    run.mkdir(parents=True)
    row = {
        "schema": "paperful.snowball.candidate.v1",
        "biblio": {"title": "Nested title"},
        "ids": {"doi": "10.1000/nested"},
        "keep": True,
    }
    (run / "candidates.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    inbox = cfg.state_dir / "authorwatch" / "voices"
    inbox.mkdir(parents=True)
    (inbox / "inbox.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    _run_id, candidates = newest_snowball_queue(cfg)
    assert candidates[0]["title"] == "Nested title"
    assert candidates[0]["doi"] == "10.1000/nested"
    from paperful.ui.pages import authorwatch_inbox_rows

    rows = authorwatch_inbox_rows(cfg)
    assert rows[0]["title"] == "Nested title"
    assert rows[0]["doi"] == "10.1000/nested"


def test_list_recent_summaries_cite_and_model(tmp_path):
    from paperful.mirror import forget_index
    from paperful.notehtml import wrap
    from paperful.store import record_path, write_json
    from paperful.ui.pages import list_recent_summaries

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.summaries_dir.mkdir(parents=True)
    (cfg.summaries_dir / "KEY1.html").write_text(
        wrap("<p>body</p>", note_type="summary", verb="summarize", model="qwen2.5"),
        encoding="utf-8",
    )
    folder = cfg.out_dir / "BBNJ" / "Smith - 2021 - Area-based -- KEY1"
    folder.mkdir(parents=True)
    write_json(
        record_path(folder),
        {
            "item_key": "KEY1",
            "title": "Area-based management",
            "year": 2021,
            "creators": [{"creatorType": "author", "lastName": "Smith"}],
        },
    )
    forget_index(cfg.out_dir)
    rows = list_recent_summaries(cfg)
    assert len(rows) == 1
    assert rows[0]["name"] == "KEY1"
    assert rows[0]["model"] == "qwen2.5"
    assert "Smith" in rows[0]["cite"]
    assert "2021" in rows[0]["cite"]
    assert "Area-based" in rows[0]["cite"]


def test_job_view_normalizes_command_record():
    assert job_view(None) == {}
    view = job_view(
        {
            "id": "abc",
            "verb": "rag_ingest",
            "status": "failed",
            "error": "no index",
            "args": {"limit": 3},
            "result": {"summary": {"pdf": 0}},
        }
    )
    assert view["id"] == "abc"
    assert view["verb"] == "rag_ingest"
    assert view["status"] == "failed"
    assert view["error"] == "no index"
    assert view["args"]["limit"] == 3
    assert view["summary"]["pdf"] == 0


def test_keep_matches_legacy_top_level_doi(tmp_path):
    from paperful.ui.jobs import set_snowball_keep

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    run = cfg.state_dir / "snowball" / "run1"
    run.mkdir(parents=True)
    row = {"schema": "paperful.snowball.candidate.v1", "title": "One", "doi": "10.1/legacy"}
    (run / "candidates.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    set_snowball_keep(cfg, "run1", ["10.1/legacy"], False)
    saved = json.loads((run / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert saved["keep"] is False
    assert saved["ids"]["doi"] == "10.1/legacy"
    assert saved["biblio"]["title"] == "One"


def test_last_job_result_prefers_matching_run(tmp_path):
    from paperful.ui import commands

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    # "old" is written last so its file mtime is newest; created time must win.
    commands.write_command(
        cfg,
        {"id": "new", "verb": "ask", "status": "queued", "created": 30, "result": {}},
    )
    commands.write_command(
        cfg,
        {"id": "ingest", "verb": "rag_ingest", "status": "queued", "created": 20, "result": {}},
    )
    commands.write_command(
        cfg,
        {"id": "old", "verb": "ask", "status": "done", "created": 10, "result": {"answer": "old"}},
    )
    by_run = last_job_result(cfg, "ask", run="old")
    assert by_run["id"] == "old"
    assert by_run["status"] == "done"
    latest = last_job_result(cfg, "ask", run="ingest")
    assert latest["id"] == "new"
    assert latest["status"] == "queued"


def test_dest_for_form_falls_back_to_disk_without_collection():
    assert dest_for_form("both", "") == "disk"
    assert dest_for_form("zotero", "") == "disk"
    assert dest_for_form("disk", "") == "disk"
    assert dest_for_form("both", "ocean") == "both"


def test_briefs_synth_form_prefers_query_then_last_job():
    class _Req:
        def __init__(self, **qp):
            self.query_params = qp

    from_query = briefs_synth_form(
        _Req(synth_dest="zotero", synth_limit="40", synth_year_from="2020"),
        dest_default="both",
        collection="",
        last={"args": {"dest": "disk", "limit": 9}},
    )
    assert from_query["dest"] == "zotero"
    assert from_query["limit"] == "40"
    assert from_query["year_from"] == "2020"

    from_last = briefs_synth_form(
        _Req(),
        dest_default="both",
        collection="",
        last={"args": {"dest": "both", "limit": 12, "force": True}},
    )
    assert from_last["dest"] == "disk"
    assert from_last["limit"] == "12"
    assert from_last["force"] is True

    fresh = briefs_synth_form(
        _Req(), dest_default="both", collection="ocean/BBNJ", last={}
    )
    assert fresh["dest"] == "both"
    assert fresh["limit"] == ""


def test_discover_queue_rows_carry_the_why_line(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    run = cfg.state_dir / "snowball" / "run-why"
    run.mkdir(parents=True)
    rows = [
        {"biblio": {"title": "Cited"}, "ids": {"doi": "10.1/c"}, "why": "cited by 3 of your seeds"},
        {"biblio": {"title": "Bare"}, "ids": {"doi": "10.1/b"}},
    ]
    (run / "candidates.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    _run_id, candidates = newest_snowball_queue(cfg)
    assert candidates[0]["why"] == "cited by 3 of your seeds"
    assert candidates[1]["why"] == ""
    assert "Why suggested" in Path("paperful/ui/templates/discover.html").read_text(encoding="utf-8")
