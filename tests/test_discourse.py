"""Academic discourse checker (not an authorship detector)."""

from paperful.peer_review_checks.discourse import scan_discourse
from paperful.peer_review_extract import ExtractedDoc
from paperful.rewrite_areas import DISCOURSE_CODES, STYLE_COMMENT_CODES, SKIP_CODES


def test_discourse_codes_are_style_comments_except_chatbot():
    assert DISCOURSE_CODES <= {
        "weasel_citation",
        "hype_copy",
        "chatbot_residue",
        "marketing_closer",
        "discourse_scaffold",
    }
    assert "chatbot_residue" not in STYLE_COMMENT_CODES
    assert "ai_tell" in SKIP_CODES
    assert "weasel_citation" not in SKIP_CODES


def test_weasel_without_cite_and_hype_and_chatbot():
    text = (
        "Studies show the effect is large. This groundbreaking result is clear. "
        "In conclusion, the basin is mixed. "
        "The takeaway is that managers should act."
    )
    doc = ExtractedDoc(text=text, format="md", paragraphs=text.split(". "))
    rows = scan_discourse(text, doc)
    codes = {r.code for r in rows}
    assert "weasel_citation" in codes
    assert "hype_copy" in codes
    assert "chatbot_residue" in codes
    assert "marketing_closer" in codes
    chat = next(r for r in rows if r.code == "chatbot_residue")
    assert chat.extra.get("drop") is True


def test_weasel_skipped_when_cite_nearby():
    text = "Studies show (Smith, 2020) the effect is large in the basin."
    rows = scan_discourse(text)
    assert not any(r.code == "weasel_citation" for r in rows)
