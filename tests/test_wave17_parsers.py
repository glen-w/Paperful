"""Parser hardening lane (1.7): hostile inputs must fail closed, never hang
or resolve external entities. Deterministic corpus — no network, no fuzz
dependency; add cases here when a new hostile shape is found."""

from __future__ import annotations

import pytest

from paperful.interop.bibtex import parse_bibtex
from paperful.interop.endnote_xml import parse_endnote_xml
from paperful.interop.ris import parse_ris
from paperful.resolve.ids import version_from_arxiv_xml

BILLION_LAUGHS = (
    '<?xml version="1.0"?>'
    "<!DOCTYPE lolz ["
    '<!ENTITY lol "lollollollollollollollollollol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    "]>"
    "<xml><records><record><titles><title>&lol3;</title></titles>"
    "</record></records></xml>"
)

XXE = (
    '<?xml version="1.0"?>'
    '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]>'
    "<xml><records><record><titles><title>&leak;</title></titles>"
    "</record></records></xml>"
)


def test_endnote_xml_rejects_entities():
    for payload in (BILLION_LAUGHS, XXE):
        with pytest.raises(Exception) as excinfo:
            parse_endnote_xml(payload)
        assert "root:" not in str(excinfo.value)


def test_endnote_xml_malformed_returns_parse_error_not_crash():
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        parse_endnote_xml("<xml><records><record>")


def test_arxiv_xml_entity_payload_is_ignored():
    payload = XXE.replace(
        "<xml><records><record><titles><title>&leak;</title></titles></record></records></xml>",
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        "<id>http://arxiv.org/abs/2401.00001v1</id></entry></feed>",
    )
    assert version_from_arxiv_xml(payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not bibtex at all {{{",
        "@article{, title = {Unclosed",
        "@article{key, title = {A} ",
        "\x00\x01\x02 binary junk",
        "@" * 5000,
        "{" * 5000,
    ],
)
def test_bibtex_hostile_inputs_do_not_raise(payload):
    assert isinstance(parse_bibtex(payload), list)


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "TY  - JOUR\nTI  - No end tag",
        "TY  - \nTI  - \nER  - \n",
        "\x00binary\xff junk",
        "ER  - orphan\n" * 1000,
    ],
)
def test_ris_hostile_inputs_do_not_raise(payload):
    assert isinstance(parse_ris(payload), list)
