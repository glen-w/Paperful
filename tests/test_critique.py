"""Local manuscript critique packs (offline)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from paperful.critique import (
    CRITIQUE_PACK_KEYS,
    SCHEMA,
    build_critique,
    dismiss_finding,
    load_dismissed,
    load_pack,
    make_finding,
    note_html,
    render_markdown,
)
from paperful.critique_extract import extract_path, stage_file
from paperful.critique_overlap import match_phrases, rank_phrases
from paperful.critique_stats import grim_possible, scan_stats
from tests.conftest import make_item

runner = CliRunner()

MANUSCRIPT = """
Abstract
We report a 47.2 percent increase in yield under the ABC protocol.

Introduction
See Figure 2. This is a systematic review of randomised trials. t(10)=2.0, p=0.90.
Mean M=1.23, N=2. Separately, p=0.04 was observed. (Smith, 1999) is cited.

Figure 1. A caption with no in-text mention.

Methods are not under a heading.

References
[1] Ada. (2001). First paper. Journal. https://doi.org/10.1000/missing
"""


def _console() -> Console:
    return Console(width=200, highlight=False, record=True)


def _docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"{body}</w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return path


def _odt(path: Path, text: str) -> Path:
    xml = (
        '<?xml version="1.0"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text><text:p>{text}</text:p></office:text></office:body>"
        "</office:document-content>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", xml)
    return path


def _pptx(path: Path, text: str) -> Path:
    slide = (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<a:t>{text}</a:t></p:sld>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
    return path


def test_grim_possible_and_impossible():
    assert grim_possible(1.50, 2, 2)
    assert not grim_possible(1.23, 2, 2)


def test_scan_stats_statcheck_and_grim():
    text = "t(10)=2.0, p=0.90. F(1, 20)=1.0, p=0.80. M=1.23, N=2. Elsewhere p=0.04 happened."
    kinds = {h.kind: h for h in scan_stats(text)}
    assert kinds["t"].consistent is False
    assert kinds["grim"].consistent is False
    assert "p_no_n" in kinds


def test_extract_plain_html_rtf_office(tmp_path: Path):
    blob = "Hello paragraph with enough letters to pass the extract minimum."
    txt = tmp_path / "a.txt"
    txt.write_text(blob, encoding="utf-8")
    doc = extract_path(txt)
    assert doc.finding == "ok" and doc.loc_kind == "paragraph"

    html = tmp_path / "a.html"
    html.write_text(f"<html><p>{blob}</p></html>", encoding="utf-8")
    assert extract_path(html).format == "html"

    rtf = tmp_path / "a.rtf"
    rtf.write_text(r"{\rtf1\ansi " + blob + r"\par}", encoding="latin-1")
    assert extract_path(rtf).finding == "ok"

    docx = _docx(tmp_path / "a.docx", [blob])
    assert extract_path(docx).format == "docx"

    odt = _odt(tmp_path / "a.odt", blob)
    assert extract_path(odt).format == "odt"

    pptx = _pptx(tmp_path / "a.pptx", blob)
    got = extract_path(pptx)
    assert got.format == "pptx" and got.loc_kind == "slide"

    bin_path = tmp_path / "x.bin"
    bin_path.write_bytes(b"\x00\x01\x02not-a-document")
    assert extract_path(bin_path).finding == "unsupported"


def test_stage_file_sanitizes_name(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text("Hello paragraph with enough letters to pass the extract minimum." * 2)
    dest = stage_file(cfg, src, name="../escape.md")
    uploads = (cfg.state_dir / "critiques" / "uploads").resolve()
    dest.resolve().relative_to(uploads)
    assert ".." not in dest.name
    assert dest.name.endswith(".md")


def test_pack_keys_and_lanes_offline(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(cfg, file_path=src, offline=True, dry_run=False)
    assert pack["schema"] == SCHEMA
    assert CRITIQUE_PACK_KEYS <= set(pack)
    assert pack["input"]["kind"] == "file"
    folder = Path(pack["pack_dir"])
    on_disk = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert CRITIQUE_PACK_KEYS <= set(on_disk)
    assert set(on_disk) & {"_findings", "_doc"} == set()
    md = (folder / "pack.md").read_text(encoding="utf-8")
    assert "## Checked" in md
    assert "grade" not in md.lower()
    assert "accept/reject" not in md.lower()
    codes = {f["code"] for f in pack["findings"]}
    assert "doi_status_skipped_offline" in codes
    assert "statcheck_p_mismatch" in codes
    assert "grim_impossible_mean" in codes
    assert "caption_not_referenced" in codes
    assert "mention_without_caption" in codes
    assert "acronym_undefined" in codes
    assert "abstract_number_missing" in codes
    assert "checklist_prisma" in codes
    assert "missing_section" in codes
    assert "text_overlap" not in codes
    assert "overlap_skipped_no_text" in codes
    assert all(f["lane"] == "checked" for f in pack["findings"])
    assert "suggested" not in (pack["counts"].get("by_lane") or {})


def test_dismiss_persists_and_hides_from_markdown(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(cfg, file_path=src, offline=True)
    cid = pack["critique_id"]
    fid = pack["findings"][0]["id"]
    dismiss_finding(cfg, cid, fid)
    assert fid in load_dismissed(cfg, cid)
    pack2 = build_critique(cfg, file_path=src, offline=True)
    dismissed = [f for f in pack2["findings"] if f["id"] == fid]
    assert dismissed and dismissed[0]["dismissed"] is True
    md = Path(pack2["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert fid not in md
    shown = render_markdown(pack2, show_dismissed=True)
    assert "dismissed" in shown


def test_apply_note_uses_critique_tag(cfg):
    pack = {
        "counts": {"findings": 1, "by_lane": {"checked": 1, "suggested": 0}},
        "findings": [
            {
                "lane": "checked",
                "code": "missing_section",
                "loc": "para 1",
                "detail": "No methods",
                "quote": "",
                "dismissed": False,
            }
        ],
    }
    html = note_html(pack)
    assert "Critique" in html
    assert "referee" in html
    assert "paperful.note.v1" in html
    assert '"type": "critique"' in html or '"type":"critique"' in html.replace(" ", "")


def test_ngram_overlap_true_and_false_positive(cfg):
    distinctive = (
        "unique tungsten carbide coating survived the salt spray chamber"
    )
    boilerplate = (
        "the authors declare that they have no conflict of interest whatsoever"
    )
    target = (
        f"Methods. {distinctive}. Also {boilerplate}. "
        "Enough extra words here so the extract is not empty."
    )
    corpus = {
        "OTHER": f"Background. {distinctive}. filler words for length here.",
        "ETH1": f"Ethics. {boilerplate}. more filler words for length here.",
        "ETH2": f"Ethics. {boilerplate}. more filler words for length here.",
        "ETH3": f"Ethics. {boilerplate}. more filler words for length here.",
    }
    ranked = rank_phrases(target, corpus, n_min=6, n_max=12, top_k=40, df_max=2)
    phrases = [p for p, _s, _d in ranked]
    assert any("tungsten carbide coating" in p for p in phrases)
    assert not any("conflict of interest" in p for p in phrases)
    hits = match_phrases(ranked, corpus, n_min=6)
    others = {h.other_key for h in hits}
    assert "OTHER" in others
    assert "ETH1" not in others


def test_overlap_checker_against_rag_text_cache(cfg, tmp_path: Path):
    from paperful.store import write_json

    distinctive = "unique tungsten carbide coating survived the salt spray chamber"
    text_dir = cfg.rag_dir / "text"
    text_dir.mkdir(parents=True)
    write_json(
        text_dir / "OTHER.json",
        {"pages": [f"Background. {distinctive}. filler words for length here."]},
    )
    src = tmp_path / "draft.md"
    src.write_text(
        f"Methods. {distinctive}. Enough extra words here so extract is not empty.\n",
        encoding="utf-8",
    )
    other = make_item(key="OTHER", title="Other paper")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        scope_items=[other],
    )
    codes = {f["code"] for f in pack["findings"]}
    assert "text_overlap" in codes
    assert "plagiarism" not in json.dumps(pack).lower()
    overlap = pack["overlap"]
    assert overlap and overlap[0]["other_key"] == "OTHER"
    assert overlap[0]["source"] == "phrase"


def test_llm_suggested_lane_drops_ungrounded_and_scores(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    payload = {
        "summary": "We report a 47.2 percent increase in yield under the ABC protocol.",
        "comments": [
            {
                "code": "methods_gap",
                "quote": "See Figure 2",
                "detail": "Figure 2 is mentioned in the introduction.",
                "unverified": False,
            },
            {
                "code": "invented",
                "quote": "lemma 12.4 is false",
                "detail": "A proof hole that is not in the excerpt.",
            },
            {
                "code": "verdict",
                "quote": "See Figure 2",
                "detail": "I would reject this paper with overall score 2.",
            },
        ],
        "questions": ["Where is the methods section?"],
    }

    def fake_chat(_client, _request):
        return json.dumps(payload)

    monkeypatch.setattr("paperful.critique_llm.chat", fake_chat)
    client = type("C", (), {"provider": "stub"})()
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_llm=True,
        llm_client=client,
    )
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    codes = {f["code"] for f in suggested}
    assert "llm_summary" in codes
    assert "methods_gap" in codes
    assert "invented" not in codes
    assert "verdict" not in codes
    assert "author_question" in codes
    assert pack["llm"] and pack["llm"].get("prompt_sha")
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Suggested" in md


def test_llm_refuses_identity_mismatch_without_force(cfg, tmp_path):
    from paperful.critique_extract import ExtractedDoc
    from paperful.critique_llm import suggested_from_llm

    doc = ExtractedDoc(text=MANUSCRIPT, format="md")
    findings = [
        make_finding(code="pdf_identity_mismatch", severity="warn", detail="mismatch")
    ]
    extra, meta = suggested_from_llm(
        cfg, doc, findings, item=None, client=object(), force=False
    )
    assert extra[0].code == "llm_refused_identity"
    assert meta is None


def test_cli_file_xor_and_json(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    both = runner.invoke(
        app,
        ["critique", "--item", "ABCD1234", "--file", str(src), "--config", str(cfg_path)],
    )
    assert both.exit_code == 1
    none = runner.invoke(app, ["critique", "--config", str(cfg_path)])
    assert none.exit_code == 1
    bad = runner.invoke(
        app,
        ["critique", "--file", str(src), "--apply", "--config", str(cfg_path)],
    )
    assert bad.exit_code == 1
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert body["command"] == "critique"
    assert body["summary"]["findings"] >= 1
    fid = body["items"][0]["id"]
    dismissed = runner.invoke(
        app,
        ["critique", "dismiss", fid, "--config", str(cfg_path), "--format", "json"],
    )
    assert dismissed.exit_code == 0, dismissed.output
    dbody = json.loads(dismissed.stdout)
    assert dbody["summary"]["id"] == fid


def test_cli_unsupported_binary(tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )
    blob = tmp_path / "x.bin"
    blob.write_bytes(b"\x00\x01")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    res = runner.invoke(
        app, ["critique", "--file", str(blob), "--config", str(cfg_path)]
    )
    assert res.exit_code == 1


def test_run_critique_apply_item_note(cfg, tmp_path, monkeypatch):
    from paperful.critique_cmd import run_critique
    from paperful.scope import ItemScope

    src = tmp_path / "paper.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    item = make_item(key="ITEM0001")
    notes: list[tuple[str, str, str]] = []

    class Backend:
        def supports_write(self) -> bool:
            return True

        def create_or_update_note(self, key, html, tag):
            notes.append((key, html, tag))

        def flush_writes(self):
            return None

    backend = Backend()

    monkeypatch.setattr(
        "paperful.cli_runtime._cfg", lambda _p: cfg
    )
    monkeypatch.setattr("paperful.cli_runtime._agent_json", lambda fmt: False)
    monkeypatch.setattr("paperful.cli_runtime._offline", lambda: True)
    monkeypatch.setattr("paperful.cli_runtime._require_manager", lambda _cfg: None)
    monkeypatch.setattr("paperful.cli_runtime._connect", lambda *a, **k: backend)
    monkeypatch.setattr(
        "paperful.cli_runtime._load_scope",
        lambda *a, **k: ItemScope(items=[item], label="Col", keys=None),
    )
    monkeypatch.setattr("paperful.cli_runtime._flush", lambda _b: None)
    monkeypatch.setattr(
        "paperful.lint.resolve_pdf_path", lambda *a, **k: src
    )
    monkeypatch.setattr(
        "paperful.critique.extract_path",
        lambda _p: __import__(
            "paperful.critique_extract", fromlist=["ExtractedDoc"]
        ).ExtractedDoc(text=MANUSCRIPT, format="pdf", finding="ok", pages=[MANUSCRIPT]),
    )
    run_critique(
        _console(),
        item=["ITEM0001"],
        file_path=None,
        collection=["Col"],
        library=False,
        dry_run=False,
        apply=True,
        llm=False,
        force=False,
        show_dismissed=False,
        config=None,
        fmt="text",
    )
    assert notes and notes[0][0] == "ITEM0001"
    assert notes[0][2] == "paperful-critique"
    assert "Critique" in notes[0][1]


def test_finding_id_stable():
    a = make_finding(code="x", severity="info", loc="p. 1", quote="hello")
    b = make_finding(code="x", severity="info", loc="p. 1", quote="hello")
    assert a.id == b.id
    assert len(a.id) == 16
