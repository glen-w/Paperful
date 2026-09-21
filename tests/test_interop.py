"""RIS / BibTeX / EndNote XML interchange."""

from paperful.interop.bibtex import parse_bibtex, records_to_bibtex
from paperful.interop.endnote_xml import parse_endnote_xml, records_to_endnote_xml
from paperful.interop.load import detect_format, dump_records, load_records
from paperful.interop.ris import parse_ris, records_to_ris
from paperful.interop.types import (
    endnote_db_to_zotero,
    endnote_to_zotero,
    mendeley_to_zotero,
    zotero_to_endnote,
    zotero_to_mendeley,
)
from paperful.store import is_item_dirname, item_dirname
from tests.conftest import make_item


def test_type_round_trips():
    assert zotero_to_mendeley("journalArticle") == "journal"
    assert mendeley_to_zotero("journal") == "journalArticle"
    num, name = zotero_to_endnote("journalArticle")
    assert name == "Journal Article"
    assert num == 17
    assert endnote_to_zotero(name, num) == "journalArticle"
    assert endnote_to_zotero("Web Page", 12) == "webpage"
    assert endnote_db_to_zotero(0) == "journalArticle"
    assert endnote_db_to_zotero(17) == "bill"
    assert endnote_to_zotero(None, 17) == "journalArticle"


def test_ris_round_trip_keeps_doi_notes_and_pdf():
    records = [
        {
            "item_type": "journalArticle",
            "title": "High seas governance",
            "creators": [
                {
                    "creatorType": "author",
                    "lastName": "Smith",
                    "firstName": "Jane",
                }
            ],
            "year": 2021,
            "date": "2021",
            "publication_title": "Marine Policy",
            "doi": "10.1000/test.doi",
            "url": "https://example.org/p",
            "abstract": "An abstract.",
            "pmid": "123",
            "tags": [{"tag": "BBNJ"}],
            "notes": [{"html": "<p>hello</p>", "tag": "paperful-imported"}],
            "pdfs": ["/tmp/a.pdf"],
            "collection_paths": [],
        }
    ]
    text = records_to_ris(records)
    assert "TY  - JOUR" in text and "DO  - 10.1000/test.doi" in text
    back = parse_ris(text)
    assert len(back) == 1
    assert back[0]["doi"] == "10.1000/test.doi"
    assert back[0]["title"] == "High seas governance"
    assert back[0]["creators"][0]["lastName"] == "Smith"
    assert back[0]["tags"][0]["tag"] == "BBNJ"
    assert back[0]["notes"]


def test_ris_tolerates_bom_and_crlf():
    raw = "\ufeffTY  - JOUR\r\nTI  - Hello\r\nPY  - 2020\r\nER  - \r\n"
    recs = parse_ris(raw)
    assert recs[0]["title"] == "Hello" and recs[0]["year"] == 2020


def test_bibtex_parse_and_write(tmp_path):
    src = """
@article{Smith2020,
  title = {A paper},
  author = {Smith, Jane and Doe, John},
  year = {2020},
  journal = {Marine Policy},
  doi = {10.1/x},
  file = {:/abs/paper.pdf:PDF}
}
"""
    recs = parse_bibtex(src)
    assert recs[0]["item_type"] == "journalArticle"
    assert recs[0]["doi"] == "10.1/x"
    assert recs[0]["creators"][0]["lastName"] == "Smith"
    text = records_to_bibtex(recs)
    assert "@article" in text and "10.1/x" in text


def test_endnote_xml_round_trip():
    records = [
        {
            "item_type": "journalArticle",
            "title": "XML paper",
            "creators": [
                {"creatorType": "author", "lastName": "Ng", "firstName": "Li"}
            ],
            "year": 2019,
            "date": "2019",
            "publication_title": "Nature",
            "doi": "10.2/y",
            "tags": [{"tag": "ocean"}],
            "notes": [{"html": "<p>rn</p>"}],
            "pdfs": ["internal-pdf://Ng-2019.pdf"],
            "collection_paths": ["BBNJ/EIA"],
            "abstract": "Abs",
        }
    ]
    xml = records_to_endnote_xml(records)
    assert "Journal Article" in xml and "10.2/y" in xml
    back = parse_endnote_xml(xml)
    assert back[0]["title"] == "XML paper"
    assert back[0]["doi"] == "10.2/y"
    assert back[0]["collection_paths"] == ["BBNJ/EIA"]


def test_detect_and_load(tmp_path):
    ris = tmp_path / "a.ris"
    ris.write_text("TY  - JOUR\nTI  - Z\nER  - \n", encoding="utf-8")
    assert detect_format(ris) == "ris"
    assert load_records(ris)[0]["title"] == "Z"
    out = dump_records(load_records(ris), "ris")
    assert "TI  - Z" in out


def test_item_dirname_accepts_uuid_and_int_keys():
    uuid_item = make_item(key="1137042a-8c30-3cd6-a7f6-7d5f1f6c450d")
    name = item_dirname(uuid_item)
    assert is_item_dirname(name)
    assert name.endswith("1137042a-8c30-3cd6-a7f6-7d5f1f6c450d")
    int_item = make_item(key="42")
    assert is_item_dirname(item_dirname(int_item))
