"""Read-only wanted/discover row builders (wave 2)."""

from __future__ import annotations

import json

from paperful.config import Config
from paperful.miss_surface import project_miss_surface
from paperful.store import Record, STATUS_OK
from paperful.ui.pages import newest_snowball_queue, wanted_rows
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
