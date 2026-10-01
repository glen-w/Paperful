"""Chunking: size, overlap, sections, and page ranges."""

from __future__ import annotations

from paperful.rag.chunk import Chunk, chunk_pages, embed_text


def _sentences(n: int, word: str = "krill") -> str:
    return " ".join(f"Sentence {i} is about {word} and the open ocean." for i in range(n))


def test_short_document_is_one_chunk_on_its_page():
    (chunk,) = chunk_pages([_sentences(4)])
    assert chunk.index == 0 and chunk.section is None
    assert (chunk.page_start, chunk.page_end) == (1, 1)
    assert chunk.text.startswith("Sentence 0") and chunk.text.endswith("ocean.")


def test_tiny_text_is_dropped_unless_min_chars_is_lowered():
    assert chunk_pages(["Too short."]) == []
    assert len(chunk_pages(["Too short."], min_chars=1)) == 1
    assert chunk_pages([]) == [] and chunk_pages(["", "  "]) == []


def test_chunks_respect_the_size_limit_and_cover_the_text():
    text = _sentences(120)
    chunks = chunk_pages([text], chunk_chars=600, overlap=100)
    assert len(chunks) > 5
    assert all(len(c.text) <= 600 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for i in range(120):
        assert any(f"Sentence {i} is" in c.text for c in chunks)


def test_overlap_repeats_whole_closing_sentences():
    chunks = chunk_pages([_sentences(60)], chunk_chars=500, overlap=120)
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.text.startswith("Sentence ")
        first_sentence = cur.text.split(".")[0] + "."
        assert first_sentence in prev.text


def test_zero_overlap_does_not_repeat_text():
    chunks = chunk_pages([_sentences(60)], chunk_chars=500, overlap=0)
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.text.split(".")[0] + "." not in prev.text


def test_page_ranges_follow_the_text():
    pages = [_sentences(8, "alpha"), _sentences(8, "bravo"), _sentences(8, "charlie")]
    chunks = chunk_pages(pages, chunk_chars=400, overlap=0)
    for chunk in chunks:
        words = {w for w in ("alpha", "bravo", "charlie") if w in chunk.text}
        expected = {"alpha": 1, "bravo": 2, "charlie": 3}
        assert chunk.page_start == min(expected[w] for w in words)
        assert chunk.page_end == max(expected[w] for w in words)
    assert chunks[0].page_start == 1 and chunks[-1].page_end == 3


def test_a_chunk_spanning_a_page_break_reports_both_pages():
    (chunk,) = chunk_pages([_sentences(3, "alpha"), _sentences(3, "bravo")])
    assert (chunk.page_start, chunk.page_end) == (1, 2)


def test_headings_start_new_chunks_and_label_them():
    page = "\n".join(
        [
            _sentences(3, "preamble"),
            "",
            "1. Introduction",
            "",
            _sentences(3, "intro"),
            "",
            "METHODS AND DATA",
            "",
            _sentences(3, "methods"),
            "",
            "Results",
            "",
            _sentences(3, "results"),
        ]
    )
    chunks = chunk_pages([page])
    assert [c.section for c in chunks] == [
        None,
        "1. Introduction",
        "METHODS AND DATA",
        "Results",
    ]
    assert "intro" in chunks[1].text and "methods" not in chunks[1].text
    assert "Introduction" not in chunks[1].text


def test_markdown_headings_from_docling_are_sections():
    page = f"## Background\n\n{_sentences(3)}\n\n### 2.1 Sampling\n\n{_sentences(3, 'nets')}"
    chunks = chunk_pages([page])
    assert [c.section for c in chunks] == ["Background", "2.1 Sampling"]


def test_overlap_does_not_cross_a_heading():
    page = "\n".join(
        [_sentences(12, "alpha"), "", "Discussion", "", _sentences(12, "bravo")]
    )
    chunks = chunk_pages([page], chunk_chars=500, overlap=120)
    first_of_discussion = next(c for c in chunks if c.section == "Discussion")
    assert "alpha" not in first_of_discussion.text


def test_running_page_headers_are_not_sections():
    pages = [f"KRUGER AND DUNNING\n\n{_sentences(4, f'p{i}')}" for i in range(4)]
    chunks = chunk_pages(pages)
    assert {c.section for c in chunks} == {None}


def test_sentences_and_numbers_are_not_headings():
    page = "\n".join(
        [
            _sentences(3),
            "",
            "12. Smith J, Chen L. Krill dynamics in the Southern Ocean, a long reference entry.",
            "",
            "5 U +2J",
            "",
            _sentences(3),
        ]
    )
    assert {c.section for c in chunks_of(page)} == {None}


def chunks_of(page: str) -> list[Chunk]:
    return chunk_pages([page])


def test_hyphenated_line_breaks_are_joined():
    page = "The meso-\npelagic zone is poorly sampled. " + _sentences(3)
    (chunk,) = chunk_pages([page])
    assert "mesopelagic zone" in chunk.text


def test_one_unbroken_run_is_hard_cut():
    chunks = chunk_pages(["x" * 1000], chunk_chars=300, overlap=0)
    assert [len(c.text) for c in chunks] == [300, 300, 300, 100]


def test_embed_text_adds_title_and_section_but_not_to_the_stored_text():
    chunk = Chunk(index=0, text="Body.", section="Methods", page_start=1, page_end=1)
    assert embed_text(chunk, "Krill at night") == "Krill at night\n\nMethods\n\nBody."
    bare = Chunk(index=0, text="Body.", section=None, page_start=1, page_end=1)
    assert embed_text(bare, "") == "Body."
