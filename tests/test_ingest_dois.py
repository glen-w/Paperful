"""DOI list ingest: dry-run, exists, held, idempotent apply."""

from paperful.identity import LibraryFingerprint
from paperful.ingest_dois import (
    apply_creates,
    classify_rows,
    parse_doi_lines,
    dois_from_refs_pack,
    ingest_tags,
)
from paperful.resolve import WorkMeta
from tests.conftest import make_item


def _work(doi: str, title: str, year: int = 2020) -> WorkMeta:
    return WorkMeta(doi=doi, title=title, year=year, source="crossref", work_type="journal-article")


def test_parse_doi_lines_comments_and_urls():
    text = """
# skip
10.1000/a
https://doi.org/10.1000/b  # comment
10.1000/a
"""
    assert parse_doi_lines(text) == ["10.1000/a", "10.1000/b"]


def test_classify_exists_unresolved_held_create():
    fp = LibraryFingerprint.from_items(
        [
            make_item(key="E", doi="10.1000/exists", title="Existing work title here", year=2019),
            make_item(key="T", doi="10.1000/other", title="Shared title about oceans", year=2020),
        ]
    )
    works = {
        "10.1000/exists": _work("10.1000/exists", "Existing work title here", 2019),
        "10.1000/new": _work("10.1000/new", "Brand new paper about oceans", 2021),
        "10.1000/clash": _work("10.1000/clash", "Shared title about oceans", 2020),
    }

    def resolve(doi):
        return works.get(doi)

    batch = classify_rows(
        ["10.1000/exists", "10.1000/missing", "10.1000/new", "10.1000/clash"],
        fp,
        resolve=resolve,
    )
    by_doi = {r.doi: r for r in batch.rows}
    assert by_doi["10.1000/exists"].status == "exists"
    assert by_doi["10.1000/missing"].status == "unresolved"
    assert by_doi["10.1000/new"].status == "create"
    assert by_doi["10.1000/clash"].status == "held"


def test_apply_then_reclassify_is_exists():
    created: list[str] = []

    class Backend:
        def ensure_collection_path(self, path):
            return "C1"

        def create_parent(self, payload):
            created.append(payload["DOI"])
            return "NEW1"

    fp = LibraryFingerprint.from_items([])
    doi = "10.1000/new"
    work = _work(doi, "Brand new paper about oceans", 2021)
    batch = classify_rows([doi], fp, resolve=lambda d: work)
    apply_creates(Backend(), batch, "BBNJ", works={doi: work}, tags=["from-list"])
    assert created == [doi]
    assert batch.rows[0].status == "created"
    fp2 = LibraryFingerprint.from_items(
        [make_item(key="NEW1", doi=doi, title=work.title, year=work.year)]
    )
    again = classify_rows([doi], fp2, resolve=lambda d: work)
    assert again.rows[0].status == "exists"


def test_dois_from_refs_pack(tmp_path):
    import json

    pack = {
        "schema": "paperful.refs_gap.pack.v1",
        "rows": [
            {"doi": "10.1000/a", "suggested_action": "ingest-dois", "already_exists": False},
            {"doi": "10.1000/b", "suggested_action": "skip", "already_exists": True},
        ],
    }
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    assert dois_from_refs_pack(path) == ["10.1000/a"]


def test_ingest_tags_include_file_stem(tmp_path):
    path = tmp_path / "bbnj-seed.txt"
    path.write_text("x")
    tags = ingest_tags(cli_tags=["mine"], default_tags=["ingest"], from_file=path)
    assert tags == ["ingest", "mine", "from-bbnj-seed"]
