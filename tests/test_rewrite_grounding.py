"""Grounding freeze, cite case, uniqueness, sidecar offset rebind."""

from __future__ import annotations

from paperful.rewrite_grounding import (
    apply_freeze,
    cites_ok,
    freeze_preserved,
    freeze_tokens,
    placeholders_in,
    thaw,
)
from paperful.rewrite_llm import edit_is_grounded
from paperful.rewrite_plan import RewriteEdit
from paperful.rewrite_render import apply_to_text


def test_single_digit_change_is_skipped():
    hay = "We enrolled n = 7 participants in the trial."
    assert (
        edit_is_grounded(
            kind="replace",
            quote="n = 7 participants",
            replacement="n = 8 participants",
            body="",
            hay=hay,
        )
        == "no_evidence"
    )


def test_author_year_not_allowed_as_new_cite_shape():
    hay = "The 2020 survey was limited. Later work expanded the sample."
    frozen, mapping = freeze_tokens(hay + " Doe (2020) is absent.")
    selected = apply_freeze("Later work expanded the sample.", mapping)
    reply = apply_freeze("Later work expanded the sample (Doe (2020)).", mapping)
    # New author–year is a new frozen token, not in selected.
    assert freeze_preserved(
        selected_frozen=selected, reply=reply, mapping=mapping
    ) is False


def test_pandoc_new_key_skipped():
    hay = "See the earlier review for context."
    assert (
        edit_is_grounded(
            kind="replace",
            quote="the earlier review",
            replacement="the earlier review [@newkey]",
            body="",
            hay=hay,
        )
        == "no_evidence"
    )


def test_capitalised_latex_key_not_false_skipped():
    hay = "See \\cite{Smith2020} for the treaty text."
    assert (
        edit_is_grounded(
            kind="replace",
            quote="See \\cite{Smith2020} for the treaty text.",
            replacement="See \\cite{Smith2020} for the treaty text.",
            body="",
            hay=hay,
        )
        is None
    )
    assert cites_ok("\\cite{Smith2020}", hay.lower())


def test_non_unique_llm_quote_skipped():
    hay = "The word might appear twice: it might rain."
    assert (
        edit_is_grounded(
            kind="replace",
            quote="might",
            replacement="may",
            body="",
            hay=hay,
        )
        == "no_unique_span"
    )


def test_insert_and_delete_grounding():
    hay = "Count 12 ships. End of the paragraph here."
    assert (
        edit_is_grounded(
            kind="insert",
            quote="End of the paragraph here",
            replacement="\\cite{NewKey}",
            body="",
            hay=hay,
        )
        == "no_evidence"
    )
    assert (
        edit_is_grounded(
            kind="insert",
            quote="End of the paragraph here",
            replacement=" 99 more.",
            body="",
            hay=hay,
        )
        == "no_evidence"
    )
    assert (
        edit_is_grounded(
            kind="delete",
            quote="Count 12 ships.",
            replacement="",
            body="",
            hay=hay,
        )
        is None
    )


def test_placeholder_round_trip_keeps_tokens():
    text = "There were 7 fish in Figure 3 (Doe (2020)) and \\cite{Smith2020}."
    frozen, mapping = freeze_tokens(text)
    assert "«PF" in frozen
    assert thaw(frozen, mapping) == text
    selected = apply_freeze("There were 7 fish in Figure 3", mapping)
    assert freeze_preserved(
        selected_frozen=selected, reply=selected, mapping=mapping
    )
    dropped = selected
    for token in placeholders_in(selected):
        dropped = dropped.replace(token, "X")
        break
    assert dropped != selected
    assert not freeze_preserved(
        selected_frozen=selected, reply=dropped, mapping=mapping
    )


def test_sidecar_rebands_to_unique_model_quote():
    body = "AAA te BBB model-quote appears here CCC"
    edit = RewriteEdit(
        kind="replace",
        finding_ids=["x"],
        area="style",
        quote="model-quote",
        replacement="REPLACED",
        start=body.index("te"),
        end=body.index("te") + 2,
    )
    out = apply_to_text(body, [edit])
    assert "REPLACEDte" not in out
    assert "REPLACED" in out
    assert "model-quote" not in out
