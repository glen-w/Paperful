#!/usr/bin/env python3
"""Capture workbench screenshots for the public site and walkthrough docs.

Requires a running workbench (``docker compose up`` or ``paperful serve``)
and Playwright Chromium. Usage from the repo root:

    uv run python scripts/docs/capture_workbench.py
    PAPERFUL_UI=http://127.0.0.1:8765 uv run python scripts/docs/capture_workbench.py

Fills demo values and ticks rows so shots look in-use. Does not submit
Grab / Attach / Apply / Search (no catalogue writes). ``index-ask.png``
opens an existing answered thread under ``state/rag/threads/``. Does not
enable Advanced sources. Do not capture Settings (email) or Sci-Hub.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DOCS_OUT = ROOT / "docs" / "_static" / "workflows"
WEB_OUT = ROOT / "website" / "images"
THREADS = ROOT / "state" / "rag" / "threads"
BASE = os.environ.get("PAPERFUL_UI", "http://127.0.0.1:8765").rstrip("/")
COLLECTION = os.environ.get("PAPERFUL_SHOT_COLLECTION", "ocean/BBNJ")
TOPIC_QUERY = os.environ.get("PAPERFUL_SHOT_TOPIC", "area based management")
SEARCH_Q = os.environ.get("PAPERFUL_SHOT_SEARCH", "clearing-house mechanism")
ASK_QUESTION = os.environ.get(
    "PAPERFUL_SHOT_ASK",
    "What is the BBNJ clearing-house mechanism?",
)
PEOPLE_LIST = os.environ.get("PAPERFUL_SHOT_LIST", "bbnj-test-voices")
FOLLOW_ORCID = os.environ.get("PAPERFUL_SHOT_ORCID", "0000-0001-9025-7632")
VIEWPORT = {"width": 1440, "height": 900}

# Docs filename → website copy (homepage gallery).
HOMEPAGE = {
    "wanted.png": "workbench-wanted.png",
    "discover.png": "workbench-discover.png",
    "repair.png": "workbench-repair.png",
    "index-ask.png": "workbench-index.png",
}


def _cookies(*, advanced: bool) -> list[dict[str, str]]:
    out = [
        {"name": "pf_collection", "value": COLLECTION, "url": BASE},
        {"name": "pf_preset", "value": "oa", "url": BASE},
    ]
    if advanced:
        out.append({"name": "pf_advanced", "value": "1", "url": BASE})
    return out


def _ready(page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)
    page.evaluate("() => document.fonts.ready")
    page.wait_for_timeout(200)


def _blur(page) -> None:
    page.evaluate(
        """() => {
          const el = document.activeElement;
          if (el && el !== document.body && typeof el.blur === 'function') el.blur();
        }"""
    )


def _shot(page, name: str) -> None:
    _blur(page)
    dest = DOCS_OUT / name
    page.screenshot(path=str(dest), full_page=False)
    print(f"wrote {dest.relative_to(ROOT)}")


def _fill(page, selector: str, value: str) -> None:
    loc = page.locator(selector)
    if loc.count():
        loc.first.fill(value)


def _select(page, selector: str, value: str) -> None:
    loc = page.locator(selector)
    if loc.count():
        loc.first.select_option(value)


def _tick_first(page, n: int) -> None:
    boxes = page.locator("input.row-select")
    total = min(n, boxes.count())
    for i in range(total):
        boxes.nth(i).check()
    if total:
        page.wait_for_timeout(150)


def _scroll_h2(page, title: str) -> None:
    loc = page.locator("h2", has_text=title)
    if loc.count():
        loc.first.scroll_into_view_if_needed()
        page.wait_for_timeout(200)


def _best_ask_thread(collection: str, question: str) -> str | None:
    """Pick an on-disk Ask thread that already has a cited answer."""
    if not THREADS.is_dir():
        return None
    tokens = {part.lower() for part in collection.replace("/", " ").split() if part}
    want = (question or "").strip().lower()
    ranked: list[tuple[int, int, int, float, str]] = []
    for path in THREADS.glob("*.json"):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        turns = body.get("turns") if isinstance(body, dict) else None
        if not isinstance(turns, list):
            continue
        answers = [
            str(t.get("content") or "")
            for t in turns
            if isinstance(t, dict) and t.get("role") == "assistant"
        ]
        answers = [a for a in answers if len(a) > 80 and "Nothing in the index" not in a]
        if not answers:
            continue
        questions = [
            str(t.get("content") or "").strip()
            for t in turns
            if isinstance(t, dict) and t.get("role") == "user"
        ]
        blob = " ".join(questions).lower()
        exact = 1 if want and any(q.lower() == want for q in questions) else 0
        topical = 1 if tokens and any(tok in blob for tok in tokens) else 0
        ranked.append(
            (exact, topical, sum(len(a) for a in answers), path.stat().st_mtime, path.stem)
        )
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][4]


def _prepare_ask_shot(page) -> None:
    """Keep Index chrome; drop sibling Index panels so the thread fits."""
    page.evaluate(
        """() => {
          const ask = [...document.querySelectorAll('section.panel')].find((el) => {
            const h = el.querySelector(':scope > h2');
            return h && (h.textContent || '').trim() === 'Ask';
          });
          if (!ask) return;
          document.querySelectorAll('section.panel').forEach((el) => {
            if (el !== ask) el.style.display = 'none';
          });
          window.scrollTo(0, 0);
        }"""
    )
    page.wait_for_timeout(200)


def _fill_discover(page) -> None:
    _fill(page, "form[action='/discover/topic'] input[name='query']", TOPIC_QUERY)
    _fill(page, "form[action='/discover/aw/save'] input[name='name']", PEOPLE_LIST)
    _fill(page, "form[action='/discover/follow'] input[name='orcid']", FOLLOW_ORCID)
    _fill(page, "form[action='/discover/follow'] input[name='list_name']", PEOPLE_LIST)
    _fill(page, "form[action='/discover/follow'] input[name='backfill_from']", "2024-01-01")


def _redact_emails(page) -> None:
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
        context.add_cookies(_cookies(advanced=False))
        page = context.new_page()

        page.goto(f"{BASE}/wanted", wait_until="domcontentloaded")
        _ready(page)
        _tick_first(page, 3)
        _shot(page, "wanted.png")

        page.goto(f"{BASE}/wanted?tab=held", wait_until="domcontentloaded")
        _ready(page)
        _tick_first(page, 2)
        _shot(page, "wanted-held.png")

        page.goto(f"{BASE}/discover", wait_until="domcontentloaded")
        _ready(page)
        _fill_discover(page)
        _shot(page, "discover.png")

        page.goto(
            f"{BASE}/discover?list_name={PEOPLE_LIST}",
            wait_until="domcontentloaded",
        )
        _ready(page)
        _fill_discover(page)
        for heading in ("Suggestions", "Members", "People"):
            loc = page.locator("h2", has_text=heading)
            if loc.count():
                loc.first.scroll_into_view_if_needed()
                page.wait_for_timeout(200)
                break
        _shot(page, "discover-people.png")

        page.goto(f"{BASE}/library", wait_until="domcontentloaded")
        _ready(page)
        page.evaluate(
            """() => {
              document.querySelectorAll('.coll-tree > .coll-node').forEach((el) => {
                const name = el.querySelector(':scope > summary .coll-name');
                el.open = !!(name && /ocean/i.test(name.textContent || ''));
              });
              document.querySelectorAll('.coll-name').forEach((el) => {
                if (/^bbnj$/i.test((el.textContent || '').trim())) {
                  const details = el.closest('details');
                  if (details) details.open = true;
                }
              });
            }"""
        )
        page.locator("h1", has_text="Library").first.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        _shot(page, "library.png")

        page.goto(f"{BASE}/activity", wait_until="domcontentloaded")
        _ready(page)
        _shot(page, "activity.png")

        page.goto(f"{BASE}/system", wait_until="domcontentloaded")
        _ready(page)
        _redact_emails(page)
        _shot(page, "system.png")

        context.add_cookies(_cookies(advanced=True))

        page.goto(f"{BASE}/repair", wait_until="domcontentloaded")
        _ready(page)
        _select(page, "select[name='phase']", "high_doi")
        page.evaluate(
            """() => {
              document.querySelectorAll('main details').forEach((el) => {
                const summary = el.querySelector('summary');
                const match = /Queued files \\((\\d+)\\)/.exec(
                  summary ? summary.textContent || '' : ''
                );
                if (match && Number(match[1]) <= 8) el.open = true;
              });
            }"""
        )
        page.wait_for_timeout(150)
        _shot(page, "repair.png")

        page.goto(f"{BASE}/mirror", wait_until="domcontentloaded")
        _ready(page)
        for handle in page.locator("select[name='pdfs']").all():
            handle.select_option("all")
        _shot(page, "mirror.png")

        query = urlencode(
            {
                "q": SEARCH_Q,
                "k": "6",
                "year_from": "2018",
                "year_to": "2026",
            }
        )
        page.goto(f"{BASE}/index?{query}", wait_until="domcontentloaded", timeout=60_000)
        _ready(page)
        _fill(page, "form[action='/index/ingest'] input[name='year_from']", "2018")
        _fill(page, "form[action='/index/ingest'] input[name='year_to']", "2026")
        _fill(page, "form[action='/index/ingest'] input[name='limit']", "40")
        _fill(page, "form[action='/index/ask'] textarea[name='question']", ASK_QUESTION)
        _fill(
            page,
            "form[action='/index/ask-batch'] textarea[name='questions']",
            "What is the BBNJ clearing-house mechanism?\n"
            "How does the treaty treat marine genetic resources?",
        )
        _shot(page, "index.png")

        thread_id = _best_ask_thread(COLLECTION, ASK_QUESTION)
        if thread_id:
            page.goto(
                f"{BASE}/index?thread={thread_id}",
                wait_until="domcontentloaded",
            )
            _ready(page)
            _prepare_ask_shot(page)
            _shot(page, "index-ask.png")
        else:
            print("skip index-ask.png (no answered thread under state/rag/threads/)")

        page.goto(f"{BASE}/briefs", wait_until="domcontentloaded")
        _ready(page)
        _fill(page, "form[action='/briefs/summarize'] input[name='limit']", "25")
        _fill(page, "form[action='/briefs/summarize'] input[name='year_from']", "2020")
        _fill(page, "form[action='/briefs/summarize'] input[name='year_to']", "2026")
        _fill(page, "form[action='/briefs/synthesize'] input[name='limit']", "40")
        _fill(page, "form[action='/briefs/synthesize'] input[name='year_from']", "2020")
        _fill(page, "form[action='/briefs/synthesize'] input[name='year_to']", "2026")
        page.evaluate(
            """() => {
              document.querySelectorAll('main details').forEach((el) => {
                el.open = true;
              });
            }"""
        )
        page.wait_for_timeout(150)
        _shot(page, "briefs.png")

        browser.close()

    for src_name, dest_name in HOMEPAGE.items():
        src = DOCS_OUT / src_name
        if not src.is_file():
            print(f"skip copy {src_name} (missing)")
            continue
        dest = WEB_OUT / dest_name
        shutil.copy2(src, dest)
        print(f"copied {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
