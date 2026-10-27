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
from paperful.rewrite_areas import bucket_findings, parse_rewrite_areas_list
from paperful.rewrite_docx import apply_tracked_docx, build_docx_from_paragraphs
from paperful.rewrite_llm import edit_is_grounded
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
