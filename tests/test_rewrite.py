"""Apply-from-critique rewrite packs (offline)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperful.critique import make_finding
from paperful.rewrite import build_rewrite
from paperful.rewrite_align import align_finding
from paperful.rewrite_areas import (
    bucket_findings,
    parse_rewrite_areas_list,
    parse_rewrite_outputs,
)
from paperful.rewrite_docx import (
    apply_tracked_docx,
    build_docx_from_paragraphs,
    docx_structural_issues,
)
from paperful.rewrite_llm import edit_is_grounded
from paperful.rewrite_office import (
    apply_odt,
    apply_pptx,
    build_odt_from_paragraphs,
    odt_structural_issues,
    pptx_structural_issues,
)
from paperful.rewrite_plan import RewriteEdit, merge_edits

runner = CliRunner()

DRAFT = """The BBNJ Agreement covers Maritime Area beyond national jurisdictions.

This is a very long sentence that goes on and on without a pause so that the prose checker can flag it as a long_sentence finding for the style area when a model is available.

See Smith (2020) for background.
"""


def _pack(findings: list[dict], *, cid: str = "file-draft", path: str = "") -> dict:
    return {
        "schema": "paperful.critique.pack.v1",
        "critique_id": cid,
        "input": {"kind": "file", "title": "draft.md", "path": path},
        "findings": findings,
        "llm": None,
    }


def _finding(**kwargs) -> dict:
    f = make_finding(
        code=kwargs.pop("code", "acronym_expansion_mismatch"),
        severity=kwargs.pop("severity", "warn"),
        loc=kwargs.pop("loc", "paragraph 1"),
        quote=kwargs.pop("quote", "Maritime Area beyond national jurisdictions"),
        detail=kwargs.pop("detail", "Use Areas Beyond National Jurisdiction"),
        lane=kwargs.pop("lane", "checked"),
        extra=kwargs.pop("extra", {"suggested": "Areas Beyond National Jurisdiction"}),
        source=kwargs.pop("source", "glossary"),
    )
    row = f.to_dict()
    row.update(kwargs)
    return row


def test_default_areas_are_style_only():
    assert parse_rewrite_outputs(None) == ("edits", "tracked")
    assert parse_rewrite_outputs(["odt", "pdf"]) == ("edits", "odt", "pdf")
    with pytest.raises(ValueError, match="unknown rewrite output"):
        parse_rewrite_outputs(["docx"])
    assert parse_rewrite_areas_list(None) == ("style",)
    assert parse_rewrite_areas_list(["all"]) == (
        "style",
        "cites",
        "structure",
        "comments",
    )


def test_style_default_excludes_cites():
    hay = DRAFT.lower()
    findings = [
        _finding(),
        _finding(
            code="cite_not_in_bibliography",
            quote="Smith (2020)",
            extra={},
            detail="cite missing",
        ),
    ]
    buckets, skips = bucket_findings(findings, areas=("style",), hay=hay)
    assert [f["code"] for f in buckets["style"]] == ["acronym_expansion_mismatch"]
    assert any(s["reason"] == "not_actionable" for s in skips)


def test_dismissed_and_quotes_are_skipped():
    hay = 'He said "Maritime Area beyond national jurisdictions" yesterday.'
    dismissed = _finding()
    dismissed["dismissed"] = True
    quoted = _finding()
    quoted["quote"] = "Maritime Area beyond national jurisdictions"
    buckets, skips = bucket_findings(
        [dismissed, quoted], areas=("style",), hay=hay
    )
    reasons = {s["reason"] for s in skips}
    assert "dismissed" in reasons
    assert "quote" in reasons
    assert buckets["style"] == []


def test_unique_span_miss_skips():
    text = DRAFT + "\n\nMaritime Area beyond national jurisdictions again."
    finding = _finding()
    bound = align_finding(finding, text=text, paragraphs=text.split("\n\n"))
    assert bound == "no_unique_span"


def test_glossary_suggested_is_deterministic(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    finding = _finding()
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        comments="off",
        dry_run=False,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    assert edits
    assert edits[0]["kind"] == "replace"
    assert "Areas Beyond National Jurisdiction" in edits[0]["replacement"]
    assert result["pack_dir"]
    assert Path(result["pack_dir"], "plan.json").is_file()
    assert src.read_text(encoding="utf-8") == DRAFT  # never overwrite


def test_overwide_acronym_quote_is_not_applied(cfg, tmp_path: Path):
    """Old packs that swallowed 'IV on' / 'of' must not delete that prose."""
    src = tmp_path / "draft.md"
    text = "Part IV on environmental impact assessment (EIA) more.\n"
    src.write_text(text, encoding="utf-8")
    finding = _finding(
        code="acronym_expansion_mismatch",
        quote="IV on environmental impact assessment (EIA)",
        detail="EIA expansion should be Environmental Impact Assessment",
        extra={
            "token": "EIA",
            "suggested": "Environmental Impact Assessment",
        },
    )
    result = build_rewrite(
        cfg,
        pack=_pack([finding], path=str(src)),
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        comments="off",
        dry_run=True,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    assert edits == []
    skips = (result.get("plan") or {}).get("skips") or []
    assert any(s.get("reason") == "needs_author" for s in skips)


def test_overlapping_spans_drop_later():
    a = RewriteEdit(
        kind="replace",
        finding_ids=["a"],
        area="style",
        quote="hello world",
        replacement="hi",
        start=0,
        end=11,
    )
    b = RewriteEdit(
        kind="replace",
        finding_ids=["b"],
        area="style",
        quote="world",
        replacement="earth",
        start=6,
        end=11,
    )
    plan = merge_edits([a, b])
    assert [e.finding_ids[0] for e in plan.edits] == ["a"]
    assert any(s["reason"] == "overlap" for s in plan.skips)


def test_no_new_cite_keys():
    hay = "the extract mentions smith 2020 only"
    reason = edit_is_grounded(
        kind="replace",
        quote="smith 2020",
        replacement="see \\cite{invented2024}",
        body="",
        hay=hay,
    )
    assert reason == "no_evidence"


def test_retracted_cite_is_comment_not_delete(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text("We cite Retracted Work (2018) throughout.\n", encoding="utf-8")
    finding = _finding(
        code="cited_retracted",
        quote="Retracted Work (2018)",
        detail="cited work was retracted",
        extra={},
        lane="checked",
    )
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("comments",),
        outputs=("edits",),
        comments="off",
        dry_run=True,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    assert edits
    assert all(e["kind"] == "comment" for e in edits)
    assert not any(e["kind"] == "delete" for e in edits)


def test_dry_run_writes_nothing(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits", "tracked"),
        dry_run=True,
        llm_client=None,
    )
    assert result.get("pack_dir") in (None, "")
    assert not (cfg.state_dir / "rewrites").exists()


def test_cli_requires_pack(cfg, tmp_path: Path):
    from paperful.cli import app

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    res = runner.invoke(app, ["rewrite", "--file", str(src), "--config", str(cfg_path)])
    assert res.exit_code == 1
    assert "critique pack" in (res.output or "").lower()


def test_cli_pack_and_dry_run(cfg, tmp_path: Path):
    from paperful.cli import app

    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    pack_dir = cfg.state_dir / "critiques" / "file-draft" / "20261027T000000Z"
    pack_dir.mkdir(parents=True)
    payload = _pack([_finding()], path=str(src))
    (pack_dir / "pack.json").write_text(json.dumps(payload), encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
    )
    res = runner.invoke(
        app,
        [
            "rewrite",
            "--pack",
            str(pack_dir),
            "--file",
            str(src),
            "--output",
            "edits",
            "--dry-run",
            "--config",
            str(cfg_path),
            "--format",
            "json",
        ],
    )
    assert res.exit_code == 0, res.output
    body = json.loads(res.stdout)
    assert body["command"] == "rewrite"
    assert body["summary"]["edits"] >= 1
    assert not list((cfg.state_dir / "rewrites").glob("**/*")) if (
        cfg.state_dir / "rewrites"
    ).exists() else True


def test_tracked_docx_insert_delete(tmp_path: Path):
    src = tmp_path / "src.docx"
    body = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:p><w:r><w:t>Maritime Area beyond national jurisdictions</w:t></w:r></w:p>"
        "</w:document>"
    )
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("word/document.xml", body)
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
    dest = tmp_path / "out.docx"
    edit = RewriteEdit(
        kind="replace",
        finding_ids=["a"],
        area="style",
        quote="Maritime Area beyond national jurisdictions",
        replacement="Areas Beyond National Jurisdiction",
    )
    skips = apply_tracked_docx(src, dest, [edit])
    assert skips == []
    with zipfile.ZipFile(dest) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "w:ins" in xml or "ins" in xml
    assert "Areas Beyond National Jurisdiction" in xml
    assert "ns0:" not in xml
    assert docx_structural_issues(dest) == []


def _docx_with_comment(path: Path, *, para: str, comment_id: str, body: str) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'mc:Ignorable="w14">'
        "<w:p>"
        f'<w:commentRangeStart w:id="{comment_id}"/>'
        f"<w:r><w:t>{para}</w:t></w:r>"
        f'<w:commentRangeEnd w:id="{comment_id}"/>'
        f'<w:r><w:commentReference w:id="{comment_id}"/></w:r>'
        "</w:p>"
        "</w:document>"
    )
    comments = (
        '<?xml version="1.0"?>'
        '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:comment w:id="{comment_id}" w:author="Glen" w:initials="GW">'
        f"<w:p><w:r><w:t>{body}</w:t></w:r></w:p>"
        "</w:comment>"
        "</w:comments>"
    )
    rels = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdCmt1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
        'Target="comments.xml"/>'
        "</Relationships>"
    )
    ctypes = (
        '<?xml version="1.0"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/comments.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr("word/comments.xml", comments)
        zf.writestr("word/_rels/document.xml.rels", rels)
        zf.writestr("[Content_Types].xml", ctypes)


def test_docx_structural_issues_flags_undeclared_ignorable(tmp_path: Path):
    src = tmp_path / "bad.docx"
    document = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'mc:Ignorable="w14">'
        "<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
    issues = docx_structural_issues(src)
    assert any("w14" in row for row in issues)


def test_tracked_docx_keeps_existing_comments(tmp_path: Path):
    src = tmp_path / "src.docx"
    _docx_with_comment(
        src,
        para="The regime applies in areas beyond national jurisdiction.",
        comment_id="0",
        body="Author note on the title claim.",
    )
    dest = tmp_path / "out.docx"
    edit = RewriteEdit(
        kind="comment",
        finding_ids=["c"],
        area="comments",
        quote="areas beyond national jurisdiction",
        body="Paperful note on the locatable span.",
    )
    skips = apply_tracked_docx(src, dest, [edit])
    assert skips == []
    with zipfile.ZipFile(dest) as zf:
        comments = zf.read("word/comments.xml").decode("utf-8")
        doc = zf.read("word/document.xml").decode("utf-8")
        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "Author note on the title claim." in comments
    assert "Paperful note on the locatable span." in comments
    assert 'w:id="0"' in comments
    assert 'w:id="1"' in comments
    assert "ns0:" not in comments
    assert "ns0:" not in doc
    assert "comments.xml" in rels
    assert rels.count("comments.xml") == 1
    assert 'xmlns:w14=' in doc
    assert 'mc:Ignorable="w14"' in doc
    assert docx_structural_issues(dest) == []


def test_tracked_docx_multiple_comments_per_paragraph(tmp_path: Path):
    src = tmp_path / "src.docx"
    _docx_with_comment(
        src,
        para="Neither requires assessment of food-web effects. Screening should be usual.",
        comment_id="0",
        body="Author note.",
    )
    dest = tmp_path / "out.docx"
    edits = [
        RewriteEdit(
            kind="comment",
            finding_ids=["c1"],
            area="comments",
            quote="Neither requires assessment of food-web effects",
            body="First paperful note.",
        ),
        RewriteEdit(
            kind="comment",
            finding_ids=["c2"],
            area="comments",
            quote="Screening should be usual",
            body="Second paperful note.",
        ),
        RewriteEdit(
            kind="replace",
            finding_ids=["r1"],
            area="style",
            quote="food-web effects",
            replacement="food web effects",
        ),
    ]
    skips = apply_tracked_docx(src, dest, edits)
    assert skips == []
    with zipfile.ZipFile(dest) as zf:
        comments = zf.read("word/comments.xml").decode("utf-8")
        doc = zf.read("word/document.xml").decode("utf-8")
    assert "Author note." in comments
    assert "First paperful note." in comments
    assert "Second paperful note." in comments
    assert "food web effects" in doc
    assert doc.count("commentRangeStart") >= 3
    assert "w:ins" in doc or "ins" in doc
    assert docx_structural_issues(dest) == []


def test_build_docx_from_paragraphs(tmp_path: Path):
    dest = tmp_path / "built.docx"
    edit = RewriteEdit(
        kind="comment",
        finding_ids=["c"],
        area="comments",
        quote="Hello",
        body="Check this claim.",
    )
    skips = build_docx_from_paragraphs(dest, ["Hello world"], [edit])
    assert skips == []
    assert dest.is_file()
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert "word/document.xml" in names
        assert "word/comments.xml" in names
        comments = zf.read("word/comments.xml").decode("utf-8")
    assert "Check this claim." in comments
    assert "ns0:" not in comments


def test_worklog_lists_needs_author(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text("Unique span here about policy instruments.\n", encoding="utf-8")
    finding = _finding(
        code="long_sentence",
        quote="Unique span here about policy instruments.",
        detail="shorten this",
        extra={},
    )
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        dry_run=True,
        llm_client=None,
    )
    skipped = (result.get("plan") or {}).get("worklog", {}).get("skipped") or []
    assert any("needs_author" in s for s in skipped)


def test_cli_never_imports_build_critique():
    from paperful import rewrite_cmd

    src = Path(rewrite_cmd.__file__).read_text(encoding="utf-8")
    assert "build_critique" not in src


def test_leakage_and_promise_are_ungrounded():
    hay = "the extract mentions smith 2020 only"
    assert (
        edit_is_grounded(
            kind="replace",
            quote="smith 2020",
            replacement="as the reviewer noted, smith 2020",
            body="",
            hay=hay,
        )
        == "leakage"
    )
    assert (
        edit_is_grounded(
            kind="replace",
            quote="smith 2020",
            replacement="smith 2020; see the appendix",
            body="",
            hay=hay,
        )
        == "no_evidence"
    )


def test_vale_quoted_swap_is_deterministic(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text("We utilise this term in the methods.\n", encoding="utf-8")
    finding = _finding(
        code="vale_swap",
        quote="utilise",
        detail="Use 'use' instead of utilise",
        extra={},
        source="vale",
        loc="",
    )
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        dry_run=True,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    assert edits
    assert edits[0]["kind"] == "replace"
    assert edits[0]["replacement"] == "use"


def test_sidecar_and_plan_schema(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits", "sidecar"),
        comments="off",
        dry_run=False,
        llm_client=None,
    )
    folder = Path(result["pack_dir"])
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    assert plan["schema"] == "paperful.rewrite.plan.v1"
    assert "worklog" in plan
    md = (folder / "pack.md").read_text(encoding="utf-8")
    assert md.index("## Worklog") < md.index("## Edits")
    sidecar = folder / "sidecar.md"
    assert sidecar.is_file()
    assert "Areas Beyond National Jurisdiction" in sidecar.read_text(encoding="utf-8")
    assert src.read_text(encoding="utf-8") == DRAFT


def test_comments_area_anchors_suggested_finding(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text("Unique span here about policy instruments.\n", encoding="utf-8")
    finding = _finding(
        code="clarity",
        lane="suggested",
        quote="Unique span here about policy instruments.",
        detail="should clarify this claim",
        extra={},
    )
    pack = _pack([finding], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("comments",),
        outputs=("edits",),
        comments="off",
        dry_run=True,
        llm_client=None,
    )
    edits = (result.get("plan") or {}).get("edits") or []
    assert edits
    assert all(e["kind"] == "comment" for e in edits)


def test_openxml_audit_skips_when_extra_missing(cfg, tmp_path: Path, monkeypatch):
    from paperful.rewrite_openxml import audit_tracked_docx

    src = tmp_path / "src.docx"
    _docx_with_comment(
        src,
        para="The regime applies in areas beyond national jurisdiction.",
        comment_id="0",
        body="Author note.",
    )
    dest = tmp_path / "out.docx"
    apply_tracked_docx(
        src,
        dest,
        [
            RewriteEdit(
                kind="comment",
                finding_ids=["c"],
                area="comments",
                quote="areas beyond national jurisdiction",
                body="Paperful note.",
            )
        ],
    )
    monkeypatch.setattr("paperful.rewrite_openxml.extra_available", lambda: False)
    cfg.rewrite_openxml_audit = True
    row = audit_tracked_docx(cfg, dest, source=src)
    assert row["enabled"] is True
    assert row["skipped"] == "unavailable"
    assert row["fail"] is False
    assert row["structural"] == []


def test_openxml_audit_reports_errors_introduced_vs_source(
    cfg, tmp_path: Path, monkeypatch
):
    from paperful.rewrite_openxml import audit_tracked_docx

    src = tmp_path / "src.docx"
    dest = tmp_path / "out.docx"
    _docx_with_comment(
        src,
        para="The regime applies in areas beyond national jurisdiction.",
        comment_id="0",
        body="Author note.",
    )
    apply_tracked_docx(
        src,
        dest,
        [
            RewriteEdit(
                kind="comment",
                finding_ids=["c"],
                area="comments",
                quote="areas beyond national jurisdiction",
                body="Paperful note.",
            )
        ],
    )
    monkeypatch.setattr("paperful.rewrite_openxml.extra_available", lambda: True)

    def fake_sdk(path: Path) -> list[str]:
        shared = ["styles.xml vs stylesWithEffects"]
        if path == dest:
            return [*shared, "Ignorable prefix 'w14' is not declared"]
        return shared

    monkeypatch.setattr("paperful.rewrite_openxml.sdk_errors", fake_sdk)
    cfg.rewrite_openxml_audit = True
    cfg.rewrite_openxml_audit_policy = "fail"
    row = audit_tracked_docx(cfg, dest, source=src)
    assert row["introduced"] == ["Ignorable prefix 'w14' is not declared"]
    assert row["fail"] is True
    assert row["format"] == "docx"


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


def test_apply_pptx_replace_and_skip_comments(tmp_path: Path):
    src = _pptx(tmp_path / "src.pptx", "Maritime Area beyond national jurisdictions")
    dest = tmp_path / "out.pptx"
    edits = [
        RewriteEdit(
            kind="replace",
            finding_ids=["a"],
            area="style",
            quote="Maritime Area beyond national jurisdictions",
            replacement="Areas Beyond National Jurisdiction",
        ),
        RewriteEdit(
            kind="comment",
            finding_ids=["c"],
            area="comments",
            quote="Areas Beyond National Jurisdiction",
            body="Reviewer note.",
        ),
    ]
    skips = apply_pptx(src, dest, edits)
    assert any("plan-only" in row for row in skips)
    with zipfile.ZipFile(dest) as zf:
        xml = zf.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "Areas Beyond National Jurisdiction" in xml
    assert "ns0:" not in xml
    assert pptx_structural_issues(dest) == []


def test_apply_odt_replace(tmp_path: Path):
    src = _odt(tmp_path / "src.odt", "Maritime Area beyond national jurisdictions")
    dest = tmp_path / "out.odt"
    edits = [
        RewriteEdit(
            kind="replace",
            finding_ids=["a"],
            area="style",
            quote="Maritime Area beyond national jurisdictions",
            replacement="Areas Beyond National Jurisdiction",
        ),
        RewriteEdit(
            kind="comment",
            finding_ids=["c"],
            area="comments",
            quote="Areas Beyond National Jurisdiction",
            body="Reviewer note.",
        ),
    ]
    skips = apply_odt(src, dest, edits)
    assert any("plan-only" in row for row in skips)
    with zipfile.ZipFile(dest) as zf:
        xml = zf.read("content.xml").decode("utf-8")
    assert "Areas Beyond National Jurisdiction" in xml
    assert "ns0:" not in xml
    assert odt_structural_issues(dest) == []


def test_odt_structural_issues_missing_content(tmp_path: Path):
    src = tmp_path / "empty.odt"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
    issues = odt_structural_issues(src)
    assert any("content.xml" in row for row in issues)


def test_pptx_structural_issues_flags_ns0(tmp_path: Path):
    src = tmp_path / "bad.pptx"
    slide = (
        '<?xml version="1.0"?>'
        '<ns0:sld xmlns:ns0="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<ns0:t>Hi</ns0:t></ns0:sld>"
    )
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
    issues = pptx_structural_issues(src)
    assert any("ns0:" in row for row in issues)


def test_rewrite_writes_native_pptx(cfg, tmp_path: Path):
    src = _pptx(
        tmp_path / "talk.pptx",
        "Maritime Area beyond national jurisdictions and enough letters here.",
    )
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits", "tracked"),
        comments="off",
        dry_run=False,
        llm_client=None,
    )
    folder = Path(result["pack_dir"])
    assert (folder / "tracked.pptx").is_file()
    assert not (folder / "tracked.docx").exists()
    assert result.get("tracked") == "tracked.pptx"
    audit = result.get("openxml_audit") or {}
    assert audit.get("format") == "pptx"


def test_rewrite_writes_native_odt(cfg, tmp_path: Path):
    src = _odt(
        tmp_path / "draft.odt",
        "Maritime Area beyond national jurisdictions and enough letters here.",
    )
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits", "tracked"),
        comments="off",
        dry_run=False,
        llm_client=None,
    )
    folder = Path(result["pack_dir"])
    assert (folder / "tracked.odt").is_file()
    assert not (folder / "tracked.docx").exists()
    assert result.get("tracked") == "tracked.odt"
    audit = result.get("openxml_audit") or {}
    assert audit.get("format") == "odt"
    assert odt_structural_issues(folder / "tracked.odt") == []


def test_sdk_errors_skips_non_office(tmp_path: Path):
    from paperful.rewrite_openxml import sdk_errors

    path = tmp_path / "note.md"
    path.write_text("hello", encoding="utf-8")
    assert sdk_errors(path) == []


def test_openxml_audit_pptx_diffs_vs_source(cfg, tmp_path: Path, monkeypatch):
    from paperful.rewrite_openxml import audit_office_file

    src = _pptx(tmp_path / "src.pptx", "The regime applies in areas beyond national jurisdiction.")
    dest = tmp_path / "out.pptx"
    apply_pptx(
        src,
        dest,
        [
            RewriteEdit(
                kind="replace",
                finding_ids=["a"],
                area="style",
                quote="areas beyond national jurisdiction",
                replacement="Areas Beyond National Jurisdiction",
            )
        ],
    )
    monkeypatch.setattr("paperful.rewrite_openxml.extra_available", lambda: True)

    def fake_sdk(path: Path) -> list[str]:
        shared = ["theme part warning"]
        if path == dest:
            return [*shared, "slide rel missing"]
        return shared

    monkeypatch.setattr("paperful.rewrite_openxml.sdk_errors", fake_sdk)
    cfg.rewrite_openxml_audit = True
    cfg.rewrite_openxml_audit_policy = "fail"
    row = audit_office_file(cfg, dest, source=src)
    assert row["format"] == "pptx"
    assert row["introduced"] == ["slide rel missing"]
    assert row["fail"] is True


def test_build_odt_from_paragraphs(tmp_path: Path):
    dest = tmp_path / "built.odt"
    edit = RewriteEdit(
        kind="replace",
        finding_ids=["a"],
        area="style",
        quote="Maritime Area beyond national jurisdictions",
        replacement="Areas Beyond National Jurisdiction",
    )
    skips = build_odt_from_paragraphs(
        dest,
        ["Maritime Area beyond national jurisdictions"],
        [edit],
    )
    assert skips == []
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert zf.read("mimetype") == b"application/vnd.oasis.opendocument.text"
        xml = zf.read("content.xml").decode("utf-8")
    assert "Areas Beyond National Jurisdiction" in xml
    assert odt_structural_issues(dest) == []


def test_rewrite_odt_output_from_markdown(cfg, tmp_path: Path):
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits", "odt"),
        comments="off",
        dry_run=False,
        llm_client=None,
    )
    folder = Path(result["pack_dir"])
    assert (folder / "tracked.odt").is_file()
    assert not (folder / "tracked.docx").exists()
    assert result.get("odt") == "tracked.odt"
    assert result.get("openxml_audit", {}).get("format") == "odt"
    xml = zipfile.ZipFile(folder / "tracked.odt").read("content.xml").decode("utf-8")
    assert "Areas Beyond National Jurisdiction" in xml


def test_rewrite_pdf_and_docx_from_markdown(cfg, tmp_path: Path, monkeypatch):
    from io import BytesIO

    from pypdf import PdfWriter

    def fake_pdf(_html: str) -> bytes:
        buf = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(buf)
        return buf.getvalue()

    monkeypatch.setattr("paperful.rewrite_pdf.html_to_pdf_bytes", fake_pdf)
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    pack = _pack([_finding()], path=str(src))
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits", "tracked", "pdf"),
        comments="off",
        dry_run=False,
        llm_client=None,
    )
    folder = Path(result["pack_dir"])
    assert (folder / "tracked.docx").is_file()
    assert (folder / "tracked.pdf").is_file()
    assert result.get("pdf") == "tracked.pdf"
    assert (result.get("pdf_audit") or {}).get("structural") == []
    from paperful.rewrite_pdf import html_from_paragraphs, pdf_structural_issues

    html_doc = html_from_paragraphs(
        ["Maritime Area beyond national jurisdictions"],
        [
            RewriteEdit(
                kind="replace",
                finding_ids=["a"],
                area="style",
                quote="Maritime Area beyond national jurisdictions",
                replacement="Areas Beyond National Jurisdiction",
            )
        ],
    )
    assert "Areas Beyond National Jurisdiction" in html_doc
    assert pdf_structural_issues(folder / "tracked.pdf") == []


def test_pdf_html_and_sticky_notes_include_comments(tmp_path: Path, monkeypatch):
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    from paperful.rewrite_pdf import build_pdf_from_paragraphs, html_from_paragraphs

    def fake_pdf(_html: str) -> bytes:
        buf = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(buf)
        return buf.getvalue()

    monkeypatch.setattr("paperful.rewrite_pdf.html_to_pdf_bytes", fake_pdf)
    edits = [
        RewriteEdit(
            kind="comment",
            finding_ids=["c"],
            area="comments",
            quote="policy instruments",
            body="Clarify this claim.",
            loc="para 1",
        )
    ]
    html_doc = html_from_paragraphs(
        ["Unique span here about policy instruments."],
        edits,
    )
    assert "pf-cmt" in html_doc
    assert "[1]" in html_doc
    assert "Clarify this claim." in html_doc
    assert "Comments" in html_doc
    dest = tmp_path / "tracked.pdf"
    issues = build_pdf_from_paragraphs(
        dest,
        ["Unique span here about policy instruments."],
        edits,
    )
    assert issues == []
    reader = PdfReader(str(dest))
    annots = reader.pages[-1].get("/Annots")
    assert annots
    contents = str(annots[0].get_object().get("/Contents") or "")
    assert "Clarify this claim." in contents
