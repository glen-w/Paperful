"""Edge cases for critique readability / lexical metrics."""

from __future__ import annotations

from paperful.critique_metrics import (
    MAX_LONG_SENTENCES,
    _finite,
    compute_readability,
    long_sentences,
)


def test_finite_filters_non_numeric():
    assert _finite(float("nan")) is None
    assert _finite(float("inf")) is None
    assert _finite(3.25) == 3.25


def test_readability_word_count_when_insufficient():
    read = compute_readability("one two")
    assert read["insufficient"] is True
    assert read["word_count"] == 2
    assert read["sentence_count"] >= 1


def test_long_sentences_reports_index_and_caps():
    long_sent = " ".join(["token"] * 65) + "."
    text = (long_sent + " ") * (MAX_LONG_SENTENCES + 3)
    rows = long_sentences(text)
    assert len(rows) == MAX_LONG_SENTENCES
    assert rows[0][0] == 1
    assert rows[0][1] >= 60
    assert rows[0][2]
