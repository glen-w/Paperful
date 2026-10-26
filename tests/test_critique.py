"""Local manuscript critique packs (offline)."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from paperful.config import CritiqueReviewer
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
from paperful.critique_overlap import collapse_nested_hits, match_phrases, rank_phrases
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
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<a:t>{text}</a:t></p:sld>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
    return path


def test_grim_possible_and_impossible():
    assert grim_possible(1.50, 2, 2)
    assert not grim_possible(1.23, 2, 2)


def test_scan_stats_statcheck_and_grim():
    text = (
        "t(10)=2.0, p=0.90. F(1, 20)=1.0, p=0.80. M=1.23, N=2. "
        + ("padding " * 40)
        + "Elsewhere p=0.04 happened."
    )
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
    assert "## Counts" in md
    assert "overall score" not in md.lower()
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
    assert "readability_summary" in codes
    assert "metrics" in pack
    assert pack["metrics"]["readability"]["word_count"] is not None
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    assert suggested
    assert {f["code"] for f in suggested} <= {"ai_tells_abstain", "ai_tell", "ai_tell_summary"}


def test_dismiss_persists_and_hides_from_markdown(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(cfg, file_path=src, offline=True)
    cid = pack["critique_id"]
    assert cid == "file-draft"
    fid = pack["findings"][0]["id"]
    dismiss_finding(cfg, cid, fid)
    assert fid in load_dismissed(cfg, cid)
    pack2 = build_critique(cfg, file_path=src, offline=True)
    assert pack2["critique_id"] == cid
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
        "unique tungsten carbide coating survived the salt spray chamber overnight without peeling"
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
    hits = match_phrases(ranked, corpus, n_min=6)
    others = {h.other_key for h in hits}
    assert "OTHER" in others
    assert not any(k.startswith("ETH") for k in others)

    collapsed = collapse_nested_hits(hits, target_text=target)
    other_hits = [h for h in collapsed if h.other_key == "OTHER"]
    assert len(other_hits) == 1
    assert "tungsten carbide coating" in other_hits[0].ngram


def test_overlap_checker_against_rag_text_cache(cfg, tmp_path: Path):
    from paperful.store import write_json

    distinctive = (
        "unique tungsten carbide coating survived the salt spray chamber overnight without peeling"
    )
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
    on_disk = Path(pack["pack_dir"], "pack.json").read_text(encoding="utf-8").lower()
    assert "plagiarism" not in on_disk
    overlap = pack["overlap"]
    assert overlap and overlap[0]["other_key"] == "OTHER"
    assert overlap[0]["source"] == "phrase"
    assert len(overlap) == 1


def test_overlap_uses_rag_text_without_scope_items(cfg, tmp_path: Path):
    from paperful.store import write_json

    distinctive = (
        "unique tungsten carbide coating survived the salt spray chamber overnight without peeling"
    )
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
    pack = build_critique(cfg, file_path=src, offline=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "text_overlap" in codes
    assert "overlap_skipped_no_text" not in codes


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

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
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
    llm_rows = [f for f in suggested if f.get("source") == "llm"]
    assert llm_rows and all(f.get("reviewer") == "reviewer" for f in llm_rows)
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
    cid = body["summary"]["critique_id"]
    assert cid == "file-draft"
    dismissed = runner.invoke(
        app,
        ["critique", "dismiss", fid, "--config", str(cfg_path), "--format", "json"],
    )
    assert dismissed.exit_code == 0, dismissed.output
    dbody = json.loads(dismissed.stdout)
    assert dbody["summary"]["id"] == fid
    again = runner.invoke(
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
    assert again.exit_code == 0, again.output
    body2 = json.loads(again.stdout)
    assert body2["summary"]["critique_id"] == cid
    hid = [i for i in body2["items"] if i["id"] == fid]
    assert hid and hid[0]["dismissed"] is True


def test_cli_ai_model_flag_writes_unavailable(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--ai-model",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert any(i["code"] == "ai_model_unavailable" for i in body["items"])
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk.get("ai_model") == {"skipped": "unavailable"}


def test_cli_config_ai_model_ors_without_flag(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[critique]\nai_model = true\n"
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    ok = runner.invoke(
        app,
        ["critique", "--file", str(src), "--config", str(cfg_path), "--format", "json"],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert any(i["code"] == "ai_model_unavailable" for i in body["items"])


def test_cli_unknown_reviewer_skips_llm_lane(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[llm]\nenabled = true\nmodel = \"stub\"\n"
        "[[critique.reviewers]]\nid = \"general\"\n"
    )
    src = tmp_path / "draft.md"
    src.write_text(
        "The working group met in New York to compare notes about article twelve. " * 8,
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )

    def boom(*_a, **_k):
        raise AssertionError("unknown --reviewer must not call the model")

    monkeypatch.setattr("paperful.llm.client.chat", boom)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--llm",
            "--reviewer",
            "nope",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    pack_dir = Path(json.loads(ok.stdout)["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["skipped"] == "no_matching_reviewers"


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
    c = make_finding(
        code="missing_section",
        severity="info",
        detail="No extractable methods section.",
    )
    d = make_finding(
        code="missing_section",
        severity="info",
        detail="No extractable results section.",
    )
    assert c.id != d.id


_PAD = (
    "The working group met in New York to compare notes about article twelve. "
    "Delegates asked how coastal states would share data under the new treaty. "
)


def test_readability_and_lexical_metrics_on_known_text():
    from paperful.critique_metrics import MIN_MTLD_TOKENS, compute_lexical_diversity, compute_readability

    text = "The cat sat on the mat. The dog ran in the park. " * 8
    read = compute_readability(text)
    lex = compute_lexical_diversity(text)
    assert read["insufficient"] is False
    assert read["flesch_reading_ease"] is not None
    assert read["gunning_fog"] is not None
    assert read["ari"] is not None
    assert read["word_count"] >= 40
    assert read["sentence_count"] >= 8
    assert lex["token_count"] >= MIN_MTLD_TOKENS
    assert lex["ttr"] is not None
    assert lex["mtld"] is not None
    assert 0 < lex["ttr"] <= 1
    assert lex["hapax_rate"] is not None


def test_short_text_omits_mtld_and_abstains_ai_tells():
    from paperful.critique_ai_tells import MIN_AI_TELL_WORDS, compute_ai_tells
    from paperful.critique_metrics import MIN_MTLD_TOKENS, compute_lexical_diversity

    text = "word " * 45
    lex = compute_lexical_diversity(text)
    tells = compute_ai_tells(text)
    assert lex["token_count"] < MIN_MTLD_TOKENS
    assert lex["mtld"] is None
    assert lex["ttr"] is not None
    assert tells["abstain"] is True
    assert tells["word_count"] < MIN_AI_TELL_WORDS


def test_pack_metrics_contract_keys(cfg, tmp_path: Path):
    path = tmp_path / "keys.txt"
    path.write_text(_PAD * 8, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    read = pack["metrics"]["readability"]
    for key in (
        "flesch_reading_ease",
        "gunning_fog",
        "ari",
        "avg_sentence_length",
        "word_count",
        "sentence_count",
    ):
        assert key in read
    lex = pack["metrics"]["lexical_diversity"]
    for key in ("token_count", "type_count", "ttr", "mtld", "hapax_rate"):
        assert key in lex
    tells = pack["metrics"]["ai_tells"]
    for key in ("word_count", "burstiness_cv", "tell_phrase_hits", "unicode_flags"):
        assert key in tells
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Metrics" in md
    assert "Flesch Reading Ease" in md
    assert md.index("## Metrics") < md.index("## Checked")
    assert "not proof" in md.lower()
    assert "readability_summary" in {f["code"] for f in pack["findings"]}
    assert "lexical_diversity_summary" in {f["code"] for f in pack["findings"]}
    assert "sentence_length" not in {f["code"] for f in pack["findings"]}


def test_ai_tell_phrases_are_suggested_info(cfg, tmp_path: Path):
    pad = (
        "The working group met in New York to compare notes about article twelve. "
        "Delegates asked how coastal states would share data under the new treaty. "
    )
    tells = (
        "It is important to note that scholars delve into the tapestry of ocean law. "
        "In the realm of biodiversity this is a testament to cooperation across regions. "
        "These talks shed light on a holistic approach that underscores the mandate. "
    )
    path = tmp_path / "tells.txt"
    path.write_text((tells + pad) * 6, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    tells_metrics = pack["metrics"]["ai_tells"]
    assert tells_metrics["abstain"] is False
    assert tells_metrics["tell_phrase_total"] >= 2
    rows = [f for f in pack["findings"] if f["code"] in {"ai_tell", "ai_tell_summary"}]
    assert rows
    assert all(f["lane"] == "suggested" for f in rows)
    assert all(f["severity"] == "info" for f in rows)
    assert any(f["code"] == "ai_tell" for f in rows)
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "not proof" in md.lower()
    assert "integrity" in md.lower()


def test_short_file_ai_tells_abstain(cfg, tmp_path: Path):
    path = tmp_path / "short.txt"
    path.write_text(
        "Limitations and funding are discussed. " + ("word " * 40), encoding="utf-8"
    )
    pack = build_critique(cfg, file_path=path, offline=True)
    assert pack["metrics"]["ai_tells"]["abstain"] is True
    assert pack["metrics"]["lexical_diversity"]["mtld"] is None
    assert "ai_tells_abstain" in {f["code"] for f in pack["findings"]}


def test_ai_model_flag_records_unavailable(cfg, tmp_path: Path):
    path = tmp_path / "model.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_ai_model=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "ai_model_unavailable" in codes
    assert pack.get("ai_model") == {"skipped": "unavailable"}
    row = next(f for f in pack["findings"] if f["code"] == "ai_model_unavailable")
    assert row["lane"] == "suggested"


def test_default_critique_does_not_import_torch(cfg, tmp_path: Path):
    before = {name for name in ("torch", "binoculars") if name in sys.modules}
    path = tmp_path / "plain.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    build_critique(cfg, file_path=path, offline=True)
    after = {name for name in ("torch", "binoculars") if name in sys.modules}
    assert after == before


def test_extreme_sentence_is_info_not_ste_warn(cfg, tmp_path: Path):
    long_sent = " ".join(["word"] * 65) + "."
    path = tmp_path / "long.txt"
    path.write_text(long_sent + " Short one. " * 8, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "long_sentence" in codes
    assert "sentence_length" not in codes
    row = next(f for f in pack["findings"] if f["code"] == "long_sentence")
    assert row["severity"] == "info"
    assert row["lane"] == "checked"


def test_unicode_zero_width_is_suggested_tell(cfg, tmp_path: Path):
    path = tmp_path / "zw.txt"
    path.write_text("Hidden\u200bjoin in the draft. " + _PAD * 8, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    flags = pack["metrics"]["ai_tells"]["unicode_flags"]
    assert any(str(f).startswith("zero_width:") for f in flags)
    rows = [f for f in pack["findings"] if f["code"] == "ai_tell" and f["loc"] == "unicode"]
    assert rows
    assert all(f["lane"] == "suggested" and f["severity"] == "info" for f in rows)
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "AI-generated" not in md


def test_discourse_not_merely_flag():
    from paperful.critique_ai_tells import compute_ai_tells

    text = "This is not merely a treaty but rather a framework. " + _PAD * 8
    tells = compute_ai_tells(text)
    assert tells["abstain"] is False
    assert "not_merely_but_rather" in tells["discourse"]


def test_two_reviewers_write_separate_notes(cfg, tmp_path: Path, monkeypatch):
    prompt_a = tmp_path / "a.md"
    prompt_b = tmp_path / "b.md"
    prompt_a.write_text("You are reviewer A. No accept/reject.\n", encoding="utf-8")
    prompt_b.write_text("You are reviewer B. No accept/reject.\n", encoding="utf-8")
    cfg.critique_reviewers = (
        CritiqueReviewer(id="general", model="model-a", prompt=str(prompt_a)),
        CritiqueReviewer(id="methods", model="model-b", prompt=str(prompt_b)),
    )
    seen: list[str] = []

    def fake_chat(_client, request):
        seen.append(request.model)
        return f"Opinion from {request.model}."

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    path = tmp_path / "multi.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=path,
        offline=True,
        use_llm=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    rows = pack["llm"]["reviewers"]
    assert [r["id"] for r in rows] == ["general", "methods"]
    assert rows[0]["narrative"] == "Opinion from model-a."
    assert rows[1]["narrative"] == "Opinion from model-b."
    assert seen == ["model-a", "model-b"]
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Reviewer notes" in md
    assert "### general (model-a)" in md
    assert "### methods (model-b)" in md
    assert md.index("## Reviewer notes") < md.index("## Counts")


def test_reviewer_prompt_file_and_id_filter(cfg, tmp_path: Path, monkeypatch):
    prompt = tmp_path / "methods.md"
    prompt.write_text("You are a methods reviewer. No accept/reject.\n", encoding="utf-8")
    cfg.critique_reviewers = (
        CritiqueReviewer(id="general", model="", prompt="default"),
        CritiqueReviewer(id="methods", model="", prompt=str(prompt)),
    )
    captured: list[str] = []

    def fake_chat(_client, request):
        captured.append(request.messages[0]["content"])
        return "Methods-only note."

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    path = tmp_path / "filter.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=path,
        offline=True,
        use_llm=True,
        reviewer_ids=["methods"],
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    rows = pack["llm"]["reviewers"]
    assert len(rows) == 1
    assert rows[0]["id"] == "methods"
    assert "You are a methods reviewer" in captured[0]
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Reviewer note" in md
    assert "## Reviewer notes" not in md


def test_missing_reviewer_prompt_skips(cfg, tmp_path: Path, monkeypatch):
    cfg.critique_reviewers = (
        CritiqueReviewer(id="ghost", model="", prompt=str(tmp_path / "missing.md")),
    )

    def boom(*_a, **_k):
        raise AssertionError("missing prompt must not call the model")

    monkeypatch.setattr("paperful.llm.client.chat", boom)
    path = tmp_path / "ghost.txt"
    path.write_text(_PAD * 4, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=path,
        offline=True,
        use_llm=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    row = pack["llm"]["reviewers"][0]
    assert row["skipped"] == "prompt_missing"
    assert pack["llm"]["skipped"] == "prompt_missing"
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Reviewer note" not in md


def test_unknown_reviewer_id_skips(cfg, tmp_path: Path):
    cfg.critique_reviewers = (CritiqueReviewer(id="general", model="", prompt="default"),)
    path = tmp_path / "noid.txt"
    path.write_text(_PAD * 4, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=path,
        offline=True,
        use_llm=True,
        reviewer_ids=["nope"],
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["skipped"] == "no_matching_reviewers"


def test_cited_withdrawn_and_eoc_are_warn(cfg, tmp_path: Path, monkeypatch):
    from paperful.screen import _write_status_cache

    _write_status_cache(cfg, "10.1000/w", {"codes": ["withdrawn"], "fetched_at": 1.0})
    _write_status_cache(
        cfg, "10.1000/e", {"codes": ["expression_of_concern"], "fetched_at": 1.0}
    )
    monkeypatch.setattr(
        "paperful.critique_checks._crossref_work", lambda *_a, **_k: (None, set(), False)
    )
    path = tmp_path / "status.md"
    path.write_text(
        "Abstract\nWe study X. See [1] and [2].\n\n"
        "References\n"
        "[1] Ada. (2001). First. https://doi.org/10.1000/w\n"
        "[2] Bea. (2002). Second. https://doi.org/10.1000/e\n\n"
        + ("Findings show p < 0.05. " * 20),
        encoding="utf-8",
    )
    pack = build_critique(
        cfg,
        file_path=path,
        offline=False,
        client=object(),
    )
    by_code = {f["code"]: f for f in pack["findings"]}
    assert by_code["cited_withdrawn"]["severity"] == "warn"
    assert by_code["cited_expression_of_concern"]["severity"] == "warn"
    assert "cited_retracted" not in by_code
