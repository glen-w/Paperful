"""EndNote XML import/export edges (checklist E6-E8: bundle contents, PDF resolution, labels)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from paperful.interop import parse_endnote_xml, records_to_endnote_xml
from paperful.interop.load import dump_records, load_records
from paperful.interop.endnote_xml import _creator_name, _person, _pdf_href, _resolve_pdf


def _record(inner: str, ref='<ref-type name="Journal Article">17</ref-type>') -> str:
    return f"<xml><records><record>{ref}{inner}</record></records></xml>"


def _style(tag: str, text: str) -> str:
    return f'<{tag}><style face="normal">{text}</style></{tag}>'


def test_utf8_bom_is_stripped():
    xml = "﻿" + _record("<titles><title>With BOM</title></titles>")
    assert parse_endnote_xml(xml)[0]["title"] == "With BOM"


def test_malformed_xml_raises_parse_error():
    with pytest.raises(ET.ParseError):
        parse_endnote_xml("<xml><records><record>")
    with pytest.raises(ET.ParseError):
        parse_endnote_xml("")


def test_records_without_title_or_doi_are_dropped():
    xml = (
        "<xml><records>"
        "<record><ref-type name='Journal Article'>17</ref-type></record>"
        "<record><abstract>only an abstract</abstract></record>"
        "<record><electronic-resource-num>10.1/doi-only</electronic-resource-num></record>"
        "<record><titles><title>Title only</title></titles></record>"
        "</records></xml>"
    )
    got = parse_endnote_xml(xml)
    assert [r["doi"] for r in got] == ["10.1/doi-only", None]
    assert [r["title"] for r in got] == ["", "Title only"]


def test_external_entities_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENT", encoding="utf-8")
    xml = (
        '<?xml version="1.0"?>'
        f'<!DOCTYPE x [<!ENTITY leak SYSTEM "file://{secret}">]>'
        "<xml><records><record><titles><title>&leak;</title></titles></record></records></xml>"
    )
    try:
        recs = parse_endnote_xml(xml)
    except ET.ParseError:
        return  # refusing the document outright is also fine
    assert all("TOP-SECRET-CONTENT" not in (r["title"] or "") for r in recs)


def test_authors_and_editors_roles_and_name_forms():
    xml = _record(
        "<contributors><authors>"
        + _style("author", "Smith, Jane")
        + _style("author", "Ada Byron King")
        + _style("author", "Cher")
        + "</authors><secondary-authors>"
        + _style("author", "Ed, Itor")
        + "</secondary-authors></contributors><titles><title>T</title></titles>"
    )
    creators = parse_endnote_xml(xml)[0]["creators"]
    assert creators == [
        {"creatorType": "author", "lastName": "Smith", "firstName": "Jane"},
        {"creatorType": "author", "lastName": "King", "firstName": "Ada Byron"},
        {"creatorType": "author", "lastName": "Cher", "firstName": ""},
        {"creatorType": "editor", "lastName": "Ed", "firstName": "Itor"},
    ]


@pytest.mark.parametrize(
    ("year_text", "year"),
    [
        ("2019", 2019),
        ("c. 2004 (reprint)", 2004),
        ("1850", 1850),
        ("n.d.", None),
        ("circa 1492", None),  # free text is only searched inside the 1500-2099 window
        ("1492", 1492),  # a bare number is taken as-is
        ("", None),
    ],
)
def test_year_fallback_regex(year_text, year):
    xml = _record(f"<titles><title>T</title></titles><dates><year>{year_text}</year></dates>")
    rec = parse_endnote_xml(xml)[0]
    assert rec["year"] == year
    assert rec["date"] == year_text


def test_ref_type_number_and_name_pick_the_item_type():
    journal = parse_endnote_xml(_record("<titles><title>T</title></titles>"))[0]
    assert journal["item_type"] == "journalArticle"
    book = parse_endnote_xml(
        _record("<titles><title>T</title></titles>", ref='<ref-type name="Book">6</ref-type>')
    )[0]
    assert book["item_type"] == "book"
    nameless = parse_endnote_xml(_record("<titles><title>T</title></titles>", ref=""))[0]
    assert nameless["item_type"]  # falls back instead of raising


def test_accession_number_pmid_vs_free_text_and_urls():
    pmid = parse_endnote_xml(
        _record(_style("accession-num", "12345") + "<titles><title>T</title></titles>")
    )[0]
    assert pmid["pmid"] == "12345" and pmid["extra"] == "PMID: 12345"
    other = parse_endnote_xml(
        _record(_style("accession-num", "WOS:0001") + "<titles><title>T</title></titles>")
    )[0]
    assert other["pmid"] is None and other["extra"] == "WOS:0001"
    web = parse_endnote_xml(
        _record("<titles><title>T</title></titles><web-urls><url>https://w.test/p</url></web-urls>")
    )[0]
    assert web["url"] == "https://w.test/p"
    related = parse_endnote_xml(
        _record(
            "<titles><title>T</title></titles><urls><related-urls><url>https://r.test/p</url></related-urls></urls>"
            "<web-urls><url>https://w.test/p</url></web-urls>"
        )
    )[0]
    assert related["url"] == "https://r.test/p"  # related-urls wins over web-urls


def test_label_becomes_collection_path_only_when_it_is_a_path():
    path = parse_endnote_xml(_record(_style("label", "BBNJ/EIA") + "<titles><title>T</title></titles>"))[0]
    assert path["collection_paths"] == ["BBNJ/EIA"]
    plain = parse_endnote_xml(_record(_style("label", "to-read") + "<titles><title>T</title></titles>"))[0]
    assert plain["collection_paths"] == []


def test_notes_are_escaped_into_html_and_tagged():
    xml = _record(
        _style("research-notes", "a &lt; b &amp; c")
        + _style("notes", "plain note")
        + "<titles><title>T</title></titles>"
    )
    notes = parse_endnote_xml(xml)[0]["notes"]
    assert [n["file"] for n in notes] == ["research-notes.html", "notes.html"]
    assert notes[0]["html"] == "<p>a &lt; b &amp; c</p>"
    assert all(n["tag"] == "paperful-imported" for n in notes)


def test_keywords_skip_blanks():
    xml = _record(
        "<keywords><keyword><style>ocean</style></keyword><keyword><style>  </style></keyword>"
        "<keyword>law</keyword></keywords><titles><title>T</title></titles>"
    )
    assert parse_endnote_xml(xml)[0]["tags"] == [{"tag": "ocean"}, {"tag": "law"}]


# --- PDF resolution -------------------------------------------------------------------


def test_internal_pdf_resolves_against_xml_folder_layouts(tmp_path):
    (tmp_path / "PDF").mkdir()
    (tmp_path / "PDF" / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "PDF" / "deep" / "x").mkdir(parents=True)
    (tmp_path / "PDF" / "deep" / "x" / "c.pdf").write_bytes(b"%PDF")
    xml_path = tmp_path / "lib.xml"
    assert _resolve_pdf("internal-pdf://a.pdf", tmp_path) == str(tmp_path / "PDF" / "a.pdf")
    assert _resolve_pdf("internal-pdf://b.pdf", tmp_path) == str(tmp_path / "b.pdf")
    assert _resolve_pdf("internal-pdf://other/dir/b.pdf", tmp_path) == str(tmp_path / "b.pdf")
    assert _resolve_pdf("internal-pdf://c.pdf", tmp_path) == str(tmp_path / "PDF" / "deep" / "x" / "c.pdf")
    # Missing files resolve to the expected location rather than raising.
    assert _resolve_pdf("internal-pdf://gone.pdf", tmp_path) == str(tmp_path / "PDF" / "gone.pdf")
    assert xml_path  # silence unused


def test_pdf_urls_in_a_full_parse(tmp_path):
    (tmp_path / "PDF").mkdir()
    (tmp_path / "PDF" / "p.pdf").write_bytes(b"%PDF")
    xml = _record(
        "<titles><title>T</title></titles><urls><pdf-urls>"
        "<url>internal-pdf://p.pdf</url><url>  </url><url>file:///abs/q.pdf</url>"
        "<url>https://x.test/r.pdf</url></pdf-urls></urls>"
    )
    rec = parse_endnote_xml(xml, xml_path=tmp_path / "lib.xml")[0]
    assert rec["pdfs"] == [str(tmp_path / "PDF" / "p.pdf"), "/abs/q.pdf", "https://x.test/r.pdf"]


def test_internal_pdf_without_xml_path_keeps_relative_name():
    assert _resolve_pdf("internal-pdf://n.pdf", None) == "n.pdf"


def test_pdf_href_variants(tmp_path):
    real = tmp_path / "real.pdf"
    real.write_bytes(b"%PDF")
    assert _pdf_href("internal-pdf://k.pdf") == "internal-pdf://k.pdf"
    assert _pdf_href("file:///x.pdf") == "file:///x.pdf"
    assert _pdf_href(real) == real.resolve().as_uri()
    assert _pdf_href("/not/there/missing.pdf") == "internal-pdf://missing.pdf"


# --- export ---------------------------------------------------------------------------


def test_export_orders_authors_and_editors_and_skips_nameless():
    xml = records_to_endnote_xml(
        [
            {
                "item_type": "journalArticle",
                "title": "Exported",
                "creators": [
                    {"creatorType": "author", "lastName": "Ng", "firstName": "Li"},
                    {"creatorType": "editor", "lastName": "Ed", "firstName": "It"},
                    {"creatorType": "author", "name": "Single Name"},
                    {"creatorType": "author", "lastName": "", "firstName": "NoLast"},
                    "not-a-dict",
                ],
                "year": 2020,
                "tags": [{"tag": "t1"}, "t2", {"tag": ""}],
                "notes": [{"html": "<p>one&nbsp;note</p>"}, {"html": ""}, "junk"],
                "pmid": "99",
                "url": "https://u.test/p",
            }
        ],
        database="mylib",
    )
    root = ET.fromstring(xml)
    assert root.find(".//database").get("name") == "mylib"
    authors = ["".join(a.itertext()) for a in root.findall(".//contributors/authors/author")]
    editors = ["".join(a.itertext()) for a in root.findall(".//contributors/secondary-authors/author")]
    assert authors == ["Ng, Li", "Single Name"] and editors == ["Ed, It"]
    assert ["".join(k.itertext()) for k in root.findall(".//keywords/keyword")] == ["t1", "t2"]
    assert "".join(root.find(".//research-notes").itertext()) == "one note"
    assert "".join(root.find(".//accession-num").itertext()) == "99"
    assert root.find(".//related-urls/url").text == "https://u.test/p"


def test_export_round_trip_preserves_bundle_pdf_names_and_label():
    rec = {
        "item_type": "journalArticle",
        "title": "RT",
        "creators": [],
        "year": 2021,
        "pdfs": ["internal-pdf://Ng-2021.pdf", "/nonexistent/dir/other.pdf"],
        "collection_paths": ["A/B", "C"],
    }
    back = parse_endnote_xml(records_to_endnote_xml([rec]))[0]
    assert back["pdfs"][0].endswith("Ng-2021.pdf") and back["pdfs"][1].endswith("other.pdf")
    # EndNote has one label per record: only the first path survives.
    assert back["collection_paths"] == ["A/B"]


def test_creator_name_and_person_helpers():
    assert _creator_name({"lastName": "Ng", "firstName": "Li"}) == "Ng, Li"
    assert _creator_name({"name": "Org Inc"}) == "Org Inc"
    assert _creator_name({"firstName": "OnlyFirst"}) == ""
    assert _person("  Doe,  Jo ", "author") == {"creatorType": "author", "lastName": "Doe", "firstName": "Jo"}


def test_load_and_dump_dispatch_for_xml(tmp_path):
    path = tmp_path / "lib.xml"
    path.write_text(records_to_endnote_xml([{"item_type": "book", "title": "Dispatch", "year": 2000}]), encoding="utf-8")
    assert load_records(path)[0]["title"] == "Dispatch"
    assert load_records(path, "endnote_xml")[0]["title"] == "Dispatch"
    assert "<record>" in dump_records(load_records(path), "EndNote-XML")
    with pytest.raises(ValueError, match="Unknown format"):
        load_records(path, "docx")
    with pytest.raises(ValueError, match="Unknown format"):
        dump_records([], "docx")
