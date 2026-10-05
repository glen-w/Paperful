"""Local fetch-win log and learned playbook propose/promote."""

from __future__ import annotations

import pytest

from paperful.config import load_config
from paperful.fetch_wins import (
    load_wins,
    propose_toml,
    record_win,
    write_learned,
)
from paperful.playbooks import GreyPlaybook, apply_rewrite, load_pack_file, merge_playbooks


def test_rewrite_recipe_from_two_wins(cfg, tmp_path):
    packs = tmp_path / "packs"
    cfg.grey_playbooks_dir = packs
    cfg.playbooks_promote = "auto"
    cfg.playbooks_auto_min_hits = 2
    start = "https://onlinelibrary.wiley.com/doi/abs/10.1002/foo?token=secret"
    final = "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/foo?download=1"
    record_win(
        cfg,
        item_key="A",
        source="unpaywall",
        start_url=start,
        final_url=final,
        win="rewrite",
    )
    assert not (packs / "learned.toml").exists()
    record_win(
        cfg,
        item_key="B",
        source="ezproxy",
        start_url="https://onlinelibrary.wiley.com/doi/abs/10.1002/bar",
        final_url="https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/bar",
        win="rewrite",
    )
    learned = packs / "learned.toml"
    assert learned.is_file()
    text = learned.read_text(encoding="utf-8")
    assert "learned-onlinelibrary-wiley-com-rewrite" in text
    assert "token=secret" not in (cfg.state_dir / "fetch-wins.jsonl").read_text(
        encoding="utf-8"
    )
    before = learned.stat().st_mtime_ns
    record_win(
        cfg,
        item_key="C",
        source="ezproxy",
        start_url="https://onlinelibrary.wiley.com/doi/abs/10.1002/baz",
        final_url="https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/baz",
        win="rewrite",
    )
    assert learned.stat().st_mtime_ns == before
    books = load_pack_file(learned)
    assert books[0].kind == "rewrite"
    hit = apply_rewrite(
        "https://onlinelibrary.wiley.com/doi/abs/10.1002/zzz", books
    )
    assert hit is not None and "pdfdirect" in hit


def test_auto_skips_without_playbook_dir(cfg, capsys):
    cfg.grey_playbooks_dir = None
    cfg.playbooks_promote = "auto"
    record_win(
        cfg,
        item_key="A",
        source="ezproxy",
        start_url="https://www.nature.com/articles/s1",
        final_url="https://www.nature.com/articles/s1.pdf",
        win="meta",
    )
    err = capsys.readouterr().out
    assert "grey_playbooks_dir" in err
    record_win(
        cfg,
        item_key="B",
        source="ezproxy",
        start_url="https://www.nature.com/articles/s2",
        final_url="https://www.nature.com/articles/s2.pdf",
        win="meta",
    )
    assert capsys.readouterr().out == ""


def test_corrupt_win_line_is_skipped(cfg):
    path = cfg.state_dir / "fetch-wins.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"win": "meta"}\nnot-json\n', encoding="utf-8")
    rows = load_wins(path)
    assert len(rows) == 1


def test_agent_click_win_proposes_after_min_hits(cfg, tmp_path):
    packs = tmp_path / "packs"
    cfg.grey_playbooks_dir = packs
    for key in ("A", "B"):
        record_win(
            cfg,
            item_key=key,
            source="browser_agent",
            start_url="https://pub.example.com/article/1",
            final_url="https://pub.example.com/article/1.pdf",
            win="click:Download PDF",
            steps=[{"action": "click", "detail": "Download PDF"}],
        )
    text = propose_toml(load_wins(cfg.state_dir / "fetch-wins.jsonl"), min_hits=2)
    assert "learned-pub-example-com-click" in text
    assert "href_re" in text


def test_propose_then_promote(cfg, tmp_path):
    packs = tmp_path / "packs"
    cfg.grey_playbooks_dir = packs
    cfg.playbooks_promote = "gated"
    record_win(
        cfg,
        item_key="A",
        source="unpaywall",
        start_url="https://www.nature.com/articles/s1",
        final_url="https://www.nature.com/articles/s1.pdf",
        win="meta",
    )
    text = propose_toml(
        [{"host": "nature.com", "start_url": "https://www.nature.com/articles/s1",
          "final_url": "https://www.nature.com/articles/s1.pdf", "win": "meta"}],
        min_hits=1,
    )
    proposed = cfg.state_dir / "playbooks-proposed.toml"
    proposed.write_text(text, encoding="utf-8")
    books = load_pack_file(proposed)
    assert books and books[0].name.startswith("learned-")
    assert write_learned(packs, books) is True
    assert write_learned(packs, books) is False
    assert (packs / "learned.toml").is_file()


def test_body_win_is_not_promoted(cfg, tmp_path):
    cfg.grey_playbooks_dir = tmp_path / "packs"
    cfg.playbooks_promote = "auto"
    cfg.playbooks_auto_min_hits = 1
    record_win(
        cfg,
        item_key="A",
        source="ezproxy",
        start_url="https://x.test/a.pdf",
        final_url="https://x.test/a.pdf",
        win="body",
    )
    assert not (tmp_path / "packs" / "learned.toml").exists()


def test_playbooks_promote_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'email = "a@b.c"\nstate_dir = "state"\nout_dir = "out"\n'
        '[playbooks]\npromote = "auto"\nauto_min_hits = 3\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.playbooks_promote == "auto"
    assert cfg.playbooks_auto_min_hits == 3
    bare = tmp_path / "bare.toml"
    bare.write_text('email = "a@b.c"\n', encoding="utf-8")
    assert load_config(bare).playbooks_promote == "gated"
    bad = tmp_path / "bad.toml"
    bad.write_text('email = "a@b.c"\n[playbooks]\npromote = "always"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(bad)


def test_learned_name_does_not_clobber_hand_pack(tmp_path):
    hand = GreyPlaybook(
        name="fao",
        kind="rewrite",
        hosts=("fao.org",),
        url_re="fao",
        pdf_template="https://example.test/{0}",
    )
    learned = GreyPlaybook(
        name="learned-example-test-meta",
        kind="scrape",
        hosts=("example.test",),
        href_re=r"(?i)\.pdf(?:\?|$)",
    )
    merged = merge_playbooks(False, [hand], extra=[learned])
    names = [pb.name for pb in merged]
    assert names == ["learned-example-test-meta", "fao"] or set(names) == {
        "learned-example-test-meta",
        "fao",
    }
    assert "fao.org" in {h for pb in merged if pb.name == "fao" for h in pb.hosts}


def test_playbooks_propose_cli_writes_under_state(tmp_path):
    from typer.testing import CliRunner

    from paperful import cli

    root = tmp_path / "proj"
    state = root / "state"
    state.mkdir(parents=True)
    (root / "config.toml").write_text(
        'email = "a@b.c"\n'
        f'state_dir = "{state}"\n'
        f'out_dir = "{root / "out"}"\n'
        f'grey_playbooks_dir = "{root / "packs"}"\n',
        encoding="utf-8",
    )
    (state / "fetch-wins.jsonl").write_text(
        '{"win":"meta","host":"nature.com",'
        '"start_url":"https://www.nature.com/articles/s1",'
        '"final_url":"https://www.nature.com/articles/s1.pdf"}\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        cli.app, ["playbooks", "propose", "--config", str(root / "config.toml")]
    )
    assert res.exit_code == 0, res.output
    proposed = state / "playbooks-proposed.toml"
    assert proposed.is_file()
    assert "learned-" in proposed.read_text(encoding="utf-8")
    assert not (root / "packs" / "learned.toml").exists()
