"""Local manuscript critique packs (offline)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from paperful.config import CritiqueReviewer
from paperful.critique import (
    CRITIQUE_PACK_KEYS,
    SCHEMA,
    _incomplete_lane_rows,
    _is_hygiene_finding,
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


@pytest.fixture(autouse=True)
def _no_live_binoculars(monkeypatch):
    """Keep the default suite offline even if the optional extra is installed."""
    monkeypatch.setattr("paperful.critique_ai_model.run_ai_model", lambda _t: None)


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
    src.write_text(
        "Hello paragraph with enough letters to pass the extract minimum." * 2
    )
    dest = stage_file(cfg, src, name="../escape.md")
    uploads = (cfg.state_dir / "critiques" / "uploads").resolve()
    dest.resolve().relative_to(uploads)
    assert ".." not in dest.name
    assert dest.name.endswith(".md")


def test_build_critique_emits_status(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    seen: list[str] = []
    pack = build_critique(cfg, file_path=src, offline=True, on_status=seen.append)
    joined = "\n".join(seen)
    assert "Extracting" in joined
    assert "Extracted" in joined
    assert "Checkers: bibliography" in joined
    assert "Library overlap" in joined
    assert pack["schema"] == SCHEMA


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
    assert "## Critical path" in md
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
    assert {f["code"] for f in suggested} <= {
        "ai_tells_abstain",
        "ai_tell",
        "ai_tell_summary",
    }


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


def test_hygiene_codes_are_demoted():
    assert _is_hygiene_finding({"code": "vale_wrighthouse_acronyms"})
    assert _is_hygiene_finding({"code": "acronym_undefined"})
    assert _is_hygiene_finding({"code": "ai_tell_summary"})
    assert not _is_hygiene_finding({"code": "cited_retracted"})
    assert not _is_hygiene_finding({"code": "missing_section"})


def test_render_markdown_critical_path_hygiene_and_incomplete_lanes():
    pack = {
        "input": {"title": "Draft"},
        "counts": {"findings": 3},
        "llm": {
            "lanes": ["reviewers", "marg"],
            "reviewers": [
                {"id": "reviewer-5", "skipped": "empty_reply"},
                {"id": "marg-impact", "skipped": "llm_error"},
            ],
        },
        "findings": [
            {
                "code": "cited_retracted",
                "lane": "checked",
                "severity": "major",
                "loc": "p. 2",
                "detail": "Cited work is retracted.",
                "quote": "Smith 1999",
                "dismissed": False,
            },
            {
                "code": "missing_section",
                "lane": "checked",
                "severity": "info",
                "loc": "",
                "detail": "No extractable methods section.",
                "quote": "",
                "dismissed": False,
            },
            {
                "code": "acronym_undefined",
                "lane": "checked",
                "severity": "info",
                "loc": "p. 1",
                "detail": "ABC used before expansion.",
                "quote": "ABC",
                "dismissed": False,
            },
            {
                "code": "vale_wrighthouse_acronyms",
                "lane": "checked",
                "severity": "warn",
                "loc": "",
                "detail": "Prefer BBNJ.",
                "quote": "",
                "dismissed": False,
            },
            {
                "code": "adversary_alt",
                "lane": "suggested",
                "severity": "info",
                "loc": "",
                "detail": "Yield may be seasonal, not the ABC protocol.",
                "quote": "ABC protocol",
                "dismissed": False,
            },
        ],
    }
    md = render_markdown(pack)
    assert md.index("## Incomplete lanes") < md.index("## Counts")
    assert "`reviewer-5`: empty_reply" in md
    assert "`marg-impact`: llm_error" in md
    assert md.index("## Critical path") < md.index("## Suggested")
    assert md.index("## Suggested") < md.index("## Hygiene")
    crit = md[md.index("## Critical path") : md.index("## Suggested")]
    hyg = md[md.index("## Hygiene") :]
    sug = md[md.index("## Suggested") : md.index("## Hygiene")]
    assert crit.index("cited_retracted") < crit.index("missing_section")
    assert "acronym_undefined" not in crit
    assert "vale_wrighthouse_acronyms" not in crit
    assert "adversary_alt" in sug
    assert "acronym_undefined" in hyg
    assert "vale_wrighthouse_acronyms" in hyg
    empty = render_markdown({"input": {"title": "X"}, "findings": []})
    assert "## Critical path" in empty
    assert "_None._" in empty
    assert "## Incomplete lanes" not in empty
    assert "## Hygiene" not in empty


def test_incomplete_lane_rows_top_level_when_no_reviewer_skips():
    assert _incomplete_lane_rows({}) == []
    assert _incomplete_lane_rows(None) == []
    assert _incomplete_lane_rows({"skipped": "llm_disabled", "lanes": ["adversary"]}) == [
        ("llm", "llm_disabled")
    ]
    assert _incomplete_lane_rows(
        {
            "reviewers": [{"id": "marg-clarity", "skipped": "timeout"}],
            "marg": {"skipped": "timeout"},
        }
    ) == [("marg-clarity", "timeout")]


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
    assert "paperful.note.v1" in html
    assert '"type": "critique"' in html or '"type":"critique"' in html.replace(" ", "")


def test_ngram_overlap_true_and_false_positive(cfg):
    distinctive = "unique tungsten carbide coating survived the salt spray chamber overnight without peeling"
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

    distinctive = "unique tungsten carbide coating survived the salt spray chamber overnight without peeling"
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

    distinctive = "unique tungsten carbide coating survived the salt spray chamber overnight without peeling"
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

    def fake_chat(_client, _request, **_kw):
        return json.dumps(payload)

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", fake_chat)
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
    seen: list[str] = []
    extra, meta = suggested_from_llm(
        cfg,
        doc,
        findings,
        item=None,
        client=object(),
        force=False,
        on_status=seen.append,
    )
    assert extra[0].code == "llm_refused_identity"
    assert meta is None
    assert any("pdf_identity_mismatch" in msg for msg in seen)


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
        [
            "critique",
            "--item",
            "ABCD1234",
            "--file",
            str(src),
            "--config",
            str(cfg_path),
        ],
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
    assert "Extracting" not in ok.stdout
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

    monkeypatch.setattr("paperful.critique_ai_model.run_ai_model", lambda _t: None)
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

    monkeypatch.setattr("paperful.critique_ai_model.run_ai_model", lambda _t: None)
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
        '[llm]\nenabled = true\nmodel = "stub"\n'
        '[[critique.reviewers]]\nid = "general"\n'
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

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", boom)
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


def test_run_critique_prints_phase_lines(cfg, tmp_path, monkeypatch):
    from contextlib import contextmanager

    from paperful.critique_cmd import run_critique

    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _p: cfg)
    monkeypatch.setattr("paperful.cli_runtime._agent_json", lambda fmt: False)
    monkeypatch.setattr("paperful.cli_runtime._offline", lambda: True)

    @contextmanager
    def fake_spinner(_text, *, json_out=False):
        yield lambda _msg: None

    monkeypatch.setattr("paperful.cli_runtime._spinner", fake_spinner)
    c = _console()
    run_critique(
        c,
        item=[],
        file_path=src,
        collection=[],
        library=False,
        dry_run=True,
        apply=False,
        llm=False,
        force=False,
        show_dismissed=False,
        config=None,
        fmt="text",
    )
    text = c.export_text()
    assert "Extracting" in text
    assert "Checkers: bibliography" in text
    assert "Library overlap" in text


def test_run_critique_apply_item_note(cfg, tmp_path, monkeypatch):
    from contextlib import contextmanager

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

    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _p: cfg)
    monkeypatch.setattr("paperful.cli_runtime._agent_json", lambda fmt: False)
    monkeypatch.setattr("paperful.cli_runtime._offline", lambda: True)
    monkeypatch.setattr("paperful.cli_runtime._require_manager", lambda _cfg: None)
    monkeypatch.setattr("paperful.cli_runtime._connect", lambda *a, **k: backend)
    monkeypatch.setattr(
        "paperful.cli_runtime._load_scope",
        lambda *a, **k: ItemScope(items=[item], label="Col", keys=None),
    )
    monkeypatch.setattr("paperful.cli_runtime._flush", lambda _b: None)
    monkeypatch.setattr("paperful.lint.resolve_pdf_path", lambda *a, **k: src)
    monkeypatch.setattr(
        "paperful.critique.extract_path",
        lambda _p: __import__(
            "paperful.critique_extract", fromlist=["ExtractedDoc"]
        ).ExtractedDoc(text=MANUSCRIPT, format="pdf", finding="ok", pages=[MANUSCRIPT]),
    )

    @contextmanager
    def fake_spinner(_text, *, json_out=False):
        yield lambda _msg: None

    monkeypatch.setattr("paperful.cli_runtime._spinner", fake_spinner)
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
    from paperful.critique_metrics import (
        MIN_MTLD_TOKENS,
        compute_lexical_diversity,
        compute_readability,
    )

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
    assert md.index("## Metrics") < md.index("## Critical path")
    assert "not proof" in md.lower()
    assert "readability_summary" in {f["code"] for f in pack["findings"]}
    assert "lexical_diversity_summary" in {f["code"] for f in pack["findings"]}
    assert "sentence_length" not in {f["code"] for f in pack["findings"]}


def test_critique_offline_pps_tortured_from_cache(cfg, tmp_path: Path):
    cfg.screen_detectors = ("tortured",)
    cache = cfg.state_dir / "pps" / "fingerprints" / "tortured.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        '{"family":"tortured","fetched_at":1,"rows":[["sign to clamor","snr"]]}',
        encoding="utf-8",
    )
    pad = "Methods and results are described below. " * 30
    path = tmp_path / "mill.txt"
    path.write_text("We improved sign to clamor ratio. " + pad, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    assert "pps_tortured" in {f["code"] for f in pack["findings"]}


def test_critique_file_pps_tortured_phrases(cfg, tmp_path: Path):
    cfg.screen_detectors = ("tortured",)
    cache = cfg.state_dir / "pps" / "fingerprints" / "tortured.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        '{"family":"tortured","fetched_at":9999999999,"rows":[["sign to clamor","snr"]]}',
        encoding="utf-8",
    )
    pad = "Methods and results are described below. " * 30
    path = tmp_path / "mill.txt"
    path.write_text(
        "We improved sign to clamor ratio in the model. " + pad,
        encoding="utf-8",
    )
    import httpx

    with httpx.Client() as client:
        pack = build_critique(cfg, file_path=path, offline=False, client=client)
    codes = {f["code"] for f in pack["findings"]}
    assert "pps_tortured" in codes
    row = next(f for f in pack["findings"] if f["code"] == "pps_tortured")
    assert row["lane"] == "checked"
    assert "sign to clamor" in (row.get("quote") or "").lower()


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


def test_ai_model_flag_records_unavailable(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("paperful.critique_ai_model.run_ai_model", lambda _t: None)
    path = tmp_path / "model.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_ai_model=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "ai_model_unavailable" in codes
    assert pack.get("ai_model") == {"skipped": "unavailable"}
    row = next(f for f in pack["findings"] if f["code"] == "ai_model_unavailable")
    assert row["lane"] == "suggested"


def test_default_critique_does_not_run_forensics(cfg, tmp_path: Path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("paperguard must not run")

    monkeypatch.setattr("paperful.critique_forensics.shutil.which", boom)
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", boom)
    path = tmp_path / "plain.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    assert "forensics" not in pack
    assert not any(
        str(f.get("code") or "").startswith("paperguard_") for f in pack["findings"]
    )


def test_forensics_unavailable_when_not_on_path(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("paperful.critique_forensics.shutil.which", lambda _name: None)
    path = tmp_path / "scan.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_forensics=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "paperguard_unavailable" in codes
    assert pack.get("forensics") == {"skipped": "unavailable"}
    row = next(f for f in pack["findings"] if f["code"] == "paperguard_unavailable")
    assert row["lane"] == "suggested"
    assert row["source"] == "paperguard"
    assert row["severity"] == "info"
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Forensics (PaperGuard)" in md
    assert "anomalies to investigate" in md.lower()


def test_forensics_maps_report_into_pack(cfg, tmp_path: Path, monkeypatch):
    report = {
        "overall_severity": 2,
        "integrity_score": 0.4,
        "all_findings": [
            {
                "detector_id": "A1",
                "detector_name": "Terminal Digit",
                "severity": 2,
                "summary": "Last digits look biased.",
                "innocent_explanations": ["Rounding"],
                "evidence": {"column": "n"},
            }
        ],
    }

    def fake_run(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--output-json") + 1])
        out.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "paperful.critique_forensics.shutil.which", lambda _name: "/usr/bin/paperguard"
    )
    monkeypatch.setattr("paperful.critique_forensics.subprocess.run", fake_run)
    path = tmp_path / "draft.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_forensics=True)
    rows = [f for f in pack["findings"] if f.get("source") == "paperguard"]
    assert any(f["code"] == "paperguard_a1" for f in rows)
    a1 = next(f for f in rows if f["code"] == "paperguard_a1")
    assert a1["lane"] == "suggested"
    assert a1["severity"] == "warn"
    assert "integrity_score" not in (pack.get("forensics") or {})
    assert pack["forensics"]["overall_severity"] == "CONCERN"
    sidecar = Path(pack["pack_dir"]) / "paperguard.json"
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["integrity_score"] == 0.4
    assert pack["forensics"]["report_path"] == str(sidecar)
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Forensics (PaperGuard)" in md
    assert "paperguard_a1" in md


def test_cli_forensics_flag_writes_unavailable(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.critique_forensics.shutil.which", lambda _name: None)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--forensics",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert any(i["code"] == "paperguard_unavailable" for i in body["items"])
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk.get("forensics") == {"skipped": "unavailable"}


def test_cli_forensics_accepts_csv_and_xlsx(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    csv_path = tmp_path / "means.csv"
    csv_path.write_text("n,mean\n10,1.2\n", encoding="utf-8")
    xlsx_path = tmp_path / "means.xlsx"
    xlsx_path.write_bytes(b"PK")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.critique_forensics.shutil.which", lambda _name: None)
    for src in (csv_path, xlsx_path):
        ok = runner.invoke(
            app,
            [
                "critique",
                "--file",
                str(src),
                "--forensics",
                "--config",
                str(cfg_path),
                "--format",
                "json",
            ],
        )
        assert ok.exit_code == 0, ok.output
        body = json.loads(ok.stdout)
        assert any(i["code"] == "paperguard_unavailable" for i in body["items"])


def test_cli_config_forensics_ors_without_flag(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[critique]\nforensics = true\n"
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.critique_forensics.shutil.which", lambda _name: None)
    ok = runner.invoke(
        app,
        ["critique", "--file", str(src), "--config", str(cfg_path), "--format", "json"],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert any(i["code"] == "paperguard_unavailable" for i in body["items"])


def test_default_critique_does_not_run_vale(cfg, tmp_path: Path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("vale must not run")

    monkeypatch.setattr("paperful.critique_vale.shutil.which", boom)
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", boom)
    path = tmp_path / "plain.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True)
    assert "vale" not in pack
    assert not any(
        str(f.get("code") or "").startswith("vale_") for f in pack["findings"]
    )


def test_vale_unavailable_when_not_on_path(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _name: None)
    path = tmp_path / "vale.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    codes = {f["code"] for f in pack["findings"]}
    assert "vale_unavailable" in codes
    assert pack.get("vale") == {"skipped": "unavailable"}
    row = next(f for f in pack["findings"] if f["code"] == "vale_unavailable")
    assert row["lane"] == "checked"
    assert row["source"] == "vale"
    assert row["severity"] == "info"


def test_vale_no_config_when_ini_missing(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    cfg.config_path = tmp_path / "config.toml"
    path = tmp_path / "vale.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    assert pack.get("vale") == {"skipped": "no_config"}
    row = next(f for f in pack["findings"] if f["code"] == "vale_no_config")
    assert row["lane"] == "checked"
    assert row["source"] == "vale"


def test_vale_maps_alerts_to_findings(cfg, tmp_path: Path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("MinAlertLevel = suggestion\n", encoding="utf-8")
    cfg.critique_vale_config = ini
    alerts = [
        {
            "Check": "House.Terms",
            "Severity": "error",
            "Match": "utilize",
            "Message": "Use 'use' instead of 'utilize'.",
            "Line": 1,
            "Span": [8, 15],
        },
        {
            "Check": "write-good.Weasel",
            "Severity": "suggestion",
            "Match": "very",
            "Message": "'very' is a weasel word!",
            "Line": 1,
            "Span": [29, 33],
        },
    ]
    payload = json.dumps({"manuscript.txt": alerts})

    def fake_run(cmd, **_kwargs):
        assert cmd[0] == "/usr/bin/vale"
        assert "sync" not in cmd
        assert "--output=JSON" in cmd
        assert "--no-exit" in cmd
        assert "--no-global" in cmd
        assert "--ignore-syntax" in cmd
        assert any(str(a).startswith("--config=") for a in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    path = tmp_path / "vale.txt"
    path.write_text(
        "Please utilize this very protocol in the methods section.\n",
        encoding="utf-8",
    )
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    rows = [f for f in pack["findings"] if f.get("source") == "vale"]
    codes = {f["code"] for f in rows}
    assert "vale_house_terms" in codes
    assert "vale_write_good_weasel" in codes
    terms = next(f for f in rows if f["code"] == "vale_house_terms")
    assert terms["lane"] == "checked"
    assert terms["severity"] == "warn"
    assert terms["quote"] == "utilize"
    weasel = next(f for f in rows if f["code"] == "vale_write_good_weasel")
    assert weasel["severity"] == "info"
    assert pack.get("vale", {}).get("alert_count") == 2
    assert pack["vale"]["config"] == str(ini)


def test_vale_truncates_after_cap(cfg, tmp_path: Path, monkeypatch):
    from paperful.critique_vale import MAX_VALE_FINDINGS

    ini = tmp_path / ".vale.ini"
    ini.write_text("MinAlertLevel = suggestion\n", encoding="utf-8")
    cfg.critique_vale_config = ini
    alerts = [
        {
            "Check": "House.Terms",
            "Severity": "warning",
            "Match": "utilize",
            "Message": f"alert {i}",
            "Line": 1,
            "Span": [8, 15],
        }
        for i in range(MAX_VALE_FINDINGS + 3)
    ]
    payload = json.dumps({"manuscript.txt": alerts})
    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    monkeypatch.setattr(
        "paperful.critique_vale.subprocess.run",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 0, stdout=payload, stderr=""
        ),
    )
    path = tmp_path / "vale.txt"
    path.write_text(
        "Please utilize this protocol in the methods section.\n", encoding="utf-8"
    )
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    vale_rows = [f for f in pack["findings"] if f.get("source") == "vale"]
    assert (
        sum(1 for f in vale_rows if f["code"] == "vale_house_terms")
        == MAX_VALE_FINDINGS
    )
    assert any(f["code"] == "vale_truncated" for f in vale_rows)
    assert pack["vale"]["alert_count"] == MAX_VALE_FINDINGS + 3


def test_cli_vale_flag_writes_unavailable(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _name: None)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--vale",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert any(i["code"] == "vale_unavailable" for i in body["items"])
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk.get("vale") == {"skipped": "unavailable"}


def test_cli_config_vale_ors_without_flag(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[critique]\nvale = true\n"
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _name: None)
    ok = runner.invoke(
        app,
        ["critique", "--file", str(src), "--config", str(cfg_path), "--format", "json"],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    assert any(i["code"] == "vale_unavailable" for i in body["items"])


def test_vale_sibling_ini_and_min_alert_level(cfg, tmp_path: Path, monkeypatch):
    cfg.config_path = tmp_path / "config.toml"
    (tmp_path / ".vale.ini").write_text(
        "MinAlertLevel = suggestion\n", encoding="utf-8"
    )
    cfg.critique_vale_min_alert_level = "warning"
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    monkeypatch.setattr("paperful.critique_vale.subprocess.run", fake_run)
    path = tmp_path / "vale.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    assert pack.get("vale", {}).get("alert_count") == 0
    assert seen and "--minAlertLevel=warning" in seen[0]
    assert any(str(a).endswith(".vale.ini") or ".vale.ini" in str(a) for a in seen[0])
    assert "sync" not in seen[0]


def test_vale_failed_on_bad_exit(cfg, tmp_path: Path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("MinAlertLevel = suggestion\n", encoding="utf-8")
    cfg.critique_vale_config = ini
    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    monkeypatch.setattr(
        "paperful.critique_vale.subprocess.run",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 2, stdout="", stderr="StylesPath does not exist"
        ),
    )
    path = tmp_path / "vale.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    assert pack.get("vale") == {"skipped": "failed"}
    row = next(f for f in pack["findings"] if f["code"] == "vale_failed")
    assert row["lane"] == "checked"
    assert "StylesPath" in row["detail"]


def test_vale_warning_maps_to_warn(cfg, tmp_path: Path, monkeypatch):
    ini = tmp_path / ".vale.ini"
    ini.write_text("MinAlertLevel = suggestion\n", encoding="utf-8")
    cfg.critique_vale_config = ini
    payload = json.dumps(
        {
            "manuscript.txt": [
                {
                    "Check": "House.Passive",
                    "Severity": "warning",
                    "Match": "was written",
                    "Message": "Avoid passive voice.",
                    "Line": 1,
                    "Span": [1, 12],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "paperful.critique_vale.shutil.which", lambda _name: "/usr/bin/vale"
    )
    monkeypatch.setattr(
        "paperful.critique_vale.subprocess.run",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 0, stdout=payload, stderr=""
        ),
    )
    path = tmp_path / "vale.txt"
    path.write_text("It was written clearly.\n", encoding="utf-8")
    pack = build_critique(cfg, file_path=path, offline=True, use_vale=True)
    row = next(f for f in pack["findings"] if f["code"] == "vale_house_passive")
    assert row["severity"] == "warn"
    assert row["lane"] == "checked"
    assert "major" not in {
        f["severity"] for f in pack["findings"] if f.get("source") == "vale"
    }


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
    rows = [
        f for f in pack["findings"] if f["code"] == "ai_tell" and f["loc"] == "unicode"
    ]
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

    def fake_chat(_client, request, **_kw):
        seen.append(request.model)
        return f"Opinion from {request.model}."

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", fake_chat)
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
    prompt.write_text(
        "You are a methods reviewer. No accept/reject.\n", encoding="utf-8"
    )
    cfg.critique_reviewers = (
        CritiqueReviewer(id="general", model="", prompt="default"),
        CritiqueReviewer(id="methods", model="", prompt=str(prompt)),
    )
    captured: list[str] = []

    def fake_chat(_client, request, **_kw):
        captured.append(request.messages[0]["content"])
        return "Methods-only note."

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", fake_chat)
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


def test_chat_reviewer_stream_wall_clock_and_heartbeat(monkeypatch):
    from paperful.critique_llm import chat_reviewer_stream
    from paperful.llm.client import ChatRequest, LLMClientError

    class SlowClient:
        provider = "stub"

        def chat_stream(self, _request):
            yield "aa"
            time.sleep(0.05)
            yield "bb"
            time.sleep(0.05)
            yield "cc"

    seen: list[str] = []
    req = ChatRequest(
        model="m",
        messages=({"role": "user", "content": "x"},),
        timeout_seconds=30,
    )
    with pytest.raises(LLMClientError, match="wall clock"):
        chat_reviewer_stream(
            SlowClient(),
            req,
            wall_s=0.08,
            on_status=seen.append,
            label="Reviewer 1/1 openreview",
            heartbeat_s=0.04,
        )
    assert any("still generating" in msg for msg in seen)


def test_reviewer_passes_max_tokens(cfg, tmp_path: Path, monkeypatch):
    prompt = tmp_path / "note.md"
    prompt.write_text("You are a note writer. No accept/reject.\n", encoding="utf-8")
    cfg.critique_reviewers = (
        CritiqueReviewer(
            id="capped", model="model-a", prompt=str(prompt), max_tokens=512
        ),
    )
    seen: list[object] = []

    def fake_chat(_client, request, **_kw):
        seen.append(request)
        return "Short note."

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", fake_chat)
    path = tmp_path / "cap.txt"
    path.write_text("The cat sat on the mat. " * 20, encoding="utf-8")
    build_critique(
        cfg,
        file_path=path,
        offline=True,
        use_llm=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert seen and seen[0].max_tokens == 512


def test_missing_reviewer_prompt_skips(cfg, tmp_path: Path, monkeypatch):
    cfg.critique_reviewers = (
        CritiqueReviewer(id="ghost", model="", prompt=str(tmp_path / "missing.md")),
    )

    def boom(*_a, **_k):
        raise AssertionError("missing prompt must not call the model")

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", boom)
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
    cfg.critique_reviewers = (
        CritiqueReviewer(id="general", model="", prompt="default"),
    )
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
        "paperful.critique_checks.biblio._crossref_work",
        lambda *_a, **_k: (None, set(), False),
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
    seen: list[str] = []
    pack = build_critique(
        cfg,
        file_path=path,
        offline=False,
        client=object(),
        on_status=seen.append,
    )
    by_code = {f["code"]: f for f in pack["findings"]}
    assert by_code["cited_withdrawn"]["severity"] == "warn"
    assert any("Cited-work status:" in msg for msg in seen)
    assert by_code["cited_expression_of_concern"]["severity"] == "warn"
    assert "cited_retracted" not in by_code


def _marg_chat(_client, request):
    sys_msg = request.messages[0]["content"]
    blob = " ".join(m["content"] for m in request.messages)
    if "refine a list" in sys_msg:
        return json.dumps(
            {
                "comments": [
                    {
                        "quote": "See Figure 2",
                        "detail": "The methods omit how Figure 2 was produced under the ABC protocol.",
                        "code": "clarity",
                    }
                ]
            }
        )
    if "lead a small review group" in sys_msg:
        if "Replies:" in blob:
            return json.dumps(
                {
                    "action": "final",
                    "summary": "The paper reports a 47.2 percent increase and cites Figure 2.",
                    "comments": [
                        {
                            "quote": "See Figure 2",
                            "detail": "Figure 2 is mentioned without methods for the ABC protocol.",
                            "code": "experiments",
                        }
                    ],
                }
            )
        return json.dumps(
            {"action": "broadcast", "message": "Please comment on the methods."}
        )
    return json.dumps(
        {
            "reply": "The methods omit N for the ABC protocol.",
            "comments": [
                {
                    "quote": "ABC protocol",
                    "detail": "State the sample size for the ABC protocol.",
                }
            ],
        }
    )


def test_default_llm_does_not_call_marg(cfg, tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("default reviewers must not call MARG")

    monkeypatch.setattr("paperful.critique_marg.suggested_from_marg", boom)
    monkeypatch.setattr(
        "paperful.critique_llm.chat_reviewer_stream",
        lambda _c, _r, **_k: json.dumps(
            {
                "summary": "We report a 47.2 percent increase in yield.",
                "comments": [],
                "questions": [],
            }
        ),
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_llm=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["mode"] == "default"
    assert pack["llm"]["lanes"] == ["reviewers"]


def test_llm_status_reports_each_reviewer(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "paperful.critique_llm.chat_reviewer_stream",
        lambda _c, _r, **_k: json.dumps(
            {
                "summary": "We report a 47.2 percent increase in yield.",
                "comments": [],
                "questions": [],
            }
        ),
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    seen: list[str] = []
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_llm=True,
        llm_client=type("C", (), {"provider": "stub"})(),
        on_status=seen.append,
    )
    joined = "\n".join(seen)
    assert "Reviewer 1/1 reviewer ·" in joined
    assert "wall " in joined and "idle " in joined
    assert "Reviewer 1/1 reviewer done" in joined
    assert pack["llm"]["mode"] == "default"


def test_vale_and_ai_model_status_lines(cfg, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("paperful.critique_vale.shutil.which", lambda _n: None)
    monkeypatch.setattr("paperful.critique_ai_model.run_ai_model", lambda _t: None)
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    seen: list[str] = []
    build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_vale=True,
        use_ai_model=True,
        on_status=seen.append,
    )
    joined = "\n".join(seen)
    assert "Vale house-style pass" in joined
    assert "AI-text model" in joined


def test_advanced_only_skips_independent_reviewers(cfg, tmp_path, monkeypatch):
    seen: list[str] = []

    def fake_chat(_client, request):
        seen.append(request.messages[0]["content"])
        return _marg_chat(_client, request)

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    src = tmp_path / "adv.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_llm=False,
        use_advanced=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["mode"] == "marg"
    assert pack["llm"]["lanes"] == ["marg"]
    assert pack["llm"]["marg"]["parser"] == "extract"
    assert all("You review a manuscript using ONLY" not in s for s in seen)
    assert any("lead a small review group" in s for s in seen)
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    llm_rows = [f for f in suggested if f.get("source") == "llm"]
    assert llm_rows
    assert any(str(f.get("reviewer") or "").startswith("marg") for f in llm_rows)
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "marg-experiments" in md or "Reviewer" in md


def test_both_lanes_concatenate_reviewers_and_marg(cfg, tmp_path, monkeypatch):
    prompt = tmp_path / "general.md"
    prompt.write_text("You are reviewer A. No accept/reject.\n", encoding="utf-8")
    cfg.critique_reviewers = (
        CritiqueReviewer(id="general", model="model-a", prompt=str(prompt)),
    )
    cfg.critique_advanced_refine = False

    def fake_reviewer(_client, request, **_kw):
        return "Opinion from model-a about the ABC protocol and Figure 2."

    def fake_chat(_client, request):
        return _marg_chat(_client, request)

    monkeypatch.setattr("paperful.critique_llm.chat_reviewer_stream", fake_reviewer)
    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    src = tmp_path / "both.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_llm=True,
        use_advanced=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["mode"] == "both"
    assert pack["llm"]["lanes"] == ["reviewers", "marg"]
    ids = [r["id"] for r in pack["llm"]["reviewers"]]
    assert "general" in ids
    assert "marg-experiments" in ids
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "Opinion from model-a" in md


def test_advanced_identity_mismatch_refuses_without_force(cfg, tmp_path):
    from paperful.critique_extract import ExtractedDoc
    from paperful.critique_llm import suggested_from_llm

    doc = ExtractedDoc(text=MANUSCRIPT, format="md")
    findings = [
        make_finding(code="pdf_identity_mismatch", severity="warn", detail="mismatch")
    ]
    extra, meta = suggested_from_llm(
        cfg,
        doc,
        findings,
        item=None,
        client=object(),
        force=False,
        use_llm=False,
        advanced=True,
    )
    assert extra[0].code == "llm_refused_identity"
    assert meta is None


def test_advanced_drops_scoreish_and_respects_max_rounds(cfg, tmp_path, monkeypatch):
    cfg.critique_advanced_max_rounds = 1
    cfg.critique_advanced_refine = False
    cfg.critique_advanced_max_comments = 4
    calls = {"n": 0}

    def fake_chat(_client, request):
        calls["n"] += 1
        sys_msg = request.messages[0]["content"]
        if "lead a small review group" in sys_msg:
            return json.dumps(
                {
                    "action": "broadcast",
                    "message": "go",
                    "comments": [
                        {
                            "quote": "See Figure 2",
                            "detail": "I would reject this paper with overall score 2.",
                        },
                        {
                            "quote": "ABC protocol",
                            "detail": "Report the sample size for the ABC protocol.",
                        },
                    ],
                }
            )
        return json.dumps({"reply": "NO_RESPONSE", "comments": []})

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    src = tmp_path / "rounds.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_advanced=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    details = [
        f["detail"]
        for f in pack["findings"]
        if f.get("source") == "llm" and f["lane"] == "suggested"
    ]
    assert not any("reject" in d.lower() for d in details)
    assert any("sample size" in d.lower() for d in details)
    # 3 aspects × (1 leader + workers + expert); refine off. Stay bounded.
    assert calls["n"] <= 30
    assert pack["llm"]["marg"]["rounds"] == 3


def test_advanced_grobid_chunks_then_extract_fallback(cfg, tmp_path, monkeypatch):
    from paperful.critique_extract import ExtractedDoc
    from paperful.critique_marg import paper_chunks

    pdf = tmp_path / "draft.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    doc = ExtractedDoc(
        text=MANUSCRIPT,
        format="pdf",
        paragraphs=[p.strip() for p in MANUSCRIPT.split("\n\n") if p.strip()],
    )

    def fake_md(_cfg, _pdf, item_key=""):
        return [
            "# Methods\n\nSee Figure 2 under the ABC protocol.\n\n# Results\n\nYield rose 47.2 percent."
        ], ""

    monkeypatch.setattr("paperful.critique_marg.grobid_markdown", fake_md)
    chunks, meta = paper_chunks(cfg, doc, use_grobid=True, pdf_path=pdf, item_key="")
    assert meta["parser"] == "grobid"
    assert chunks
    assert any("Methods" in c.text or c.heading == "Methods" for c in chunks)

    monkeypatch.setattr(
        "paperful.critique_marg.grobid_markdown", lambda *_a, **_k: (None, "scan")
    )
    chunks2, meta2 = paper_chunks(cfg, doc, use_grobid=True, pdf_path=pdf, item_key="")
    assert meta2["parser"] == "extract"
    assert meta2["grobid_skipped"] == "scan"
    assert chunks2


def test_cli_advanced_flag_runs_marg(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        '[llm]\nenabled = true\nmodel = "stub"\n'
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )
    monkeypatch.setattr("paperful.llm.client.chat", _marg_chat)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--advanced",
            "--no-llm",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["mode"] == "marg"
    assert on_disk["llm"]["lanes"] == ["marg"]


def test_advanced_duplicate_broadcast_hard_stop(cfg, tmp_path, monkeypatch):
    cfg.critique_advanced_max_rounds = 4
    cfg.critique_advanced_refine = False
    calls = {"n": 0}

    def fake_chat(_client, request):
        calls["n"] += 1
        sys_msg = request.messages[0]["content"]
        if "lead a small review group" in sys_msg:
            return json.dumps(
                {
                    "action": "broadcast",
                    "message": "same question every time",
                    "comments": [
                        {
                            "quote": "ABC protocol",
                            "detail": "Name the sample size for the ABC protocol.",
                        }
                    ],
                }
            )
        return json.dumps({"reply": "NO_RESPONSE", "comments": []})

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    src = tmp_path / "dup.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_advanced=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    reviewers = pack["llm"].get("reviewers") or []
    assert any(r.get("skipped") == "loop" for r in reviewers)
    assert calls["n"] <= 40


def test_advanced_timeout_aborts_later_groups(cfg, tmp_path, monkeypatch):
    cfg.critique_advanced_timeout_s = 0.01
    cfg.critique_advanced_refine = False
    clock = {"t": 1_000.0}
    monkeypatch.setattr("paperful.critique_marg.time.monotonic", lambda: clock["t"])

    def fake_chat(_client, request):
        clock["t"] += 10.0
        sys_msg = request.messages[0]["content"]
        if "lead a small review group" in sys_msg:
            return json.dumps(
                {
                    "action": "final",
                    "comments": [
                        {
                            "quote": "ABC protocol",
                            "detail": "Report the sample size for the ABC protocol.",
                        }
                    ],
                }
            )
        return json.dumps({"reply": "NO_RESPONSE", "comments": []})

    monkeypatch.setattr("paperful.llm.client.chat", fake_chat)
    src = tmp_path / "timeout.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        use_advanced=True,
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    reviewers = pack["llm"].get("reviewers") or []
    assert any(r.get("skipped") == "timeout" for r in reviewers)


def _cli_critique_pdf(tmp_path, cfg, monkeypatch, *flags):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        '[llm]\nenabled = true\nmodel = "stub"\n',
        encoding="utf-8",
    )
    src = tmp_path / "draft.pdf"
    src.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n")
    hits = {"n": 0}

    def fake_md(_cfg, _pdf, item_key=""):
        hits["n"] += 1
        return [
            "# Methods\n\nSee Figure 2 under the ABC protocol.\n\n# Results\n\nYield rose 47.2 percent."
        ], ""

    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )
    monkeypatch.setattr("paperful.llm.client.chat", _marg_chat)
    monkeypatch.setattr("paperful.critique_marg.grobid_markdown", fake_md)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            *flags,
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    return ok, hits


def test_cli_grobid_flag_attempts_sidecar_without_enabled(cfg, tmp_path, monkeypatch):
    ok, hits = _cli_critique_pdf(
        tmp_path, cfg, monkeypatch, "--advanced", "--no-llm", "--grobid"
    )
    assert ok.exit_code == 0, ok.output
    assert hits["n"] == 1
    body = json.loads(ok.stdout)
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["marg"]["parser"] == "grobid"


def test_cli_grobid_without_advanced_is_ignored(cfg, tmp_path, monkeypatch):
    ok, hits = _cli_critique_pdf(tmp_path, cfg, monkeypatch, "--no-llm", "--grobid")
    assert ok.exit_code == 0, ok.output
    assert hits["n"] == 0


def _context_chat(_client, request):
    sys_msg = request.messages[0]["content"]
    if "structured summary" in sys_msg:
        return json.dumps(
            {
                "claims": ["Yield rose 47.2 percent under the ABC protocol."],
                "method": "ABC protocol",
                "evidence": ["47.2 percent increase", "Figure 2"],
            }
        )
    if "sub-domain historian" in sys_msg:
        return json.dumps(
            {"narrative": "Library papers discuss the ABC protocol and yield."}
        )
    if "baseline scout" in sys_msg:
        return json.dumps(
            {
                "omitted": [
                    {
                        "title": "Prior ABC work",
                        "detail": "Compare sample size for the ABC protocol.",
                    }
                ]
            }
        )
    if "novelty and significance" in sys_msg or "technical soundness" in sys_msg:
        return json.dumps(
            {
                "pairs": [
                    {
                        "q": "What is N for the ABC protocol?",
                        "a": "The excerpt does not report N for the ABC protocol.",
                    }
                ]
            }
        )
    return json.dumps(
        {
            "summary": "The paper reports a 47.2 percent increase under the ABC protocol.",
            "comments": [
                {
                    "quote": "ABC protocol",
                    "detail": "Report the sample size for the ABC protocol.",
                    "code": "context_soundness",
                }
            ],
            "questions": ["How was Figure 2 produced?"],
        }
    )


def _adversary_chat(_client, request):
    sys_msg = request.messages[0]["content"]
    if "validity red-team" not in sys_msg:
        raise AssertionError(f"unexpected adversary prompt: {sys_msg[:80]}")
    return json.dumps(
        {
            "summary": "The paper claims a 47.2 percent increase in yield under the ABC protocol.",
            "comments": [
                {
                    "code": "adversary_alt",
                    "quote": "ABC protocol",
                    "detail": "The ABC protocol yield increase may be seasonal rather than causal.",
                },
                {
                    "code": "adversary_invented",
                    "quote": "lemma 12.4 is false",
                    "detail": "A proof hole that is not in the excerpt.",
                },
                {
                    "code": "adversary_verdict",
                    "quote": "See Figure 2",
                    "detail": "I would reject this paper with overall score 2.",
                },
            ],
        }
    )


def test_cli_lane_flag_runs_marg(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        '[llm]\nenabled = true\nmodel = "stub"\n',
        encoding="utf-8",
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )
    monkeypatch.setattr("paperful.llm.client.chat", _marg_chat)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--lane",
            "marg",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["lanes"] == ["marg"]
    assert on_disk["llm"]["mode"] == "marg"


def test_cli_unknown_lane_exits(cfg, tmp_path):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n',
        encoding="utf-8",
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--lane",
            "nope",
            "--config",
            str(cfg_path),
        ],
    )
    assert ok.exit_code == 1
    assert "unknown critique lane" in ok.output


def test_context_lane_writes_suggested_comments(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.llm.client.chat", _context_chat)
    monkeypatch.setattr(
        "paperful.critique_context.library_passages",
        lambda *_a, **_k: (
            [{"item_key": "X", "title": "Prior ABC", "year": 2020, "text": "ABC protocol"}],
            "",
        ),
    )

    def boom_oa(*_a, **_k):
        raise AssertionError("context lane must not call OpenAlex")

    monkeypatch.setattr("paperful.critique_context._openalex_works", boom_oa)
    src = tmp_path / "ctx.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("context",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["lanes"] == ["context"]
    assert pack["llm"]["mode"] == "context"
    assert pack["llm"]["context"]["search_enabled"] is False
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    assert any(str(f.get("reviewer") or "") == "context" for f in suggested)
    assert any("sample size" in (f.get("detail") or "").lower() for f in suggested)


def test_context_web_offline_skips_search(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.llm.client.chat", _context_chat)
    monkeypatch.setattr(
        "paperful.critique_context.library_passages",
        lambda *_a, **_k: ([], "IndexMissing"),
    )

    def boom_oa(*_a, **_k):
        raise AssertionError("offline context-web must not call OpenAlex")

    def boom_sx(*_a, **_k):
        raise AssertionError("offline context-web must not call SearXNG")

    monkeypatch.setattr("paperful.critique_context._openalex_works", boom_oa)
    monkeypatch.setattr("paperful.critique_context._searxng_hits", boom_sx)
    src = tmp_path / "web.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("context-web",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["lanes"] == ["context-web"]
    assert pack["llm"]["context"]["search_skipped"] == "offline"
    assert pack["llm"]["context"]["search_enabled"] is True
    assert pack["llm"]["context"].get("rag_skipped") == "IndexMissing"


def test_adversary_lane_writes_suggested_comments(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.llm.client.chat", _adversary_chat)
    src = tmp_path / "advr.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("adversary",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["lanes"] == ["adversary"]
    assert pack["llm"]["mode"] == "adversary"
    assert pack["llm"]["adversary"]["calls"] == 1
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    codes = {f["code"] for f in suggested if f.get("source") == "llm"}
    assert "adversary_alt" in codes
    assert "llm_summary" in codes
    assert "adversary_invented" not in codes
    assert "adversary_verdict" not in codes
    assert any(str(f.get("reviewer") or "") == "adversary" for f in suggested)
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Suggested" in md
    assert "adversary_alt" in md
    assert "## Incomplete lanes" not in md


def test_cli_lane_flag_runs_adversary(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        '[llm]\nenabled = true\nmodel = "stub"\n',
        encoding="utf-8",
    )
    src = tmp_path / "draft.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )
    monkeypatch.setattr("paperful.llm.client.chat", _adversary_chat)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--lane",
            "adversary",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["lanes"] == ["adversary"]
    assert on_disk["llm"]["mode"] == "adversary"


CLAIMS_MANUSCRIPT = """
Abstract

We report a 47.2 percent increase in yield under the ABC protocol.
Global coverage is claimed for every ocean basin.

Methods

The ABC protocol was applied to 40 plots. Yield was measured at harvest.

Results

Yield rose 47.2 percent under the ABC protocol compared with the control.

Limitations

The ABC protocol sample was a single season.

References

[1] Ada. (2001). First paper. Journal. https://doi.org/10.1000/missing
"""


def _claims_chat(_client, request):
    sys_msg = request.messages[0]["content"]
    if "extract core claims" in sys_msg:
        return json.dumps(
            {
                "claims": [
                    "Yield rose 47.2 percent under the ABC protocol.",
                    "Global coverage is claimed for every ocean basin.",
                    "lemma 12.4 is false",
                ],
                "method": "ABC protocol on 40 plots",
            }
        )
    if "only downgrade" in sys_msg:
        return json.dumps(
            {
                "adjustments": [
                    {
                        "id": "c1",
                        "status": "supported",
                        "detail": "Must not upgrade a claim.",
                    }
                ]
            }
        )
    raise AssertionError(f"unexpected claims prompt: {sys_msg[:80]}")


def _verify_chat(_client, request):
    sys_msg = request.messages[0]["content"]
    if "refine section-verify" in sys_msg:
        return json.dumps(
            {
                "comments": [
                    {
                        "code": "verify_gap",
                        "quote": "ABC protocol",
                        "detail": "The ABC protocol excerpt does not report how Figure 2 was produced.",
                    }
                ]
            }
        )
    if "verify one manuscript" in sys_msg or "short pass over a light" in sys_msg:
        return json.dumps(
            {
                "comments": [
                    {
                        "code": "verify_gap",
                        "quote": "ABC protocol",
                        "detail": "The ABC protocol does not state N for the plots.",
                    },
                    {
                        "code": "verify_logic",
                        "quote": "ABC protocol",
                        "detail": 'Compare "A Completely Fake Zebra Paper" on yield.',
                    },
                ]
            }
        )
    if "attack a previous acceptance" in sys_msg:
        return json.dumps({"comments": []})
    raise AssertionError(f"unexpected verify prompt: {sys_msg[:80]}")


def test_claims_lane_writes_ledger_and_gaps(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.llm.client.chat", _claims_chat)
    src = tmp_path / "claims.md"
    src.write_text(CLAIMS_MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("claims",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["lanes"] == ["claims"]
    assert pack["llm"]["mode"] == "claims"
    ledger = pack.get("claims") or []
    texts = [row["text"] for row in ledger]
    assert any("47.2 percent" in t for t in texts)
    assert all("lemma 12.4" not in t for t in texts)
    supported = [row for row in ledger if "47.2 percent" in row["text"]]
    assert supported and supported[0]["status"] == "supported"
    basin = [row for row in ledger if "ocean basin" in row["text"]]
    assert basin and basin[0]["status"] == "unsupported"
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    codes = {f["code"] for f in suggested if f.get("source") == "claims"}
    assert "claim_unsupported_in_text" in codes
    assert "claim_supported" not in {f["code"] for f in suggested}
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Claims" in md
    assert md.index("## Critical path") < md.index("## Claims")
    assert md.index("## Claims") < md.index("## Suggested")
    assert "not supported in this extract" in md.lower() or "unsupported" in md
    sug = md[md.index("## Suggested") :]
    assert "claim_supported" not in sug
    assert "## Incomplete lanes" not in md


def test_cli_lane_flag_runs_claims(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        '[llm]\nenabled = true\nmodel = "stub"\n',
        encoding="utf-8",
    )
    src = tmp_path / "draft.md"
    src.write_text(CLAIMS_MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )
    monkeypatch.setattr("paperful.llm.client.chat", _claims_chat)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--lane",
            "claims",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["lanes"] == ["claims"]
    assert on_disk["llm"]["mode"] == "claims"
    assert on_disk.get("claims")


def test_verify_lane_drops_invented_citations(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("paperful.llm.client.chat", _verify_chat)
    src = tmp_path / "verify.md"
    src.write_text(CLAIMS_MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("verify",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["lanes"] == ["verify"]
    assert pack["llm"]["mode"] == "verify"
    assert pack["llm"]["verify"]["segments"]
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    codes = {f["code"] for f in suggested if f.get("source") == "llm"}
    assert "verify_gap" in codes
    details = " ".join(f.get("detail") or "" for f in suggested)
    assert "Completely Fake Zebra Paper" not in details
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "verify_gap" in md


def test_verify_timeout_records_incomplete_segments(cfg, tmp_path, monkeypatch):
    cfg.critique_verify_timeout_s = 1.0
    n = {"i": 0}

    def fake_mono():
        n["i"] += 1
        return 0.0 if n["i"] == 1 else 5.0

    monkeypatch.setattr("paperful.critique_verify.time.monotonic", fake_mono)
    monkeypatch.setattr("paperful.llm.client.chat", _verify_chat)
    src = tmp_path / "to.md"
    src.write_text(CLAIMS_MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("verify",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["verify"].get("skipped") == "timeout"
    segs = pack["llm"]["verify"].get("segments") or []
    assert segs and all(s.get("skipped") == "timeout" for s in segs)
    md = Path(pack["pack_dir"], "pack.md").read_text(encoding="utf-8")
    assert "## Incomplete lanes" in md


def test_verify_doi_status_cache_without_http(cfg, tmp_path, monkeypatch):
    from paperful.screen import _write_status_cache

    _write_status_cache(cfg, "10.1000/cached", {"codes": [], "fetched_at": 1.0})

    def chat(_client, request):
        sys_msg = request.messages[0]["content"]
        if "refine section-verify" in sys_msg:
            return json.dumps({"comments": []})
        return json.dumps(
            {
                "comments": [
                    {
                        "code": "verify_gap",
                        "quote": "ABC protocol",
                        "detail": "The ABC protocol should cite 10.1000/cached.",
                    },
                    {
                        "code": "verify_logic",
                        "quote": "ABC protocol",
                        "detail": "The ABC protocol should cite 10.9999/cold-cache.",
                    },
                ]
            }
        )

    monkeypatch.setattr("paperful.llm.client.chat", chat)
    src = tmp_path / "doi.md"
    src.write_text(CLAIMS_MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("verify",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    suggested = [f for f in pack["findings"] if f["lane"] == "suggested"]
    details = " ".join(f.get("detail") or "" for f in suggested)
    codes = {f["code"] for f in suggested if f.get("source") == "llm"}
    assert "10.1000/cached" in details
    assert "10.9999/cold-cache" not in details
    assert "verify_cite_unchecked" in codes


def test_cli_lane_flag_runs_verify(cfg, tmp_path, monkeypatch):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        '[llm]\nenabled = true\nmodel = "stub"\n',
        encoding="utf-8",
    )
    src = tmp_path / "draft.md"
    src.write_text(CLAIMS_MANUSCRIPT, encoding="utf-8")
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_llm_for_verb", lambda _cfg: None
    )
    monkeypatch.setattr(
        "paperful.llm.get_client",
        lambda _cfg: type("C", (), {"provider": "stub"})(),
    )
    monkeypatch.setattr("paperful.llm.client.chat", _verify_chat)
    ok = runner.invoke(
        app,
        [
            "critique",
            "--file",
            str(src),
            "--lane",
            "verify",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert ok.exit_code == 0, ok.output
    body = json.loads(ok.stdout)
    pack_dir = Path(body["summary"]["pack_dir"])
    on_disk = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert on_disk["llm"]["lanes"] == ["verify"]


def test_marg_config_aspects_run_theory_only(cfg, tmp_path, monkeypatch):
    cfg.critique_advanced_refine = False
    cfg.critique_advanced_aspects = ("theory",)
    monkeypatch.setattr("paperful.llm.client.chat", _marg_chat)
    src = tmp_path / "theory.md"
    src.write_text(MANUSCRIPT, encoding="utf-8")
    pack = build_critique(
        cfg,
        file_path=src,
        offline=True,
        lanes=("marg",),
        llm_client=type("C", (), {"provider": "stub"})(),
    )
    assert pack["llm"]["marg"]["aspects"] == ["theory"]
    ids = [r["id"] for r in pack["llm"]["reviewers"]]
    assert "marg-theory" in ids
    assert "marg-experiments" not in ids


def test_render_markdown_claims_section_between_critical_and_suggested():
    pack = {
        "input": {"title": "Draft"},
        "counts": {"findings": 1},
        "claims": [
            {
                "id": "c1",
                "text": "Yield rose 47.2 percent under the ABC protocol.",
                "status": "supported",
                "support_quote": "Yield rose 47.2 percent under the ABC protocol.",
                "loc": "paragraph 3",
            }
        ],
        "findings": [
            {
                "code": "missing_section",
                "lane": "checked",
                "severity": "info",
                "loc": "",
                "detail": "No extractable related work.",
                "quote": "",
                "dismissed": False,
            },
            {
                "code": "claim_unsupported_in_text",
                "lane": "suggested",
                "severity": "info",
                "loc": "",
                "detail": "Claim is not supported in this extract.",
                "quote": "ocean basin",
                "dismissed": False,
            },
        ],
    }
    md = render_markdown(pack)
    assert md.index("## Critical path") < md.index("## Claims")
    assert md.index("## Claims") < md.index("## Suggested")
    assert "c1" in md
    assert "supported" in md
