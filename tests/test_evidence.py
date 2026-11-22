"""Sourced evidence table: quote or check this. No LLM."""

from __future__ import annotations

from typer.testing import CliRunner

from paperful.cli import app
from paperful.evidence import (
    CHECK_THIS,
    EVIDENCE_PACK_KEYS,
    HONESTY_BANNER,
    collect_item,
    pack_payload,
    quoted_span,
    sample_size_cell,
    write_pack,
)
from tests.conftest import make_item


def _item(**overrides):
    base = dict(
        key="ABCD1234",
        item_type="journalArticle",
        title="Marine governance",
        has_pdf=True,
        pdf_path="/tmp/out/marine -- ABCD1234/paper.pdf",
    )
    base.update(overrides)
    return make_item(**base)


def _pages() -> list[str]:
    return [
        (
            "Methods\n\n"
            "We surveyed twelve sites using structured interviews and coding. "
            "Each site received the same protocol, blinded coders, and inter-rater "
            "checks with n = 42 participants in 2019 field sites across the basin.\n\n"
            "Results\n\n"
            "Most sites showed improvement under the ABC protocol after the first "
            "season of monitoring and the yield rose forty percent in coded notes.\n\n"
            "Conclusion\n\n"
            "Marine policy should adopt stronger monitoring frameworks soon. "
            "Future work must tie enforcement data to measurable ecological outcomes.\n"
        )
    ]


def test_quoted_span_or_check_this():
    pages = _pages()
    cell, loc = quoted_span(
        "We surveyed twelve sites using structured interviews and coding.",
        pages,
    )
    assert cell != CHECK_THIS
    assert "surveyed twelve sites" in cell.lower()
    assert loc.startswith("p.")
    missing, _ = quoted_span("A claim that is not in the PDF at all.", pages)
    assert missing == CHECK_THIS


def test_sample_size_requires_quote():
    pages = _pages()
    cell, loc = sample_size_cell(pages[0], pages)
    assert "42" in cell
    assert loc.startswith("p.")
    empty, _ = sample_size_cell("No sample size here.", pages)
    assert empty == CHECK_THIS


def test_collect_and_write_pack(cfg, monkeypatch):
    monkeypatch.setattr("paperful.evidence.pdf_pages_for", lambda *a, **k: _pages())
    item = _item()
    from paperful.evidence import EvidenceBatch, EvidenceRow

    row = collect_item(cfg, item, None, None)
    assert isinstance(row, EvidenceRow)
    assert row.key == "ABCD1234"
    assert row.design == "journalArticle"
    assert row.n != CHECK_THIS
    assert "42" in row.n
    assert row.method != CHECK_THIS
    batch = EvidenceBatch(rows=[row])
    payload = pack_payload(evidence_id="bbnj", scope="BBNJ", batch=batch)
    folder = write_pack(cfg, payload, stamp="20260101T000000Z")
    data = (folder / "pack.json").read_text(encoding="utf-8")
    import json

    parsed = json.loads(data)
    assert EVIDENCE_PACK_KEYS <= set(parsed)
    md = (folder / "pack.md").read_text(encoding="utf-8")
    assert HONESTY_BANNER in md
    csv_text = (folder / "table.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("key,")
    assert "ABCD1234" in csv_text
    assert str(folder).endswith("evidence/20260101T000000Z")


def test_missing_pdf_is_skip(cfg):
    from paperful.evidence import EvidenceSkip, collect_item

    row = collect_item(cfg, _item(has_pdf=False), None, None)
    assert isinstance(row, EvidenceSkip)
    assert row.reason == "no PDF"


def test_cli_evidence_help_lists_honesty():
    res = CliRunner().invoke(app, ["evidence", "--help"])
    assert res.exit_code == 0
    out = (res.stdout or "") + (res.output or "")
    assert "check this" in out.lower() or "sourced" in out.lower()


def test_cli_evidence_refuses_apply(tmp_path, cfg):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        app,
        ["evidence", "--apply", "-C", "BBNJ", "--config", str(cfg_path)],
    )
    assert res.exit_code == 1
    out = (res.stdout or "") + (res.output or "")
    assert "apply" in out.lower()
