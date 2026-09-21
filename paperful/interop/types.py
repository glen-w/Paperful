"""Zotero item types are canonical. Map to Mendeley / EndNote at the adapter edge."""

from __future__ import annotations

# Mendeley document.type values from GET /document_types (dev.mendeley.com, 2026-09-21).
_ZOTERO_TO_MENDELEY: dict[str, str] = {
    "journalArticle": "journal",
    "book": "book",
    "bookSection": "book_section",
    "conferencePaper": "conference_proceedings",
    "report": "report",
    "thesis": "thesis",
    "webpage": "web_page",
    "magazineArticle": "magazine_article",
    "newspaperArticle": "newspaper_article",
    "patent": "patent",
    "statute": "statute",
    "hearing": "hearing",
    "tvBroadcast": "television_broadcast",
    "encyclopediaArticle": "encyclopedia_article",
    "case": "case",
    "film": "film",
    "bill": "bill",
    "computerProgram": "computer_program",
    "preprint": "working_paper",
    "manuscript": "working_paper",
    "blogPost": "web_page",
    "forumPost": "web_page",
    "document": "generic",
    "dictionaryEntry": "generic",
    "email": "generic",
    "instantMessage": "generic",
    "interview": "generic",
    "letter": "generic",
    "map": "generic",
    "podcast": "generic",
    "presentation": "generic",
    "radioBroadcast": "television_broadcast",
    "standard": "generic",
    "videoRecording": "film",
    "audioRecording": "generic",
    "artwork": "generic",
    "dataset": "generic",
}

_MENDELEY_TO_ZOTERO: dict[str, str] = {
    "journal": "journalArticle",
    "book": "book",
    "generic": "document",
    "book_section": "bookSection",
    "conference_proceedings": "conferencePaper",
    "working_paper": "preprint",
    "report": "report",
    "web_page": "webpage",
    "thesis": "thesis",
    "magazine_article": "magazineArticle",
    "statute": "statute",
    "patent": "patent",
    "newspaper_article": "newspaperArticle",
    "computer_program": "computerProgram",
    "hearing": "hearing",
    "television_broadcast": "tvBroadcast",
    "encyclopedia_article": "encyclopediaArticle",
    "case": "case",
    "film": "film",
    "bill": "bill",
}

# EndNote XML <ref-type name="…">N</ref-type>. Numbers from EndNote's XML DTD
# as used by Zotero's EndNote XML translator; unknown types fall back to Generic.
_ZOTERO_TO_ENDNOTE: dict[str, tuple[int, str]] = {
    "journalArticle": (17, "Journal Article"),
    "book": (6, "Book"),
    "bookSection": (5, "Book Section"),
    "conferencePaper": (47, "Conference Paper"),
    "report": (27, "Report"),
    "thesis": (32, "Thesis"),
    "webpage": (12, "Web Page"),
    "magazineArticle": (19, "Magazine Article"),
    "newspaperArticle": (23, "Newspaper Article"),
    "patent": (25, "Patent"),
    "statute": (31, "Statute"),
    "hearing": (21, "Hearing"),
    "tvBroadcast": (21, "Film or Broadcast"),
    "encyclopediaArticle": (16, "Encyclopedia"),
    "case": (8, "Case"),
    "film": (21, "Film or Broadcast"),
    "bill": (31, "Bill"),
    "computerProgram": (9, "Computer Program"),
    "preprint": (27, "Report"),
    "manuscript": (36, "Unpublished Work"),
    "document": (13, "Generic"),
    "blogPost": (12, "Web Page"),
    "forumPost": (12, "Web Page"),
    "dictionaryEntry": (14, "Dictionary"),
    "presentation": (13, "Generic"),
    "dataset": (13, "Generic"),
    "podcast": (21, "Film or Broadcast"),
    "videoRecording": (21, "Film or Broadcast"),
    "audioRecording": (4, "Audiovisual Material"),
    "artwork": (2, "Artwork"),
    "map": (20, "Map"),
    "interview": (22, "Interview"),
    "letter": (13, "Generic"),
    "email": (13, "Generic"),
    "standard": (13, "Generic"),
    "radioBroadcast": (21, "Film or Broadcast"),
}

_ENDNOTE_NAME_TO_ZOTERO: dict[str, str] = {
    "journal article": "journalArticle",
    "book": "book",
    "book section": "bookSection",
    "conference paper": "conferencePaper",
    "conference proceedings": "conferencePaper",
    "report": "report",
    "thesis": "thesis",
    "web page": "webpage",
    "electronic article": "webpage",
    "magazine article": "magazineArticle",
    "newspaper article": "newspaperArticle",
    "patent": "patent",
    "statute": "statute",
    "bill": "bill",
    "hearing": "hearing",
    "film or broadcast": "film",
    "encyclopedia": "encyclopediaArticle",
    "case": "case",
    "computer program": "computerProgram",
    "generic": "document",
    "unpublished work": "manuscript",
    "dictionary": "dictionaryEntry",
    "artwork": "artwork",
    "audiovisual material": "audioRecording",
    "map": "map",
    "interview": "interview",
    "grant": "document",
    "government document": "report",
}

_ENDNOTE_NUM_TO_ZOTERO: dict[int, str] = {
    num: zot for zot, (num, _name) in _ZOTERO_TO_ENDNOTE.items()
}

# SQLite ``refs.reference_type`` (EndNote 20/21). Distinct from XML <ref-type>
# numbers: journal is 0 in the database and 17 in XML. Using the XML map on a
# live library mislabels Journal Article as Bill.
_ENDNOTE_DB_NUM_TO_ZOTERO: dict[int, str] = {
    0: "journalArticle",
    1: "book",
    2: "thesis",
    3: "conferencePaper",
    4: "letter",
    5: "newspaperArticle",
    6: "computerProgram",
    7: "bookSection",
    8: "magazineArticle",
    9: "book",
    10: "report",
    11: "map",
    12: "audioRecording",
    13: "artwork",
    15: "patent",
    16: "webpage",
    17: "bill",
    18: "case",
    19: "hearing",
    20: "manuscript",
    21: "film",
    22: "statute",
    26: "document",
    31: "document",
    33: "conferencePaper",
    48: "dataset",
    53: "encyclopediaArticle",
}

# RIS TY → Zotero. Subset of the RIS.js translator; unknown TY → document.
_RIS_TO_ZOTERO: dict[str, str] = {
    "JOUR": "journalArticle",
    "JFULL": "journalArticle",
    "MGZN": "magazineArticle",
    "NEWS": "newspaperArticle",
    "BOOK": "book",
    "CHAP": "bookSection",
    "CONF": "conferencePaper",
    "CPAPER": "conferencePaper",
    "THES": "thesis",
    "RPRT": "report",
    "REPORT": "report",
    "PAT": "patent",
    "ELEC": "webpage",
    "ICOMM": "webpage",
    "COMP": "computerProgram",
    "ADVS": "videoRecording",
    "SOUND": "audioRecording",
    "ART": "artwork",
    "CASE": "case",
    "BILL": "bill",
    "HEAR": "hearing",
    "STAT": "statute",
    "MAP": "map",
    "GEN": "document",
    "UNPB": "manuscript",
    "DATA": "dataset",
}

_ZOTERO_TO_RIS: dict[str, str] = {
    "journalArticle": "JOUR",
    "magazineArticle": "MGZN",
    "newspaperArticle": "NEWS",
    "book": "BOOK",
    "bookSection": "CHAP",
    "conferencePaper": "CONF",
    "thesis": "THES",
    "report": "RPRT",
    "patent": "PAT",
    "webpage": "ELEC",
    "blogPost": "ICOMM",
    "forumPost": "ICOMM",
    "computerProgram": "COMP",
    "videoRecording": "ADVS",
    "audioRecording": "SOUND",
    "artwork": "ART",
    "case": "CASE",
    "bill": "BILL",
    "hearing": "HEAR",
    "statute": "STAT",
    "map": "MAP",
    "manuscript": "UNPB",
    "preprint": "GEN",
    "dataset": "DATA",
    "document": "GEN",
}

_BIBTEX_TO_ZOTERO: dict[str, str] = {
    "article": "journalArticle",
    "book": "book",
    "inbook": "bookSection",
    "incollection": "bookSection",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "unpublished": "manuscript",
    "misc": "document",
    "online": "webpage",
    "webpage": "webpage",
    "patent": "patent",
    "dataset": "dataset",
    "preprint": "preprint",
}

_ZOTERO_TO_BIBTEX: dict[str, str] = {
    "journalArticle": "article",
    "book": "book",
    "bookSection": "incollection",
    "conferencePaper": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "manuscript": "unpublished",
    "webpage": "online",
    "blogPost": "online",
    "patent": "patent",
    "dataset": "dataset",
    "preprint": "misc",
    "document": "misc",
}


def zotero_to_mendeley(item_type: str) -> str:
    return _ZOTERO_TO_MENDELEY.get(item_type or "", "generic")


def mendeley_to_zotero(doc_type: str) -> str:
    return _MENDELEY_TO_ZOTERO.get((doc_type or "").strip().lower(), "document")


def zotero_to_endnote(item_type: str) -> tuple[int, str]:
    return _ZOTERO_TO_ENDNOTE.get(item_type or "", (13, "Generic"))


def endnote_to_zotero(name: str | None, number: int | None = None) -> str:
    """Map EndNote XML ``<ref-type name>`` / XML numbers to a Zotero type.

    Do not pass SQLite ``reference_type`` here — those ids use
    :func:`endnote_db_to_zotero`.
    """
    if name:
        mapped = _ENDNOTE_NAME_TO_ZOTERO.get(name.strip().lower())
        if mapped:
            return mapped
    if number is not None:
        return _ENDNOTE_NUM_TO_ZOTERO.get(int(number), "document")
    return "document"


def endnote_db_to_zotero(number: int | None) -> str:
    """Map EndNote SQLite ``refs.reference_type`` to a Zotero type."""
    if number is None:
        return "document"
    try:
        return _ENDNOTE_DB_NUM_TO_ZOTERO.get(int(number), "document")
    except (TypeError, ValueError):
        return "document"


def ris_to_zotero(ty: str) -> str:
    return _RIS_TO_ZOTERO.get((ty or "").strip().upper(), "document")


def zotero_to_ris(item_type: str) -> str:
    return _ZOTERO_TO_RIS.get(item_type or "", "GEN")


def bibtex_to_zotero(entry_type: str) -> str:
    return _BIBTEX_TO_ZOTERO.get((entry_type or "").strip().lower(), "document")


def zotero_to_bibtex(item_type: str) -> str:
    return _ZOTERO_TO_BIBTEX.get(item_type or "", "misc")
