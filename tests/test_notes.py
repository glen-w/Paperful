"""Paperful-owned note classify and delete."""

from __future__ import annotations

from paperful.config import Config
from paperful.library import LibraryError
from paperful.notehtml import wrap
from paperful.notes import apply_delete, collect, identify, select
from paperful.zot import Item


def _item(key: str = "AAAA1111", title: str = "Paper") -> Item:
    return Item(
        key=key,
        item_type="journalArticle",
        title=title,
        doi=None,
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Ada",
        has_pdf=True,
    )


class _Backend:
    def __init__(self, children: dict[str, list], *, notes: dict | None = None):
        self._children = children
        self.trashed: list[tuple[str, str]] = []
        self._notes = notes or {}

    def children(self, key: str):
        return self._children.get(key, [])

    def trash_note(self, note_key: str, *, parent_key: str = ""):
        if note_key.startswith("PARENT"):
            raise LibraryError(f"{note_key} is a journalArticle, not a note.")
        self.trashed.append((note_key, parent_key))

    def raw_item(self, key: str):
        return self._notes.get(key)

    def find_collection_note_keys(self, collection_key: str, tag: str):
        return []


def test_identify_v1_and_tag_only():
    cfg = Config()
    html = wrap("<p>body</p>", note_type="summary", verb="summarize", model="qwen")
    assert identify(html, ("paperful-summary",), cfg)[0] == "summary"
    assert identify("<p>human</p>", ("paperful-found",), cfg)[0] == "attach"
    assert identify("<p>my thoughts</p>", ("todo",), cfg) is None


def test_select_except_model_only_llm_types():
    cfg = Config()
    html_old = wrap("<p>a</p>", note_type="summary", verb="summarize", model="old")
    html_new = wrap("<p>b</p>", note_type="summary", verb="summarize", model="qwen")
    attach = wrap("<p></p>", note_type="attach", verb="remarks", extra="oa")
    backend = _Backend(
        {
            "AAAA1111": [
                {
                    "key": "N1",
                    "data": {
                        "itemType": "note",
                        "note": html_old,
                        "tags": [{"tag": "paperful-summary"}],
                    },
                },
                {
                    "key": "N2",
                    "data": {
                        "itemType": "note",
                        "note": html_new,
                        "tags": [{"tag": "paperful-summary"}],
                    },
                },
                {
                    "key": "N3",
                    "data": {
                        "itemType": "note",
                        "note": attach,
                        "tags": [{"tag": "paperful-found"}],
                    },
                },
            ]
        }
    )
    hits = collect(backend, [_item()], cfg)
    kept = select(hits, types=None, model="", except_model="old", all_owned=False)
    assert {h.note_key for h in kept} == {"N2"}


def test_all_skips_human_notes():
    cfg = Config()
    html = wrap("<p>a</p>", note_type="summary", verb="summarize", model="qwen")
    backend = _Backend(
        {
            "AAAA1111": [
                {
                    "key": "N1",
                    "data": {
                        "itemType": "note",
                        "note": html,
                        "tags": [{"tag": "paperful-summary"}],
                    },
                },
                {
                    "key": "HUMAN",
                    "data": {
                        "itemType": "note",
                        "note": "<p>my reading notes</p>",
                        "tags": [],
                    },
                },
            ]
        }
    )
    hits = collect(backend, [_item()], cfg)
    matched = select(hits, types=None, model="", except_model="", all_owned=True)
    assert [h.note_key for h in matched] == ["N1"]


def test_apply_delete_refuses_parent_keys():
    backend = _Backend({})
    from paperful.notes import NoteHit

    hits = [
        NoteHit(
            note_key="PARENT",
            parent_key="",
            title="x",
            note_type="summary",
            model="",
            verb="",
            tags=(),
            standalone=False,
        ),
        NoteHit(
            note_key="N1",
            parent_key="AAAA1111",
            title="x",
            note_type="summary",
            model="qwen",
            verb="summarize",
            tags=("paperful-summary",),
            standalone=False,
        ),
    ]
    ok, errors = apply_delete(backend, hits)
    assert ok == 1 and backend.trashed == [("N1", "AAAA1111")]
    assert errors and "PARENT" in errors[0]
