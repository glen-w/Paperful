"""Offline grey-playbook probe, plus replay of any saved live snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from paperful.cli import app
from paperful.grey_probe import (
    ProbeTarget,
    anchors_to_html,
    load_corpus,
    playbooks_for_probe,
    probe_one,
)
from paperful.playbooks import default_playbooks, load_builtin_pack
from paperful.sources.landing import extract_pdf_urls

_RECORDED = Path(__file__).resolve().parent / "fixtures" / "grey" / "recorded"
_CORPUS = Path(__file__).resolve().parent / "fixtures" / "grey" / "corpus.toml"
_PDF = b"%PDF-1.4\n" + b"0" * 12_000


def _books():
    load_builtin_pack.cache_clear()
    return playbooks_for_probe(default_playbooks(), examples=True)


def _client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        timeout=5.0,
    )


def test_pdf_link_outranks_section_and_other_host():
    books = _books()
    html = """
    <html><body>
      <a href="/meetings/2024/comm">Meetings</a>
      <a href="/depts/los/overview">Overview</a>
      <a href="https://cdn.example.org/reports/cmm-02.pdf">CMM</a>
    </body></html>
    """
    sprfmo = extract_pdf_urls(
        html, "https://www.sprfmo.int/fisheries/conservation-and-management-measures", books
    )
    assert sprfmo[0] == "https://cdn.example.org/reports/cmm-02.pdf"
    assert any(u.endswith("/meetings/2024/comm") for u in sprfmo)

    bbnj = extract_pdf_urls(html, "https://www.un.org/bbnjagreement/", books)
    assert bbnj[0] == "https://cdn.example.org/reports/cmm-02.pdf"
    assert any(u.endswith("/depts/los/overview") for u in bbnj)


def test_section_path_kept_when_it_is_the_only_link():
    books = _books()
    html = '<html><body><a href="/files/renewables-2024">Annex</a></body></html>'
    urls = extract_pdf_urls(html, "https://www.iea.org/reports/renewables", books)
    assert urls == ["https://www.iea.org/files/renewables-2024"]


def test_probe_rewrite_requires_pdf_bytes():
    books = _books()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith(".pdf"):
            return httpx.Response(200, content=_PDF)
        return httpx.Response(200, text="<html>landing</html>")

    with _client(handler) as client:
        row = probe_one(
            ProbeTarget(
                playbook="fao",
                url="https://www.fao.org/3/cc0461en/cc0461en.htm",
            ),
            books,
            client,
            min_bytes=10_000,
        )
    assert row.status == "pass"
    assert row.stamp == "fao"
    assert row.chosen.endswith("/cc0461en.pdf")
    assert row.nbytes >= 10_000


def test_probe_scrape_pass_and_alternate_and_miss():
    books = _books()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/good.pdf"):
            return httpx.Response(200, content=_PDF)
        if path.endswith("/fake.pdf"):
            return httpx.Response(200, text="<html>not a pdf</html>")
        if path.endswith("/empty"):
            return httpx.Response(
                200,
                text="<html><body><a href='/about'>About</a></body></html>",
            )
        if path.endswith("/mixed"):
            return httpx.Response(
                200,
                text=(
                    "<html><body>"
                    "<a href='/fake.pdf'>Fake</a>"
                    "<a href='/good.pdf'>Real</a>"
                    "</body></html>"
                ),
            )
        return httpx.Response(404)

    with _client(handler) as client:
        mixed = probe_one(
            ProbeTarget(playbook="iea_scrape", url="https://www.iea.org/reports/mixed"),
            books,
            client,
            check=3,
            min_bytes=10_000,
        )
        empty = probe_one(
            ProbeTarget(playbook="iea_scrape", url="https://www.iea.org/reports/empty"),
            books,
            client,
            min_bytes=10_000,
        )
    assert mixed.status == "alternate"
    assert mixed.chosen.endswith("/good.pdf")
    assert empty.status == "miss"
    assert empty.stamp == "iea_scrape"


def test_probe_wrong_playbook_and_corpus_file():
    books = _books()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_PDF)

    with _client(handler) as client:
        row = probe_one(
            ProbeTarget(playbook="rfmo-docs", url="https://example.org/file.pdf"),
            books,
            client,
            min_bytes=10_000,
        )
    assert row.status == "wrong-playbook"
    targets = load_corpus(_CORPUS)
    names = {t.playbook for t in targets}
    assert "fao" in names
    assert "who_scrape" in names
    assert "undocs-unga-vme-symbol" in names


def test_snapshot_replay_prefers_pdf():
    books = _books()
    html = anchors_to_html(
        [
            {"href": "/meetings/2024/comm", "text": "Meetings"},
            {"href": "/assets/cmm.pdf", "text": "CMM"},
        ]
    )
    urls = extract_pdf_urls(
        html, "https://www.sprfmo.int/fisheries/cmm", books
    )
    assert urls[0] == "https://www.sprfmo.int/assets/cmm.pdf"


def test_recorded_passes_replay():
    """Live passes keep selecting the same first URL from the stored links."""
    files = sorted(_RECORDED.glob("*.json"))
    files = [p for p in files if p.name != "index.json"]
    if not files:
        pytest.skip("no recorded grey probe yet")
    books = _books()
    checked = 0
    for path in files:
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") != "pass":
            continue
        anchors = row.get("anchors") or []
        if anchors:
            urls = extract_pdf_urls(
                anchors_to_html(anchors, row.get("metas") or []),
                row.get("resolved") or row["url"],
                books,
            )
            assert urls, path.name
            assert urls[0] == row["chosen"], path.name
            checked += 1
        else:
            from types import SimpleNamespace

            from paperful.sources.landing import grey_target

            item = SimpleNamespace(
                url=row.get("url") or "",
                extra=row.get("extra") or "",
                title="",
                doi=None,
            )
            assert grey_target(item, books) == row["resolved"], path.name
            checked += 1
    if checked == 0:
        pytest.skip("recorded probe has no pass rows to replay")


def test_probe_cli_rejects_empty_corpus(tmp_path):
    corpus = tmp_path / "empty.toml"
    corpus.write_text("# no targets\n", encoding="utf-8")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'out_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        app,
        ["playbooks", "probe", "--corpus", str(corpus), "--config", str(cfg)],
    )
    assert res.exit_code == 2


@pytest.mark.grey_live
def test_grey_live_corpus_has_a_pass_per_playbook():
    if os.environ.get("PAPERFUL_GREY_LIVE") != "1":
        pytest.skip("set PAPERFUL_GREY_LIVE=1 to fetch the public corpus")
    import httpx

    from paperful.grey_probe import probe_corpus

    books = _books()
    targets = load_corpus(_CORPUS)
    timeout = httpx.Timeout(20.0, connect=15.0)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        rows = probe_corpus(targets, books, client, check=3, min_bytes=10_000, delay_s=0.4)
    by_name: dict[str, list] = {}
    for row in rows:
        by_name.setdefault(row.playbook, []).append(row)
    missing = [
        name
        for name, group in sorted(by_name.items())
        if not any(row.status == "pass" for row in group)
    ]
    assert missing == [], [(row.playbook, row.status, row.detail, row.url) for row in rows]
