"""Manager-agnostic interchange: types, RIS, BibTeX, EndNote XML.

Canonical item type ids are Zotero's (``journalArticle``, …). Adapters map at
the edge. ``out/`` ``record.json`` (``paperful.item.v1``) is the restore unit
when moving a library between Zotero, Mendeley, and EndNote.
"""

from .bibtex import parse_bibtex, records_to_bibtex
from .endnote_xml import parse_endnote_xml, records_to_endnote_xml
from .ris import parse_ris, records_to_ris
from .types import (
    endnote_db_to_zotero,
    endnote_to_zotero,
    mendeley_to_zotero,
    zotero_to_endnote,
    zotero_to_mendeley,
)

__all__ = [
    "endnote_db_to_zotero",
    "endnote_to_zotero",
    "mendeley_to_zotero",
    "parse_bibtex",
    "parse_endnote_xml",
    "parse_ris",
    "records_to_bibtex",
    "records_to_endnote_xml",
    "records_to_ris",
    "zotero_to_endnote",
    "zotero_to_mendeley",
]
