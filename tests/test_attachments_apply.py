"""Attachment surgery apply ops (tmp_path, no Zotero)."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from paperful.attachments import Action, _apply_one, apply_actions, _trash_attachment


class Backend:
    def __init__(self):
        self.trashed = []
        self.relinked = []
        self.attached = []
        self.linked = []
        self.refreshed = []

    def trash_attachment(self, key):
        self.trashed.append(key)

    def relink_file(self, key, path):
        self.relinked.append((key, Path(path)))

    def attach(self, parent, path, title=""):
        self.attached.append((parent, Path(path), title))
        return SimpleNamespace(ok=True, reason="")

    def create_linked_file(self, parent, path):
        self.linked.append((parent, Path(path)))

    def refresh(self, key):
        self.refreshed.append(key)


def test_apply_trash_rename_relink_link(tmp_path):
    item = tmp_path / "Smith - 2020 - Title.pdf"
    item.write_bytes(b"pdf-bytes")
    backend = Backend()
    actions = [
        Action(op="trash", parent_key="P1", attachment_key="A1"),
        Action(
            op="rename_file",
            parent_key="P1",
            source_path=str(item),
            filename="renamed.pdf",
        ),
        Action(
            op="relink",
            parent_key="P1",
            attachment_key="A2",
            source_path=str(tmp_path / "renamed.pdf"),
        ),
        Action(
            op="link",
            parent_key="P1",
            source_path=str(tmp_path / "renamed.pdf"),
            trash_keys=("OLD",),
        ),
    ]
    done, errors = apply_actions(backend, actions, out_dir=tmp_path)
    assert not errors
    assert done == 4
    assert "A1" in backend.trashed
    assert "OLD" in backend.trashed
    assert backend.relinked
    assert backend.linked
    assert backend.refreshed


def test_apply_refill_and_rename_upload(tmp_path):
    src = tmp_path / "paper.pdf"
    src.write_bytes(b"pdf")
    backend = Backend()
    refill = Action(
        op="refill",
        parent_key="P1",
        source_path=str(src),
        trash_keys=("GHOST",),
    )
    upload = Action(
        op="rename_upload",
        parent_key="P1",
        source_path=str(src),
        trash_keys=("OLD",),
    )
    done, errors = apply_actions(backend, [refill, upload], out_dir=tmp_path)
    assert not errors and done == 2
    assert backend.attached
    assert "GHOST" in backend.trashed


def test_apply_unknown_and_missing_file(tmp_path):
    backend = Backend()
    with pytest.raises(RuntimeError, match="unknown action"):
        _apply_one(backend, Action(op="nope", parent_key="P"), tmp_path)
    missing = Action(
        op="link",
        parent_key="P",
        source_path=str(tmp_path / "gone.pdf"),
    )
    with pytest.raises(RuntimeError, match="file missing"):
        _apply_one(backend, missing, tmp_path)
    with pytest.raises(RuntimeError, match="outside"):
        _apply_one(
            backend,
            Action(op="relink", parent_key="P", attachment_key="A", source_path="/etc/passwd"),
            tmp_path,
        )


def test_trash_falls_back_to_trash_item():
    seen = []
    backend = SimpleNamespace(trash_item=lambda k: seen.append(k))
    _trash_attachment(backend, "X")
    assert seen == ["X"]
    with pytest.raises(RuntimeError, match="missing attachment key"):
        _trash_attachment(backend, None)


def test_rename_linked_and_attach_failure(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"aa")
    backend = Backend()
    _apply_one(
        backend,
        Action(
            op="rename_linked",
            parent_key="P",
            attachment_key="A",
            source_path=str(src),
            filename="b.pdf",
        ),
        tmp_path,
    )
    assert backend.relinked[0][1].name == "b.pdf"

    backend.attach = lambda *_a, **_k: SimpleNamespace(ok=False, reason="no")
    with pytest.raises(RuntimeError, match="no"):
        _apply_one(
            backend,
            Action(op="refill", parent_key="P", source_path=str(tmp_path / "b.pdf")),
            tmp_path,
        )
