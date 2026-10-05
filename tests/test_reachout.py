"""Reachout: contact-only missing-PDF list. No fetch."""

from __future__ import annotations

import csv

from paperful.reachout import (
    build_reachout_rows,
    emails_from_item,
    extract_emails_from_text,
    write_reachout_export,
)
from paperful.store import STATUS_NOT_FOUND, Manifest, Record
from tests.conftest import make_item


def test_extract_prefers_correspondence_line():
    text = (
        "Authors: Ada Lovelace ada@gmail.com\n"
        "Corresponding author: Ada Lovelace ada@univ.edu\n"
        "banner@2x.png"
    )
    assert extract_emails_from_text(text)[0] == "ada@univ.edu"
    assert "banner@2x.png" not in extract_emails_from_text(text)


def test_emails_from_item_extra_and_mailto():
    extra = make_item(
        extra="Correspondence: smith@ocean.edu\nDOI: 10.1/x",
        url="https://example.org/paper",
        has_pdf=False,
    )
    assert emails_from_item(extra) == ["smith@ocean.edu"]
    mail = make_item(
        extra="",
        url="mailto:jane.doe@uni.ac.uk?subject=PDF",
        has_pdf=False,
    )
    assert emails_from_item(mail) == ["jane.doe@uni.ac.uk"]


def test_metadata_beats_twenty_cache(cfg):
    cfg.twenty_enabled = True
    item = make_item(
        extra="corresponding author: meta@univ.edu",
        first_author="Lovelace",
        creator_surnames=["Lovelace"],
        has_pdf=False,
    )
    folder = cfg.state_dir / "author-contacts"
    folder.mkdir(parents=True)
    (folder / "lovelace-l.json").write_text(
        '{"schema":"paperful.author_contact.v1","fingerprint":"lovelace|l",'
        '"emails":["crm@univ.edu"]}\n',
        encoding="utf-8",
    )
    rows = build_reachout_rows(cfg, [item])
    assert len(rows) == 1
    assert rows[0].email == "meta@univ.edu"
    assert rows[0].email_source == "metadata"


def test_twenty_cache_when_no_metadata(cfg):
    cfg.twenty_enabled = True
    item = make_item(
        extra="",
        first_author="Lovelace",
        creator_surnames=["Lovelace"],
        has_pdf=False,
    )
    folder = cfg.state_dir / "author-contacts"
    folder.mkdir(parents=True)
    (folder / "lovelace-l.json").write_text(
        '{"schema":"paperful.author_contact.v1","fingerprint":"lovelace|l",'
        '"emails":["crm@univ.edu"]}\n',
        encoding="utf-8",
    )
    rows = build_reachout_rows(cfg, [item])
    assert rows[0].email == "crm@univ.edu"
    assert rows[0].email_source == "twenty"


def test_non_oa_only_drops_unknown_surface(cfg):
    closed = make_item(key="CLOSED01", title="Closed paper", has_pdf=False)
    unknown = make_item(key="OPEN0001", title="Unknown paper", has_pdf=False)
    have = make_item(key="HAVEPDF1", title="Has pdf", has_pdf=True)
    man = Manifest(cfg.manifest_path)
    man.write(
        Record(
            itemKey="CLOSED01",
            status=STATUS_NOT_FOUND,
            title=closed.title,
            doi=closed.doi,
            attempts=["unpaywall:not_found(no OA location)"],
        )
    )
    rows = build_reachout_rows(cfg, [closed, unknown, have], non_oa_only=True)
    assert [r.key for r in rows] == ["CLOSED01"]
    all_rows = build_reachout_rows(cfg, [closed, unknown, have], non_oa_only=False)
    assert {r.key for r in all_rows} == {"CLOSED01", "OPEN0001"}


def test_csv_columns_stable(cfg, tmp_path):
    item = make_item(has_pdf=False, extra="c@univ.edu")
    rows = build_reachout_rows(cfg, [item])
    path = write_reachout_export(rows, tmp_path / "reachout.csv")
    with path.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == [
        "key",
        "title",
        "year",
        "author",
        "email",
        "email_source",
        "doi",
        "oa_status",
        "miss_surface",
        "request_url",
    ]


def test_lookup_writes_contact(cfg, monkeypatch):
    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    item = make_item(
        extra="",
        first_author="Ada Lovelace",
        creator_surnames=["Lovelace"],
        has_pdf=False,
    )

    def getter(url, headers, params):
        return {
            "data": {
                "people": [
                    {
                        "id": "p1",
                        "name": {"firstName": "Ada", "lastName": "Lovelace"},
                        "emails": {"primaryEmail": "ada@univ.edu"},
                    }
                ]
            }
        }

    rows = build_reachout_rows(cfg, [item], lookup=True, getter=getter)
    assert rows[0].email == "ada@univ.edu"
    assert rows[0].email_source == "twenty"
    assert list((cfg.state_dir / "author-contacts").glob("*.json"))


def test_reachout_module_does_not_import_fetch_sources():
    import inspect

    import paperful.reachout as mod

    src = inspect.getsource(mod)
    assert "paperful.pipeline" not in src
    assert "scihub" not in src
    assert "ezproxy" not in src


def test_emails_from_abstract():
    item = make_item(abstract="Please write to foo@marine.org for the PDF.", extra="", has_pdf=False)
    assert emails_from_item(item) == ["foo@marine.org"]


def test_lookup_ambiguous_stays_blank(cfg, monkeypatch):
    monkeypatch.setenv("TWENTY_API_KEY", "test-key")
    cfg.twenty_enabled = True
    cfg.twenty_base_url = "https://api.twenty.example"
    item = make_item(
        extra="",
        first_author="Lovelace",
        creator_surnames=["Lovelace"],
        has_pdf=False,
    )

    def getter(url, headers, params):
        return {
            "data": {
                "people": [
                    {"id": "1", "name": {"firstName": "Ada", "lastName": "Lovelace"}},
                    {"id": "2", "name": {"firstName": "Ann", "lastName": "Lovelace"}},
                ]
            }
        }

    rows = build_reachout_rows(cfg, [item], lookup=True, getter=getter)
    assert rows[0].email == ""
    assert rows[0].email_source == ""
    assert not list((cfg.state_dir / "author-contacts").glob("*.json"))


def test_tsv_and_md_export(cfg, tmp_path):
    item = make_item(has_pdf=False, extra="c@univ.edu")
    rows = build_reachout_rows(cfg, [item])
    tsv = write_reachout_export(rows, tmp_path / "reachout.tsv")
    md = write_reachout_export(rows, tmp_path / "reachout.md")
    tsv_text = tsv.read_text(encoding="utf-8")
    assert tsv_text.splitlines()[0].startswith("key\ttitle")
    assert "c@univ.edu" in tsv_text
    md_text = md.read_text(encoding="utf-8")
    assert "# Reachout" in md_text
    assert "c@univ.edu" in md_text


def test_rg_url_on_row_when_request_enabled(cfg):
    cfg.request_channels = "rg"
    item = make_item(
        has_pdf=False,
        url="https://www.researchgate.net/publication/123456789_A_Paper",
        extra="",
    )
    rows = build_reachout_rows(cfg, [item])
    assert rows[0].request_url.endswith("A_Paper")
