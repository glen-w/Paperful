"""Attachment classification and refuse rules. No Zotero."""

from pathlib import Path

from paperful.attachments import (
    MirrorPdf,
    PdfChild,
    SurgeryFlags,
    apply_refusal,
    classify_parent,
    plan_actions,
)

OUT = Path("/tmp/paperful-out")
STEM = "Smith - 2020 - Title.pdf"
MD5 = "abc123"


def _child(
    key: str,
    *,
    mode: str = "imported_file",
    filename: str = "paper.pdf",
    md5: str | None = MD5,
    path: str | None = None,
    present: bool = True,
    parent: str = "P1",
) -> PdfChild:
    return PdfChild(key, parent, filename, mode, md5, path, present)


def _kinds(findings) -> set[str]:
    return {f.kind for f in findings}


def test_ghost_with_mirror_bytes_is_repairable():
    mirror = [MirrorPdf(str(OUT / "BBNJ" / "x.pdf"), MD5, "x.pdf")]
    child = _child("A", present=False)
    findings = classify_parent("P1", [child], mirror, STEM)
    assert "ghost" in _kinds(findings)
    assert "unrepairable" not in _kinds(findings)


def test_ghost_without_mirror_is_unrepairable():
    child = _child("A", present=False)
    findings = classify_parent("P1", [child], [], STEM)
    assert "unrepairable" in _kinds(findings)
    assert "ghost" not in _kinds(findings)


def test_broken_link_and_same_md5_duplicate():
    missing = _child(
        "L",
        mode="linked_file",
        path="/gone/paper.pdf",
        present=False,
        filename="paper.pdf",
    )
    other = _child("S", filename="paper.pdf")
    findings = classify_parent("P1", [missing, other], [], STEM)
    assert "unrepairable" in _kinds(findings)
    assert "duplicate_file" in _kinds(findings)
    assert "ok" in _kinds(findings)


def test_rename_drift():
    child = _child("A", filename="paper.pdf")
    findings = classify_parent("P1", [child], [], STEM)
    assert "rename_drift" in _kinds(findings)


def test_link_refused_for_group_library():
    child = _child("A", filename=STEM)
    mirror = [MirrorPdf(str(OUT / "BBNJ" / STEM), MD5, STEM)]
    scan = plan_actions(
        [child],
        {"P1": mirror},
        {"P1": STEM},
        SurgeryFlags(link=True),
        out_dir=OUT,
        library_type="group",
    )
    assert scan.refusals
    assert all(action.op != "link" for action in scan.actions)


def test_rename_refuses_linked_file_outside_out():
    child = _child(
        "L",
        mode="linked_file",
        path="/Users/other/paper.pdf",
        filename="paper.pdf",
        present=True,
    )
    scan = plan_actions(
        [child],
        {"P1": []},
        {"P1": STEM},
        SurgeryFlags(rename=True),
        out_dir=OUT,
        library_type="user",
    )
    assert any("outside out/" in line for line in scan.refusals)
    assert all(action.op != "rename_linked" for action in scan.actions)


def test_broken_link_with_matching_mirror_plans_relink():
    mirror = [MirrorPdf(str(OUT / "BBNJ" / "x.pdf"), MD5, "x.pdf")]
    child = _child("L", mode="linked_file", path="/gone/paper.pdf", present=False)
    scan = plan_actions(
        [child],
        {"P1": mirror},
        {"P1": STEM},
        SurgeryFlags(fix_broken=True),
        out_dir=OUT,
    )
    assert "broken_link" in _kinds(scan.findings)
    assert [a.op for a in scan.actions] == ["relink"]
    assert scan.actions[0].source_path == mirror[0].path


def test_merge_keeps_the_stored_file_with_bytes():
    keeper = _child("KEEP", present=True)
    extra = _child("DROP", present=True)
    scan = plan_actions(
        [keeper, extra],
        {"P1": []},
        {"P1": STEM},
        SurgeryFlags(merge_files=True),
        out_dir=OUT,
    )
    assert [a.op for a in scan.actions] == ["trash"]
    assert scan.actions[0].attachment_key == "DROP"


def test_link_refuses_a_mirror_outside_out():
    outside = MirrorPdf("/Users/other/paper.pdf", MD5, "paper.pdf")
    child = _child("A", filename=STEM)
    scan = plan_actions(
        [child],
        {"P1": [outside]},
        {"P1": STEM},
        SurgeryFlags(link=True),
        out_dir=OUT,
    )
    assert any("no matching PDF under out/" in line for line in scan.refusals)
    assert scan.actions == []


def test_link_uses_the_matching_md5_not_the_first_pdf():
    other = MirrorPdf(str(OUT / "BBNJ" / "other.pdf"), "ffff", "other.pdf")
    match = MirrorPdf(str(OUT / "BBNJ" / STEM), MD5, STEM)
    child = _child("A", filename="scan.pdf")
    scan = plan_actions(
        [child],
        {"P1": [other, match]},
        {"P1": STEM},
        SurgeryFlags(link=True),
        out_dir=OUT,
    )
    assert scan.actions[0].op == "link"
    assert scan.actions[0].source_path == match.path
    assert scan.actions[0].trash_keys == ("A",)


def test_surgery_order_is_repair_then_merge_then_rename_then_link():
    ghost = _child("GHOST", present=False, filename="old.pdf")
    extra = _child("EXTRA", present=True, filename="old.pdf")
    mirror = [MirrorPdf(str(OUT / "BBNJ" / "old.pdf"), MD5, "old.pdf")]
    scan = plan_actions(
        [ghost, extra],
        {"P1": mirror},
        {"P1": STEM},
        SurgeryFlags(fix_broken=True, merge_files=True, rename=True, link=True),
        out_dir=OUT,
    )
    assert [a.op for a in scan.actions] == ["trash", "rename_file", "link"]
    assert scan.actions[0].attachment_key == "GHOST"
    assert scan.actions[-1].attachment_key == "EXTRA"
    assert scan.actions[-1].source_path.endswith(STEM)


def test_apply_refuses_a_path_outside_out(tmp_path):
    from paperful.attachments import Action, apply_actions

    class Backend:
        def trash_item(self, key):
            raise AssertionError(key)

    action = Action("trash", "P1", "A", source_path="/Users/other/paper.pdf")
    # trash has no path check; the path guard is on file ops
    move = Action(
        "rename_file",
        "P1",
        source_path="/Users/other/paper.pdf",
        filename="moved.pdf",
    )
    done, errors = apply_actions(Backend(), [move], out_dir=tmp_path)
    assert done == 0
    assert errors and "outside out/" in errors[0]
    assert action.op == "trash"
    assert apply_refusal(manager="mendeley", library_type="user", link=False)
    assert apply_refusal(manager="zotero", library_type="group", link=True)
    assert apply_refusal(manager="zotero", library_type="user", link=True) is None


def test_attachment_has_bytes_uses_the_file_fetch():
    from paperful.library import ZoteroBackend

    class FakeZot:
        def file(self, key):
            if key == "ok":
                return b"%PDF"
            if key == "empty":
                return b""
            raise OSError("missing")

    class FakeLocal:
        zot = FakeZot()

    backend = ZoteroBackend.__new__(ZoteroBackend)
    backend.zl = FakeLocal()
    assert backend.attachment_has_bytes("ok") is True
    assert backend.attachment_has_bytes("empty") is False
    assert backend.attachment_has_bytes("missing") is False
