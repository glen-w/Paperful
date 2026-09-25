"""Plain-language lines: note or tag, and the three sentences."""

from paperful.dedupe import DedupeGroup
from paperful.remarks import linked_sentence, remark_duplicates, say, spare_sentence
from paperful.snowball.candidate import Candidate
from paperful.snowball.ingest import create_new
from paperful.snowball.local_cites import LocalCites
from tests.conftest import make_item


class _Notes:
    def __init__(self):
        self.notes: list[tuple[str, str, str]] = []
        self.tags: list[tuple[str, str, str]] = []

    def create_or_update_note(self, key, html, tag):
        self.notes = [row for row in self.notes if not (row[0] == key and row[2] == tag)]
        self.notes.append((key, html, tag))
        return "NOTE"

    def replace_prefixed_tag(self, key, prefix, tag):
        self.tags = [row for row in self.tags if not (row[0] == key and row[1] == prefix)]
        self.tags.append((key, prefix, tag))


def test_say_replaces_note_and_prefixed_tag():
    lib = _Notes()
    say(lib, "K", "found", "Free copy from Unpaywall.", surface="note")
    say(lib, "K", "found", "Free copy from OpenAlex.", surface="note")
    assert lib.notes == [("K", "<p>Free copy from OpenAlex.</p>", "paperful-found")]
    say(lib, "K", "found", "Free copy from Unpaywall.", surface="tag")
    say(lib, "K", "duplicate", "Same paper as Smith 2019.", surface="tag")
    say(lib, "K", "found", "Downloaded through your library login.", surface="tag")
    assert ("K", "paperful duplicate:", "paperful duplicate: Same paper as Smith 2019.") in lib.tags
    found = [row for row in lib.tags if row[1] == "paperful found:"]
    assert found == [
        ("K", "paperful found:", "paperful found: Downloaded through your library login.")
    ]
    say(lib, "K", "found", "Free copy from Unpaywall.", surface="off")
    assert len(lib.notes) == 1


def test_spare_sentence_names_the_keeper():
    assert (
        spare_sentence(make_item(first_author="Smith", year=2019, has_pdf=True))
        == "Same paper as Smith 2019, which already has the PDF."
    )
    assert (
        spare_sentence(make_item(first_author="Smith", year=2019, has_pdf=False))
        == "Same paper as Smith 2019."
    )


def test_remark_duplicates_skips_held_groups():
    lib = _Notes()
    keeper = make_item(key="KEEP", first_author="Smith", year=2019, has_pdf=True)
    spare = make_item(key="DROP", doi="10.1000/other")
    groups = [
        DedupeGroup("high_doi", "doi", "KEEP", ["DROP"], False, False),
        DedupeGroup("high_doi", "divergent", "KEEP", ["DROP"], True, False),
    ]
    remark_duplicates(lib, groups, [keeper, spare], surface="note")
    assert len(lib.notes) == 1
    assert "Smith 2019" in lib.notes[0][1]
    assert lib.notes[0][0] == "DROP"


def test_linked_sentence_cites_and_seeds():
    assert linked_sentence(hop=0, direction="refs", overlap=1, cite_count=4, library=False) == (
        "Cited by 4 papers in this collection."
    )
    assert linked_sentence(hop=0, direction="refs", overlap=1, cite_count=1, library=True) == (
        "Cited by 1 paper in your library."
    )
    assert (
        linked_sentence(hop=1, direction="cites", overlap=3, cite_count=0, library=False)
        == "Cites 3 of the papers you started from."
    )
    assert (
        linked_sentence(hop=1, direction="refs", overlap=2, cite_count=4, library=False)
        == "Cited by 4 papers in this collection. In the bibliography of 2 of the papers you started from."
    )
    assert linked_sentence(hop=1, direction="both", overlap=1, cite_count=0, library=False) == ""
    assert (
        linked_sentence(hop=1, direction="both", overlap=2, cite_count=0, library=False)
        == "Linked to 2 of the papers you started from."
    )


class _Create:
    def __init__(self):
        self.notes: list[tuple[str, str]] = []

    def ensure_collection_path(self, path):
        return "COL"

    def create_parent(self, payload):
        return "NEW"

    def create_or_update_note(self, key, html, tag):
        self.notes.append((tag, html))
        return "N"


def _row(**kwargs):
    base = dict(
        run_id="r",
        seed={"type": "doi", "value": "10.1/seed"},
        hop=1,
        direction="refs",
        ids={"doi": "10.1/new", "openalex": "W9"},
        biblio={"title": "New", "year": 2021, "authors": ["Ada Lovelace"], "overlap": 1},
        why="ref",
        status="new",
        provenance={},
        gate="auto",
    )
    base.update(kwargs)
    return Candidate(**base)


def test_create_new_writes_collection_cites_not_a_single_seed():
    lib = _Create()
    index = LocalCites(by_openalex={"W9": {"KEEP"}}, library=False)
    create_new(lib, [_row()], "Inbox", note_provenance=False, local_cites=index)
    assert lib.notes == [("paperful-linked", "<p>Cited by 1 paper in this collection.</p>")]

    lib.notes.clear()
    create_new(
        lib,
        [_row(biblio={"title": "New", "year": 2021, "authors": ["Ada Lovelace"], "overlap": 2})],
        "Inbox",
        note_provenance=False,
        local_cites=LocalCites(),
    )
    assert "bibliography of 2" in lib.notes[0][1]
    assert "Cited by" not in lib.notes[0][1]
