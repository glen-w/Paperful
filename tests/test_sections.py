"""Structured section extract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, load_config
from paperful.sections.command import SCHEMA, extract_item, write_item
from paperful.sections.extract import extract_fields
from paperful.sections.headings import canonical_for_heading, clear_heading_cache
from paperful.store import MirrorEntry
from paperful.store import write_json

runner = CliRunner()


def _imrad_pages() -> list[str]:
    p1 = (
        "Abstract\n\n"
        "We study ocean governance with a long abstract body that exceeds "
        "the minimum length required for a valid section extract here.\n\n"
        "Introduction\n\n"
        "Background on the topic.\n\n"
        "Methods\n\n"
        "We surveyed twelve sites using structured interviews and coding. "
        "Each site received the same protocol, blinded coders, and inter-rater checks.\n\n"
        "Results\n\n"
        "Most sites showed improvement.\n\n"
        "Discussion\n\n"
        "The findings suggest policy gaps.\n\n"
        "Conclusion\n\n"
        "Marine policy should adopt stronger monitoring frameworks soon. "
        "Future work must tie enforcement data to measurable ecological outcomes.\n\n"
        "Research questions\n\n"
        "RQ1. How do institutions adapt?\n"
        "RQ2. What limits enforcement?\n"
    )
    return [p1]


def test_canonical_for_heading_synonyms():
    assert canonical_for_heading("Materials and Methods") == "methodology"
    assert canonical_for_heading("Conclusions") == "conclusion"


def test_extract_fields_imrad(cfg: Config):
    result = extract_fields(
        cfg,
        _imrad_pages(),
        record_abstract="",
        mvp_fields=cfg.extract_sections_fields,
        raw_map=True,
        max_field_chars=20_000,
    )
    assert result.fields["abstract"] is not None
    assert "governance" in result.fields["abstract"]["text"].lower()
    assert result.fields["methodology"] is not None
    assert result.fields["conclusion"] is not None
    assert result.fields["research_questions"]
    assert "methodology" not in result.missing


def test_short_section_stays_missing(cfg: Config):
    pages = ["Methods\n\nToo short.\n\nResults\n\n" + ("x" * 120)]
    result = extract_fields(
        cfg,
        pages,
        mvp_fields=("methodology", "abstract"),
        raw_map=False,
        max_field_chars=5000,
    )
    assert result.fields["methodology"] is None
    assert "methodology" in result.missing


def test_heading_overlay(tmp_path: Path, cfg: Config):
    overlay = tmp_path / "section-headings.toml"
    overlay.write_text('methodology = ["custom methods lane"]\n', encoding="utf-8")
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True)
    import shutil

    shutil.copy(overlay, cfg.state_dir / "section-headings.toml")
    clear_heading_cache()
    pages = [
        "Custom Methods Lane\n\n"
        + ("We applied a mixed-methods design with interviews. " * 5)
    ]
    result = extract_fields(
        cfg,
        pages,
        mvp_fields=("methodology",),
        raw_map=False,
        max_field_chars=5000,
    )
    clear_heading_cache()
    assert result.fields["methodology"] is not None


def test_write_and_load_item(cfg: Config):
    entry = MirrorEntry(
        key="KEY1",
        dirs=["coll/item -- KEY1"],
        record={"abstract": "", "title": "T", "year": 2020},
        pdfs=[],
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    folder = cfg.out_dir / "coll" / "item -- KEY1"
    folder.mkdir(parents=True)
    text = "\n\n".join(_imrad_pages())
    (folder / "paper.pdf").write_bytes(b"%PDF-1.4\n")  # may fail parse; use cache
    from paperful.rag.extract import TEXT_SCHEMA, text_cache_path

    write_json(
        text_cache_path(cfg, "KEY1"),
        {"schema": TEXT_SCHEMA, "pages": _imrad_pages()},
    )
    item = extract_item(cfg, entry, use_llm=False)
    assert item is not None
    path = write_item(cfg, item)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA


def test_config_extract_sections_table(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[extract_sections]
llm = true
raw_map = false
max_field_chars = 15000
fields = ["abstract", "conclusion"]
""",
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert cfg.extract_sections_llm is True
    assert cfg.extract_sections_raw_map is False
    assert cfg.extract_sections_max_field_chars == 15000
    assert cfg.extract_sections_fields == ("abstract", "conclusion")


def test_cli_extract_sections_dry_run(cfg: Config, tmp_path: Path):
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    toml = tmp_path / "paperful.toml"
    toml.write_text(
        f'email = "{cfg.email}"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n',
        encoding="utf-8",
    )
    coll = cfg.out_dir / "BBNJ" / "Paper -- KEY99"
    coll.mkdir(parents=True)
    write_json(
        coll / "record.json",
        {
            "schema": "paperful.item.v1",
            "item_key": "KEY99",
            "title": "Paper",
            "year": 2020,
            "abstract": "",
        },
    )
    from paperful.rag.extract import TEXT_SCHEMA, text_cache_path

    write_json(
        text_cache_path(cfg, "KEY99"),
        {"schema": TEXT_SCHEMA, "pages": _imrad_pages()},
    )
    res = runner.invoke(
        cli.app,
        ["extract-sections", "-C", "BBNJ", "--dry-run", "-c", str(toml)],
    )
    assert res.exit_code == 0, res.stdout
    assert not list((cfg.state_dir / "sections").glob("*.json"))


def test_fill_missing_llm_grounding(cfg: Config):
    from paperful.sections.llm import fill_missing_llm

    class FakeChat:
        def chat_stream(self, request):
            yield json.dumps(
                {
                    "abstract": "Totally invented abstract with no overlap.",
                    "methodology": (
                        "We surveyed twelve sites using structured interviews and coding "
                        "with the same protocol described in the excerpt."
                    ),
                }
            )

    pages = _imrad_pages()
    excerpt_body = pages[0]
    out = fill_missing_llm(
        cfg,
        pages=pages,
        record_abstract="",
        section_bodies=[excerpt_body],
        missing=["abstract", "methodology"],
        client=FakeChat(),
    )
    assert "abstract" not in out
    assert out.get("methodology", {}).get("provenance") == "llm"


def test_extract_scope_skips_existing_without_force(cfg: Config):
    from paperful.sections.command import extract_scope, write_item, ItemSections

    entry = MirrorEntry(
        key="SKIP1",
        dirs=["c/x -- SKIP1"],
        record={"abstract": "", "title": "T", "year": 2019},
        pdfs=[],
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    (cfg.out_dir / "c" / "x -- SKIP1").mkdir(parents=True)
    from paperful.rag.extract import TEXT_SCHEMA, text_cache_path

    write_json(
        text_cache_path(cfg, "SKIP1"),
        {"schema": TEXT_SCHEMA, "pages": _imrad_pages()},
    )
    write_item(
        cfg,
        ItemSections(
            schema=SCHEMA,
            item_key="SKIP1",
            title="T",
            year=2019,
            source="pdf",
            fields={"abstract": {"text": "cached", "provenance": "rule"}},
        ),
    )
    items = extract_scope(
        cfg,
        item_keys=["SKIP1"],
        force=False,
        skip_existing=True,
    )
    assert len(items) == 1
    assert items[0].fields["abstract"]["text"] == "cached"


def test_cli_requires_scope(cfg: Config, tmp_path: Path):
    toml = tmp_path / "paperful.toml"
    toml.write_text(
        f'email = "{cfg.email}"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n',
        encoding="utf-8",
    )
    res = runner.invoke(cli.app, ["extract-sections", "-c", str(toml)])
    assert res.exit_code == 1
