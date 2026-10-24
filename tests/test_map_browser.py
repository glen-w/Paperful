"""Browser checks for the map views (papers / authors). Skipped without Playwright + Chromium.

Set PAPERFUL_CHROMIUM to a Chromium binary when Playwright's own download is
not installed.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from paperful.config import load_config  # noqa: E402
from paperful.snowball.candidate import Candidate  # noqa: E402
from paperful.snowball.openalex import OpenAlexClient  # noqa: E402
from paperful.snowball.queue import write_queue  # noqa: E402

pytestmark = pytest.mark.browser


def _chromium() -> str | None:
    for candidate in (os.environ.get("PAPERFUL_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _launch(p):
    exe = _chromium()
    try:
        return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Chromium not available: {exc}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _row(doi, *, hop=1, authors=(), parent="", direction="cites", year=2020, cited=5):
    records = [{"openalex": oa, "orcid": "", "display_name": name, "fingerprint": ""} for name, oa in authors]
    biblio = {
        "title": f"Paper {doi}",
        "year": year,
        "cited_by_count": cited,
        "authors": [n for n, _ in authors],
        "author_records": records,
    }
    if parent:
        biblio["graph_links"] = [{"parent": parent, "direction": direction}]
    return Candidate(
        run_id="R1", seed={"type": "doi", "value": "s"}, hop=hop,
        direction=direction if hop else "doi", ids={"doi": doi, "openalex": ""},
        biblio=biblio, why="t", status="new", provenance={"backend": "openalex"}, gate="dry-run",
    )


@pytest.fixture
def server(tmp_path, monkeypatch):
    import paperful.agent_ops as ops
    from paperful.serve import create_app

    path = tmp_path / "config.toml"
    path.write_text(
        f'email = "t@example.com"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
        '[map]\ncolor = "role"\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    people = [("Ana Ruiz", "A0"), ("Ben Okafor", "A1"), ("Chen Wei", "A2"), ("Dara Kelly", "A3"), ("Eli Novak", "A4")]
    seed = _row("10.1/seed", hop=0, authors=people[:2], year=2014, cited=900)
    rows = [seed]
    for i in range(12):
        rows.append(
            _row(f"10.1/p{i}", authors=[people[i % 5], people[(i + 1) % 5]], parent=seed.identity,
                 direction="cites" if i % 2 else "refs", year=2010 + i, cited=100 + i)
        )
    write_queue(cfg.state_dir, "R1", rows, OpenAlexClient(email="t@example.com"), library_unread=False)
    monkeypatch.setattr(ops, "doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(ops, "collections_tree", lambda _c: {"ok": True, "collections": []})
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", cfg
    srv.should_exit = True
    thread.join(timeout=5)


def _ids(pg):
    return pg.evaluate("[...document.querySelectorAll('#citationCanvas .nodes > g')].map(g => g.__data__.id)")


def _click(pg, node_id):
    pg.evaluate(
        """(id) => [...document.querySelectorAll('#citationCanvas .nodes > g')]
            .find(g => g.__data__.id === id).dispatchEvent(new MouseEvent('click', {bubbles: true}))""",
        node_id,
    )


def test_author_view_end_to_end(server):
    base, cfg = server
    with playwright.sync_playwright() as p:
        browser = _launch(p)
        pg = browser.new_page(viewport={"width": 1300, "height": 1000})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{base}/discover?tab=queue")
        pg.wait_for_function("document.querySelectorAll('#citationCanvas .nodes > g').length >= 5", timeout=15000)

        # Papers view first; then the same map as people.
        assert all(not i.startswith("author:") for i in _ids(pg))
        pg.click("[data-map-view=authors]")
        pg.wait_for_function(
            "[...document.querySelectorAll('#citationCanvas .nodes > g')].every(g => g.__data__.kind === 'author')"
        )
        assert len(_ids(pg)) == 5
        assert pg.locator("#citationAuthorLegend").is_visible()

        # Author panel: their papers, co-authors, follow.
        _click(pg, "author:openalex:A0")
        pg.wait_for_selector("#citationPanel [data-paper-id]")
        assert "Ana Ruiz" in pg.locator("#citationPanel h3").inner_text()
        assert pg.locator("#citationPanel [data-paper-id]").count() == 6  # seed + 5 papers
        assert "Co-authors here" in pg.locator("#citationPanel").inner_text()
        pg.click("#citationPanel [data-author-follow]")
        pg.wait_for_function("document.querySelector('#citationPanel').innerText.includes('Following')")
        stored = " ".join(f.read_text() for f in (cfg.state_dir / "authorwatch").rglob("*") if f.is_file())
        assert "A0" in stored

        # Find in the author view, then keyboard into a node.
        pg.fill("#citationSearch", "Novak")
        pg.wait_for_function("!document.getElementById('citationHighlight').hidden")
        pg.press("#citationSearch", "Enter")
        pg.wait_for_function("document.querySelector('#citationPanel h3').innerText.includes('Eli Novak')")

        # A paper in the author panel goes back to the papers view and selects it.
        pg.locator("#citationPanel [data-paper-id]").first.click()
        pg.wait_for_function("document.querySelector('[data-map-view=papers]').getAttribute('aria-pressed') === 'true'")
        pg.wait_for_function(
            "[...document.querySelectorAll('#citationCanvas .nodes > g')].every(g => g.__data__.kind !== 'author')"
        )
        assert "Eli Novak" in pg.locator("#citationHighlight").inner_text()

        # Keyboard: focus a node and press Enter.
        pg.evaluate("document.querySelector('#citationCanvas .nodes > g').focus()")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#citationPanel h3")

        # Export the author list.
        pg.click("[data-map-view=authors]")
        with pg.expect_download() as dl:
            pg.select_option("#citationExport", "csv")
        text = Path(dl.value.path()).read_text()
        assert text.splitlines()[0].startswith('"name","count"') and "Ana Ruiz" in text
        browser.close()
    assert not errors, errors
