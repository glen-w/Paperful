"""Opt-in browser lane: a real Chromium against ``paperful serve`` on a free port.

Run with ``uv run pytest -m browser``. Skipped unless Playwright's Chromium is
installed (``uv run playwright install chromium``). The library is a stub:
no Zotero, no network, so every page renders deterministically.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

BASE_PORT_HINT = 8765


class _Item:
    def __init__(self, key, title, doi, has_pdf, year=2024):
        self.key = key
        self.title = title
        self.doi = doi
        self.has_pdf = has_pdf
        self.year = year
        self.arxiv_id = None
        self.url = ""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_state(cfg) -> None:
    """Enough on-disk state for Discover queue, Activity, and Waiting rows."""
    snow = cfg.state_dir / "snowball" / "20260101T120000Z"
    snow.mkdir(parents=True)
    rows = [
        {
            "ids": {"doi": "10.5/kept"},
            "biblio": {"title": "Kept paper"},
            "keep": True,
            "status": "new",
            "why": "cited by 2 of your seeds",
        },
        {
            "ids": {"doi": "10.5/skipped"},
            "biblio": {"title": "Skipped paper"},
            "keep": False,
            "status": "new",
        },
        {
            "ids": {"doi": "10.5/undecided"},
            "biblio": {"title": "Undecided paper"},
            "status": "new",
        },
    ]
    (snow / "candidates.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    (snow / "summary.json").write_text(
        json.dumps(
            {
                "run_id": snow.name,
                "query": "area based management tools",
                "target_collection": "ocean",
            }
        ),
        encoding="utf-8",
    )
    cmds = cfg.state_dir / "gui" / "commands"
    cmds.mkdir(parents=True)
    old = time.time() - 7200
    (cmds / "stale01.json").write_text(
        json.dumps(
            {"id": "stale01", "verb": "synthesize", "status": "running", "created": old}
        ),
        encoding="utf-8",
    )
    (cmds / "done0001.json").write_text(
        json.dumps(
            {
                "id": "done0001",
                "verb": "preview_run",
                "status": "done",
                "created": old + 60,
                "started": old + 61,
                "finished": old + 70,
                "result": {"would_fetch": 3},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def workbench(tmp_path_factory):
    pytest.importorskip("fastapi")
    pytest.importorskip("playwright")
    uvicorn = pytest.importorskip("uvicorn")

    from paperful.config import Config
    from paperful.store import Manifest, Record, STATUS_OK
    from paperful.ui import jobs
    import paperful.ui.app as ui_app
    from paperful.serve import create_app

    root = tmp_path_factory.mktemp("browser")
    cfg = Config(email="t@example.org", out_dir=root / "out", state_dir=root / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.config_path = root / "config.toml"
    cfg.config_path.write_text('email = "t@example.org"\n', encoding="utf-8")
    _seed_state(cfg)
    manifest = Manifest(cfg.manifest_path)
    items = [
        _Item(
            "MATCH",
            "Matched paper with a long title that should wrap inside the table cell",
            "10.1/a",
            True,
        ),
        _Item("MISM", "Mismatched paper", "10.1/b", True),
        _Item("MISS1", "Missing paper one", "10.1/e", False),
        _Item("MISS2", "Missing paper two", "10.1/f", False),
        _Item("NODOI", "No identifier", None, False),
    ]
    for key, doi, pdf_doi in (
        ("MATCH", "10.1/a", "10.1/a"),
        ("MISM", "10.1/b", "10.9/x"),
    ):
        manifest.write(
            Record(
                itemKey=key,
                status=STATUS_OK,
                doi=doi,
                pdf_doi=pdf_doi,
                source="unpaywall",
                path=f"{key}.pdf",
            )
        )

    # Stub the library: no Zotero, no network.
    ui_app.doctor_payload = lambda _c, probe=False: [  # type: ignore[assignment]
        {"name": "Zotero", "status": "green", "code": "", "detail": "stub"},
        {
            "name": "Camofox",
            "status": "amber",
            "code": "camofox_down",
            "detail": "not running",
        },
    ]
    ui_app.collections_tree = lambda _c: {  # type: ignore[assignment]
        "ok": True,
        "collections": [
            {
                "path": "ocean",
                "name": "ocean",
                "key": "C1",
                "items": 5,
                "missing_pdf": 3,
            },
            {
                "path": "ocean/BBNJ",
                "name": "BBNJ",
                "key": "C2",
                "items": 2,
                "missing_pdf": 1,
            },
        ],
    }
    jobs._load_scope_items = lambda _c, _col: (items, Manifest(cfg.manifest_path))  # type: ignore[assignment]

    app = create_app(cfg)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:  # pragma: no cover
        raise RuntimeError("workbench did not start")
    yield {"base": f"http://127.0.0.1:{port}", "cfg": cfg, "port": port}
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    pw_mod = pytest.importorskip("playwright.sync_api")
    with pw_mod.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except Exception as exc:  # browser binary missing
            pytest.skip(f"Chromium not installed for Playwright: {exc}")
        yield chromium
        chromium.close()


@pytest.fixture
def page_factory(browser, workbench):
    contexts = []

    def make(width: int = 1440, *, advanced: bool = True, collection: str = "ocean"):
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        suffix = "" if workbench["port"] == BASE_PORT_HINT else f"_{workbench['port']}"
        cookies = [
            {
                "name": f"pf_advanced{suffix}",
                "value": "1" if advanced else "0",
                "url": workbench["base"],
            }
        ]
        if collection:
            cookies.append(
                {
                    "name": f"pf_collection{suffix}",
                    "value": collection,
                    "url": workbench["base"],
                }
            )
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.console_errors = []  # type: ignore[attr-defined]
        page.external = []  # type: ignore[attr-defined]
        page.on(
            "console",
            lambda m: page.console_errors.append(m.text) if m.type == "error" else None,
        )  # type: ignore[attr-defined]
        page.on("pageerror", lambda e: page.console_errors.append(str(e)))  # type: ignore[attr-defined]
        page.on(
            "request",
            lambda r: (
                page.external.append(r.url)
                if not r.url.startswith(workbench["base"])
                else None
            ),
        )  # type: ignore[attr-defined]
        contexts.append(ctx)
        return page

    yield make
    for ctx in contexts:
        ctx.close()


ASSETS = Path(__file__).resolve().parents[2] / "paperful" / "ui" / "static"
