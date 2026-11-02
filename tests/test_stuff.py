"""Stuff pack: manuscript sentences, outline sections, fail-closed index."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from paperful.cli import app
from paperful.config import Config, load_config
from paperful.critique_extract import ExtractedDoc
from paperful.stuff import (
    HONESTY_BANNER,
    STUFF_PACK_KEYS,
    canonical_lane,
    collect_pack,
    pack_payload,
    render_markdown,
    resolve_k,
    resolve_lane,
    write_pack,
)


LONG = (
    "Area-based management tools in areas beyond national jurisdiction "
    "need a clear legal warrant from the Agreement."
)

MS = f"""{LONG}

Short.

References

Smith, A. 2019. Bibliographic leftover that should not be stuffed as a claim.
"""

OUTLINE = """Working title. Sharing Suspicion, Not Data. Audience is AML policy.

1. Introduction

The compliance problem and why banks share suspicion, not customer data.
Suggested length 800 words.

2. Methodology

What an SoK is and why it suits a policy question better than a literature review.

3. Legal analysis

Five regimes compared. Article 75 as operating requirements for encrypted matching.

References

Leftover bibliography that must not become a stuffed section.
"""


def _doc(text: str) -> ExtractedDoc:
    paras = [p for p in text.split("\n\n") if p.strip()]
    return ExtractedDoc(
        text=text,
        format="md",
        paragraphs=paras or [text],
        loc_kind="paragraph",
    )


def _hit(item_key="ITEM0001", **overrides):
    base = dict(
        item_key=item_key,
        title="Held paper",
        score=0.91,
        text="Area-based management in ABNJ",
        doi="10.1000/held",
        year=2019,
        pages="p. 3",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_canonical_lane_rejects_unknown():
    try:
        canonical_lane("reviewers")
    except ValueError as exc:
        assert "outline" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert canonical_lane("Outline") == "outline"


def test_resolve_k_caps_at_rag_top_k():
    cfg = Config(stuff_k=10, rag_top_k=2)
    assert resolve_k(cfg, None) == 2
    assert resolve_k(cfg, 1) == 1
    assert resolve_k(cfg, 9) == 2


def test_manuscript_skips_short_and_bibliography(cfg):
    seen: list[str] = []

    def search_fn(query, *, k, keys):
        seen.append(query)
        return [_hit()]

    rows, skips, ledger = collect_pack(
        cfg, _doc(MS), lane="manuscript", k=3, search_fn=search_fn
    )
    assert ledger is None
    assert len(rows) == 1
    assert LONG in rows[0].quote
    assert rows[0].hits[0].item_key == "ITEM0001"
    reasons = {s.reason for s in skips}
    assert "short" in reasons
    assert "biblio" in reasons
    assert any("References" in s.quote for s in skips if s.reason == "biblio")
    assert all("Bibliographic leftover" not in q for q in seen)
    assert len(seen) == 1


def test_outline_sections_skip_references_keep_thin_heading(cfg):
    seen: list[str] = []

    def search_fn(query, *, k, keys):
        seen.append(query)
        return [_hit("LIB1"), _hit("LIB2")]

    rows, skips, ledger = collect_pack(
        cfg, _doc(OUTLINE), lane="outline", k=2, search_fn=search_fn
    )
    headings = {r.heading for r in rows}
    assert "1. Introduction" in headings
    assert "2. Methodology" in headings
    assert "3. Legal analysis" in headings
    assert ledger
    led_heads = {row["heading"] for row in ledger}
    assert headings <= led_heads
    assert any(s.reason == "biblio" and "References" in s.quote for s in skips)
    assert all("Leftover bibliography" not in q for q in seen)
    assert all(len(r.hits) <= 2 for r in rows)


def test_source_item_never_listed_as_hit(cfg):
    def search_fn(query, *, k, keys):
        return [_hit("SELF"), _hit("OTHER")]

    rows, _skips, _ledger = collect_pack(
        cfg,
        _doc(MS),
        lane="manuscript",
        k=3,
        exclude_key="SELF",
        search_fn=search_fn,
    )
    keys = {h.item_key for r in rows for h in r.hits}
    assert "SELF" not in keys
    assert "OTHER" in keys


def test_over_cap_skips_remaining_units(cfg):
    cfg.stuff_max_units = 1
    calls = {"n": 0}

    def search_fn(query, *, k, keys):
        calls["n"] += 1
        return [_hit()]

    text = f"{LONG}\n\n{LONG.replace('warrant', 'procedure')}\n"
    rows, skips, _ = collect_pack(
        cfg, _doc(text), lane="manuscript", k=1, search_fn=search_fn
    )
    assert len(rows) == 1
    assert calls["n"] == 1
    assert any(s.reason == "over_cap" for s in skips)


def test_write_pack_frozen_keys_and_honesty(cfg):
    rows, skips, _ = collect_pack(
        cfg,
        _doc(MS),
        lane="manuscript",
        k=1,
        search_fn=lambda query, k, keys: [_hit()],
    )
    payload = pack_payload(
        cid="file-draft",
        scope="index",
        lane="manuscript",
        k=1,
        inp={"kind": "file", "title": "draft.md"},
        rows=rows,
        skips=skips,
    )
    folder = write_pack(cfg, payload, stamp="20260101T000000Z")
    pack = (folder / "pack.json").read_text(encoding="utf-8")
    assert STUFF_PACK_KEYS <= set(__import__("json").loads(pack))
    md = (folder / "pack.md").read_text(encoding="utf-8")
    assert HONESTY_BANNER in md
    assert "invent BibTeX" in md
    assert "## Claims" in md


def test_outline_markdown_has_ledger(cfg):
    rows, skips, ledger = collect_pack(
        cfg,
        _doc(OUTLINE),
        lane="outline",
        k=1,
        search_fn=lambda query, k, keys: [_hit()],
    )
    payload = pack_payload(
        cid="file-outline",
        scope="index",
        lane="outline",
        k=1,
        inp={"kind": "file", "title": "outline.md"},
        rows=rows,
        skips=skips,
        ledger=ledger,
    )
    md = render_markdown(payload)
    assert "## Outline" in md
    assert "1. Introduction" in md


def test_stuff_config_from_toml(tmp_path):
    bare = Config()
    assert bare.stuff_k == 3
    assert bare.stuff_lane == "manuscript"
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[stuff]\nk = 2\nlane = "outline"\n'
        "min_sentence_words = 5\nmax_units = 9\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.stuff_k == 2
    assert cfg.stuff_lane == "outline"
    assert cfg.stuff_min_sentence_words == 5
    assert cfg.stuff_max_units == 9
    assert resolve_lane(cfg, None) == "outline"
    assert resolve_lane(cfg, "manuscript") == "manuscript"


def test_cli_requires_item_or_file(cfg, tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(app, ["stuff", "--config", str(cfg_path)])
    assert res.exit_code == 1, (res.stdout, res.stderr, res.exception)
    out = f"{res.stdout or ''}{res.stderr or ''}{res.output or ''}"
    assert "--item" in out and "--file" in out


def test_cli_unknown_lane_exits_1(tmp_path, cfg):
    src = tmp_path / "draft.md"
    src.write_text(LONG + "\n", encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n[rag]\nenabled = true\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        app,
        ["stuff", "--file", str(src), "--lane", "reviewers", "--config", str(cfg_path)],
    )
    assert res.exit_code == 1
    assert "lane" in ((res.stdout or "") + (res.output or "")).lower()


def test_cli_empty_index_exits_1(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.md"
    src.write_text(LONG + "\n", encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n[rag]\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("paperful.cli_runtime._rag_require", lambda _cfg: None)
    monkeypatch.setattr("paperful.cli_runtime._rag_embedder", lambda _cfg: object())

    class Empty:
        def count(self):
            return 0

    monkeypatch.setattr(
        "paperful.cli_runtime._rag_open", lambda _cfg: (Empty(), object())
    )
    res = CliRunner().invoke(
        app, ["stuff", "--file", str(src), "--config", str(cfg_path)]
    )
    assert res.exit_code == 1
    assert "empty" in ((res.stdout or "") + (res.output or "")).lower()


def test_cli_file_writes_pack(cfg, tmp_path, monkeypatch):
    src = tmp_path / "draft.md"
    src.write_text(MS, encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n[rag]\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("paperful.cli_runtime._rag_require", lambda _cfg: None)
    monkeypatch.setattr("paperful.cli_runtime._rag_embedder", lambda _cfg: object())

    class Index:
        def count(self):
            return 4

    monkeypatch.setattr(
        "paperful.cli_runtime._rag_open", lambda _cfg: (Index(), object())
    )
    monkeypatch.setattr(
        "paperful.rag.retrieve.scope_keys",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "paperful.rag.retrieve.search",
        lambda *a, **k: [_hit()],
    )
    res = CliRunner().invoke(
        app,
        [
            "stuff",
            "--file",
            str(src),
            "--config",
            str(cfg_path),
            "--k",
            "2",
        ],
    )
    assert res.exit_code == 0, res.output
    packs = list((cfg.state_dir / "stuff").glob("**/pack.json"))
    assert packs
    md = packs[0].with_name("pack.md").read_text(encoding="utf-8")
    assert "Stuff pack" in md
    assert HONESTY_BANNER.split(".")[0] in md


def test_list_recent_stuff_and_markdown_jail(tmp_path):
    from paperful.ui.ask_rows import list_recent_stuff, stuff_pack_markdown

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    folder = cfg.state_dir / "stuff" / "file-draft" / "20261102T000000Z"
    folder.mkdir(parents=True)
    (folder / "pack.json").write_text(
        '{"input": {"title": "Draft"}, "counts": {"units": 3}}',
        encoding="utf-8",
    )
    (folder / "pack.md").write_text("# Stuff pack\n", encoding="utf-8")
    rows = list_recent_stuff(cfg)
    assert len(rows) == 1
    assert rows[0]["stuff_id"] == "file-draft"
    assert rows[0]["units"] == 3
    assert stuff_pack_markdown(cfg, str(folder)).startswith("# Stuff pack")
    assert stuff_pack_markdown(cfg, str(tmp_path / "other")) == ""


def test_jobs_stuff_fails_when_rag_off(tmp_path):
    from paperful.ui import commands, jobs

    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.rag_enabled = False
    rec = {
        "id": "abc123def456",
        "verb": "stuff",
        "status": "running",
        "args": {},
    }
    commands.write_command(cfg, rec)
    jobs.stuff(cfg, rec["id"], item_key="", staged_path=None, collection="")
    out = commands.read_command(cfg, rec["id"]) or {}
    assert out.get("status") == "failed"
    assert "[rag]" in (out.get("error") or "")
