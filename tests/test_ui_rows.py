"""Read-only wanted/discover row builders (wave 2)."""

from __future__ import annotations

import json

from paperful.config import Config
from paperful.miss_surface import project_miss_surface
from paperful.store import Manifest, Record, STATUS_OK
from paperful.ui.pages import (
    library_items_page,
    nest_collection_rows,
    newest_snowball_queue,
    resolve_wanted_tab,
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
