#!/usr/bin/env python3
"""Capture workbench screenshots for the public site and walkthrough docs.

Requires a running workbench (``docker compose up`` or ``paperful serve``)
and Playwright Chromium. Usage from the repo root:

    uv run python scripts/docs/capture_workbench.py
    PAPERFUL_UI=http://127.0.0.1:8765 uv run python scripts/docs/capture_workbench.py

Does not enable Advanced sources. Do not capture Settings (email) or Sci-Hub.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DOCS_OUT = ROOT / "docs" / "_static" / "workflows"
WEB_OUT = ROOT / "website" / "images"
BASE = os.environ.get("PAPERFUL_UI", "http://127.0.0.1:8765").rstrip("/")
COLLECTION = os.environ.get("PAPERFUL_SHOT_COLLECTION", "ocean/BBNJ")
VIEWPORT = {"width": 1440, "height": 900}

# Docs filename → website copy (homepage gallery).
HOMEPAGE = {
    "wanted.png": "workbench-wanted.png",
    "discover.png": "workbench-discover.png",
    "repair.png": "workbench-repair.png",
    "index.png": "workbench-index.png",
}


def _ready(page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)
    page.evaluate("() => document.fonts.ready")
    page.wait_for_timeout(200)


def _shot(page, name: str) -> None:
    dest = DOCS_OUT / name
    page.screenshot(path=str(dest), full_page=False)
    print(f"wrote {dest.relative_to(ROOT)}")


def main() -> None:
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    WEB_OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=1,
            color_scheme="light",
        )
        context.add_cookies(
            [
                {
                    "name": "pf_collection",
                    "value": COLLECTION,
                    "url": BASE,
                },
                {
                    "name": "pf_preset",
                    "value": "oa",
                    "url": BASE,
                },
            ]
        )
        page = context.new_page()

        page.goto(f"{BASE}/wanted", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "wanted.png")

        page.goto(f"{BASE}/wanted?tab=held", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "wanted-held.png")

        page.goto(f"{BASE}/discover", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "discover.png")
        people = page.locator("h2", has_text="People")
        if people.count():
            people.first.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            _shot(page, "discover-people.png")

        page.goto(f"{BASE}/library", wait_until="domcontentloaded")
        _ready(page)
        ocean = page.locator(".coll-name", has_text="ocean")
        if ocean.count():
            details = ocean.first.locator("xpath=ancestor::details")
            if details.count():
                details.first.evaluate("el => { el.open = true; }")
            ocean.first.scroll_into_view_if_needed()
            page.wait_for_timeout(250)
        _shot(page, "library.png")

        page.goto(f"{BASE}/activity", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "activity.png")

        page.goto(f"{BASE}/system", wait_until="domcontentloaded")
        _ready(page)
        page.evaluate(
            """() => {
              const re = /[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}/g;
              document.querySelectorAll('td, .next-step, .counts').forEach((el) => {
                if (re.test(el.textContent || '')) {
                  el.textContent = (el.textContent || '').replace(re, 'you@example.org');
                }
              });
            }"""
        )
        _shot(page, "system.png")

        page.locator("form.advanced-toggle input[name='advanced']").check()
        page.wait_for_load_state("networkidle")
        _ready(page)

        page.goto(f"{BASE}/repair", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "repair.png")

        page.goto(f"{BASE}/mirror", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "mirror.png")

        page.goto(f"{BASE}/index", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "index.png")

        page.goto(f"{BASE}/briefs", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "briefs.png")

        browser.close()

    for src_name, dest_name in HOMEPAGE.items():
        src = DOCS_OUT / src_name
        dest = WEB_OUT / dest_name
        shutil.copy2(src, dest)
        print(f"copied {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
