"""Direct-quotation guards for critique prose, Vale, and LLM comments."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from paperful.critique_direct_quotes import (
    elide_direct_quotes,
    line_column_span_in_direct_quote,
    snippet_in_direct_quote,
    span_in_direct_quote,
)
from paperful.critique_llm import findings_from_comments
from paperful.critique_vale import _finding_from_alert
from paperful.critique_extract import ExtractedDoc
from tests.test_critique import build_critique


def test_span_in_smart_quotes():
    text = 'She said \u201cwe might perhaps utilize this approach\u201d in the interview.'
    start = text.index("utilize")
    assert span_in_direct_quote(text, start, start + len("utilize"))
    assert not span_in_direct_quote(text, 0, 3)


def test_block_quote_line():
    text = "Our view is clear.\n> They utilize very many terms here.\nWe disagree."
    assert snippet_in_direct_quote(text, "utilize")
    assert not snippet_in_direct_quote(text, "Our view")


def test_elide_preserves_newlines():
    text = 'Before \u201cutilize\u201d after.'
    out = elide_direct_quotes(text)
    assert "\n" not in text or "\n" in out
    assert "utilize" not in out.replace(" ", "")
    assert out.startswith("Before ")


def test_snippet_only_in_quote():
    text = 'He wrote \u201cutilize\u201d and we prefer use.'
    assert snippet_in_direct_quote(text, "utilize")
    both = 'We utilize tools. They said \u201cutilize\u201d again.'
    assert not snippet_in_direct_quote(both, "utilize")
    text2 = 'He wrote \u201cwe utilize this\u201d only.'
    assert snippet_in_direct_quote(text2, "utilize")


def test_vale_alert_inside_quote_dropped():
    doc = ExtractedDoc(
        text='Intro \u201cplease utilize this\u201d end.',
        format="txt",
    )
    alert = {
        "Check": "House.Terms",
        "Severity": "error",
        "Match": "utilize",
        "Message": "Use 'use'.",
        "Line": 1,
        "Span": [9, 16],
    }
    assert _finding_from_alert(doc, alert) is None


def test_vale_alert_outside_quote_kept():
    doc = ExtractedDoc(text="Please utilize this protocol.", format="txt")
    alert = {
        "Check": "House.Terms",
        "Severity": "error",
        "Match": "utilize",
        "Message": "Use 'use'.",
        "Line": 1,
        "Span": [8, 15],
    }
    row = _finding_from_alert(doc, alert)
    assert row is not None
    assert row.code == "vale_house_terms"


def test_line_column_span_in_direct_quote():
    text = "aa \u201cutilize\u201d bb"
    assert line_column_span_in_direct_quote(text, 1, 5, 12)
    assert not line_column_span_in_direct_quote(text, 1, 1, 2)


def test_llm_drops_comments_on_quoted_span():
    hay = 'Methods: \u201cwe might perhaps utilize the old kit\u201d was noted.'
    rows = findings_from_comments(
        [{"quote": "utilize the old kit", "detail": "Tighten wording here."}],
        hay=hay,
        reviewer_id="t",
    )
    assert rows == []


def test_prose_skips_long_sentence_in_quote(cfg, tmp_path: Path):
    words = " ".join(["word"] * 45)
    body = f'Introduction.\n\n\u201c{words}.\u201d\n\nShort closing.'
    path = tmp_path / "quote.txt"
    path.write_text(body, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "long_sentence" not in codes


def test_vale_integration_skips_quoted_match(cfg, tmp_path: Path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("MinAlertLevel = suggestion\n", encoding="utf-8")
    cfg.critique_vale_config = ini
    alerts = [
        {
            "Check": "House.Terms",
            "Severity": "error",
            "Match": "utilize",
            "Message": "Use 'use'.",
            "Line": 1,
            "Span": [10, 17],
        },
    ]
    payload = json.dumps({"manuscript.txt": alerts})

    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    path = tmp_path / "vale.txt"
    path.write_text(
        f'Note \u201cplease utilize this\u201d here.\n',
        encoding="utf-8",
    )
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    vale_rows = [f for f in pack["findings"] if f.get("source") == "vale"]
    assert not any(f["code"] == "vale_house_terms" for f in vale_rows)
