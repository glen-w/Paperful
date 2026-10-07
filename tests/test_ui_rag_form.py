"""Index RAG form helpers (scope, prompt precedence, saved prompts)."""

from __future__ import annotations

from paperful.config import Config
from paperful.ui.rag_form import (
    list_saved_prompts,
    parse_item_keys,
    parse_rag_scope,
    resolve_prompt_from_form,
    save_prompt_as,
    scope_has_target,
)


class _Form(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_parse_item_keys_lines_and_commas():
    assert parse_item_keys("A1\nB2, C3") == ["A1", "B2", "C3"]


def test_scope_has_target_rules():
    empty = parse_rag_scope(_Form(), "", year_from=None, year_to=None)
    assert not scope_has_target(empty)
    assert scope_has_target(empty, whole_library=True)
    with_coll = parse_rag_scope(_Form(), "ocean/BBNJ", year_from=None, year_to=None)
    assert scope_has_target(with_coll)


def test_prompt_precedence_path_before_saved(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    path_file = tmp_path / "path.md"
    path_file.write_text("from path")
    saved = save_prompt_as(cfg, "saved.md", "from saved")
    assert saved is not None
    form = _Form(
        {
            "prompt_path": str(path_file),
            "prompt_saved": "saved.md",
        }
    )
    resolved = resolve_prompt_from_form(cfg, form)
    assert resolved.prompt_path == str(path_file)
    assert resolved.prompt_text is None


def test_prompt_inline_wins_over_path(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    path_file = tmp_path / "path.md"
    path_file.write_text("from path")
    form = _Form({"prompt_inline": "inline wins", "prompt_path": str(path_file)})
    resolved = resolve_prompt_from_form(cfg, form)
    assert resolved.prompt_text == "inline wins"


def test_prompt_upload_persists_under_gui_uploads(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    form = _Form()
    resolved = resolve_prompt_from_form(
        cfg,
        form,
        upload_bytes=b"uploaded prompt body",
        upload_name="custom.md",
    )
    assert resolved.prompt_path is not None
    path = __import__("pathlib").Path(resolved.prompt_path)
    assert path.is_file()
    assert "gui/uploads" in str(path).replace("\\", "/")
    assert path.read_text(encoding="utf-8").strip() == "uploaded prompt body"


def test_list_and_save_prompts(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    assert list_saved_prompts(cfg) == []
    assert save_prompt_as(cfg, "", "x") is None
    path = save_prompt_as(cfg, "my prompt", "Be terse.")
    assert path is not None and path.name == "my-prompt.md"
    rows = list_saved_prompts(cfg)
    assert {r["name"] for r in rows} == {"my-prompt.md"}
