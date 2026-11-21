"""Ask claim-check: deterministic labels, fail-closed index, flag conflicts."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from paperful.cli import app
from paperful.claim_check import (
    CLAIM_CHECK_PACK_KEYS,
    HONESTY_BANNER,
    MIXED_PHRASE,
    collect_claim_check,
    label_hits,
    pack_payload,
    write_pack,
)
from paperful.peer_review_extract import ExtractedDoc


LONG = (
    "Area-based management tools in areas beyond national jurisdiction "
    "need a clear legal warrant from the Agreement."
)

UNRELATED = "The committee met on Tuesday to discuss catering."


def _doc(text: str) -> ExtractedDoc:
    paras = [p for p in text.split("\n\n") if p.strip()]
    return ExtractedDoc(
        text=text,
        format="md",
        paragraphs=paras or [text],
        loc_kind="paragraph",
    )


def _hit(text: str, item_key: str = "LIB1", **overrides):
    base = dict(
        item_key=item_key,
        title="Held paper",
        text=text,
        pages="p. 3",
        score=0.9,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_label_supported_quote_in_chunk():
    chunk = LONG + " Field sites were compared in 2019."
    status, note, hits = label_hits(LONG, [_hit(chunk)])
    assert status == "supported"
    assert note == ""
    assert hits
    assert hits[0].quote
    assert hits[0].quote.lower() in chunk.lower() or hits[0].quote in chunk


def test_label_unsupported_empty_hits():
    status, note, hits = label_hits(LONG, [])
    assert status == "unsupported"
    assert note == ""
    assert hits == []


def test_label_mixed_when_hits_do_not_state_claim():
    status, note, hits = label_hits(LONG, [_hit(UNRELATED)])
    assert status == "mixed"
    assert note == MIXED_PHRASE
    assert hits


def test_collect_and_write_pack(cfg):
    def search_fn(query, *, k, keys):
        return [_hit(LONG + " Extra held sentence.")]

    rows, skips = collect_claim_check(
        cfg, _doc(f"{LONG}\n\nShort.\n"), k=3, search_fn=search_fn
    )
    assert any(r.status == "supported" for r in rows)
    payload = pack_payload(
        cid="file-draft",
        scope="index",
        k=3,
        inp={"kind": "file", "title": "draft.md"},
        rows=rows,
        skips=skips,
    )
    folder = write_pack(cfg, payload, stamp="20260101T000000Z")
    pack = (folder / "pack.json").read_text(encoding="utf-8")
    import json

    data = json.loads(pack)
    assert CLAIM_CHECK_PACK_KEYS <= set(data)
    md = (folder / "pack.md").read_text(encoding="utf-8")
    assert HONESTY_BANNER in md
    assert str(folder).endswith("ask-claims/20260101T000000Z")


def test_cli_claim_check_conflicts_with_from_file(tmp_path, cfg):
    src = tmp_path / "draft.md"
    src.write_text(LONG + "\n", encoding="utf-8")
    qs = tmp_path / "q.txt"
    qs.write_text("What is EIA?\n", encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n[rag]\nenabled = true\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        app,
        [
            "ask",
            "--claim-check",
            "--file",
            str(src),
            "--from-file",
            str(qs),
            "--config",
            str(cfg_path),
        ],
    )
    assert res.exit_code == 1
    out = (res.stdout or "") + (res.output or "")
    assert "from-file" in out.lower()


def test_cli_file_without_claim_check_exits_1(tmp_path, cfg):
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
        ["ask", "--file", str(src), "--config", str(cfg_path)],
    )
    assert res.exit_code == 1
    out = (res.stdout or "") + (res.output or "")
    assert "claim-check" in out.lower()


def test_cli_claim_check_empty_index(tmp_path, cfg, monkeypatch):
    src = tmp_path / "draft.md"
    src.write_text(LONG + "\n", encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'email = "t@example.org"\nout_dir = "{cfg.out_dir}"\n'
        f'state_dir = "{cfg.state_dir}"\n[rag]\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("paperful.cli_runtime._rag_require", lambda _cfg: None)

    class Empty:
        def count(self) -> int:
            return 0

    monkeypatch.setattr(
        "paperful.cli_runtime._rag_open", lambda _cfg: (Empty(), object())
    )
    monkeypatch.setattr("paperful.cli_runtime._rag_embedder", lambda _cfg: object())
    res = CliRunner().invoke(
        app,
        ["ask", "--claim-check", "--file", str(src), "--config", str(cfg_path)],
    )
    assert res.exit_code == 1
    out = (res.stdout or "") + (res.output or "")
    assert "empty" in out.lower()
