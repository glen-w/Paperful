"""Rewrite copy sanitizer: invisible Unicode, C2PA zip parts, token swaps."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from paperful.hidden_text import fold_homoglyphs, strip_invisible
from paperful.rewrite_check import _tells_regressed
from paperful.rewrite_sanitize import perturb_trackers, strip_c2pa_zip


def test_strip_invisible_and_tags():
    raw = "Hello\u200b world\ufeff"
    raw += "\U000e0020"
    clean, n = strip_invisible(raw)
    assert "Hello world" in clean.replace("  ", " ")
    assert n >= 2
    assert "\u200b" not in clean


def test_fold_mixed_script_homoglyph():
    # Cyrillic а in "раper" mix
    token = "pаper"  # Latin p, Cyrillic а, Latin per
    out, n = fold_homoglyphs(f"the {token} is wet")
    assert n == 1
    assert "paper" in out


def test_perturb_trackers_is_reproducible():
    text = "The storm moved towards the island amongst the reefs whilst surveys continued onwards."
    a, n1 = perturb_trackers(text, rate=1.0, seed=7)
    b, n2 = perturb_trackers(text, rate=1.0, seed=7)
    assert a == b
    assert n1 == n2
    assert n1 > 0
    assert "toward" in a or "among" in a or "while" in a


def test_strip_c2pa_zip_part(tmp_path: Path):
    dest = tmp_path / "tracked.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:t>hi</w:t>")
        zf.writestr("word/c2pa/manifest.json", '{"c2pa": true}')
    dest.write_bytes(buf.getvalue())
    stats = strip_c2pa_zip(dest)
    assert stats["c2pa_parts"] >= 1
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
    assert not any("c2pa" in n.lower() for n in names)
    assert "word/document.xml" in names


def test_tell_regression_detects_new_delve():
    assert _tells_regressed("The basin mixed.", "We delve into the basin.")
    assert not _tells_regressed("We delve into the basin.", "We delve into the basin.")


def test_perturb_preserves_frozen_numbers():
    text = 'The rate was 12.5 towards the "quoted towards" coast.'
    out, _n = perturb_trackers(text, rate=1.0, seed=3)
    assert "12.5" in out
    assert '"quoted towards"' in out or "quoted towards" in out


def test_strip_c2pa_pdf_noop_when_absent(tmp_path: Path):
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "tracked.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    from paperful.rewrite_sanitize import strip_c2pa_pdf

    assert strip_c2pa_pdf(path)["c2pa_pdf"] == 0


def test_tracker_prose_rejects_new_numbers(monkeypatch):
    from paperful.config import Config
    from paperful.rewrite_sanitize import tracker_prose_paragraph

    cfg = Config()
    cfg.llm_model = "stub"
    monkeypatch.setattr("paperful.llm.client.prompt_exceeds_ctx", lambda *a, **k: False)
    monkeypatch.setattr("paperful.llm.client.ctx_tokens_for", lambda *a, **k: 256)
    monkeypatch.setattr(
        "paperful.llm.client.chat",
        lambda *_a, **_k: '{"paragraph": "The rate was «PFN1» towards 99."}',
    )
    out = tracker_prose_paragraph(
        cfg, "The rate was 12.5 towards the coast.", client=object(), timeout_s=5
    )
    assert out is None
