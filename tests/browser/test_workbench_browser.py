"""Browser lane: every page renders without overflow, console errors, or
third-party requests; the key flows work with real JS.

Opt-in: ``uv run pytest -m browser``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

PAGES = [
    "/wanted",
    "/wanted?tab=held",
    "/wanted?tab=have",
    "/discover",
    "/discover?tab=topic",
    "/discover?tab=grow",
    "/discover?tab=people",
    "/discover?tab=queue",
    "/discover?tab=following",
    "/ask",
    "/library",
    "/activity",
    "/system",
    "/repair",
    "/mirror",
    "/index",
    "/briefs",
    "/critique",
    "/rewrite",
    "/stuff",
    "/settings",
]

AUDIT_JS = """
() => {
  const q = (s) => Array.from(document.querySelectorAll(s));
  const unnamed = q('input:not([type=hidden]), select, textarea, button').filter(el => {
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title')) return false;
    if (el.tagName === 'BUTTON' && el.textContent.trim()) return false;
    if (el.id && document.querySelector(`label[for="${el.id}"]`)) return false;
    if (el.closest('label')) return false;
    return true;
  }).map(el => `${el.tagName.toLowerCase()}[name=${el.getAttribute('name')}]`);
  return {
    unnamed,
    hOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    inline: q('[onclick],[onchange],[onsubmit],[oninput]').length,
    longAria: q('[role=img][aria-label]').filter(e => (e.getAttribute('aria-label')||'').length > 120).length,
    emptyTh: q('th').filter(th => !th.textContent.trim()).length,
    tablesNoCaption: q('table').filter(t => !t.querySelector('caption')).length,
    skipLink: !!document.querySelector('a.skip-link[href="#main"]'),
    main: !!document.getElementById('main'),
    h1: q('h1').length,
    dialogs: q('dialog').length,
  };
}
"""


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("path", PAGES)
def test_page_renders_clean(page_factory, workbench, path, width):
    page = page_factory(width)
    resp = page.goto(workbench["base"] + path, wait_until="load")
    assert resp is not None and resp.status == 200, path
    audit = page.evaluate(AUDIT_JS)
    assert page.console_errors == [], (path, page.console_errors)
    assert page.external == [], (path, page.external)
    assert audit["inline"] == 0, path
    assert audit["longAria"] == 0, path
    assert audit["unnamed"] == [], (path, audit["unnamed"])
    assert audit["emptyTh"] == 0, path
    assert audit["tablesNoCaption"] == 0, path
    assert audit["skipLink"] and audit["main"], path
    assert audit["h1"] == 1, path
    assert audit["dialogs"] == 1, (path, "one shared drawer only")
    assert audit["hOverflow"] is False, (path, width)


def test_security_headers_and_hashed_static(page_factory, workbench):
    page = page_factory()
    resp = page.goto(workbench["base"] + "/wanted")
    headers = resp.headers
    assert "script-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    css = page.evaluate(
        "() => document.querySelector('link[href*=\"workbench.css\"]').href"
    )
    assert "?v=" in css
    assert page.evaluate("() => getComputedStyle(document.body).fontFamily").startswith(
        '"Source Sans 3"'
    )


def test_wanted_tick_updates_labels_and_drawer_opens(page_factory, workbench):
    page = page_factory()
    page.goto(workbench["base"] + "/wanted")
    assert page.text_content("#preview-btn").strip() == "Preview all"
    page.check("input.row-select >> nth=0")
    assert page.text_content("#preview-btn").strip() == "Preview selected"
    assert "1 selected" in page.text_content("#wanted-selected-count")
    # Fetch toolbar sits above the table; the table is still on screen.
    box_btn = page.locator("#preview-btn").bounding_box()
    box_tbl = page.locator("table.wanted-table").bounding_box()
    assert box_btn["y"] < box_tbl["y"]
    # Shared drawer: one <dialog>, filled from the row's <template>.
    page.click("button[data-drawer] >> nth=0")
    page.wait_for_selector("#row-drawer[open]")
    assert "Key MISS1" in page.text_content(
        "#row-drawer"
    ) or "Key " in page.text_content("#row-drawer")
    assert page.locator("dialog[open]").count() == 1
    page.click("#row-drawer form[method=dialog] button")
    page.wait_for_function("() => !document.getElementById('row-drawer').open")


def test_apply_buttons_disabled_until_preview(page_factory, workbench):
    page = page_factory()
    page.goto(workbench["base"] + "/discover?tab=queue")
    add = page.locator("form[action='/discover/apply'] button[type=submit]")
    assert add.is_disabled()
    assert "Preview apply first" in (add.get_attribute("title") or "")
    assert "area based management tools" in page.text_content("h2:has-text('Queue')")
    page.goto(workbench["base"] + "/wanted")
    attach_held = page.locator(
        "form[action='/wanted/attach'] button:has-text('Attach held PDFs')"
    )
    assert attach_held.is_disabled()


def test_keep_skip_segmented_control(page_factory, workbench):
    page = page_factory()
    page.goto(workbench["base"] + "/discover?tab=queue")
    first = page.locator("form.keep-toggle >> nth=0")
    assert first.locator("button[aria-pressed=true]").text_content().strip() == "Keep"
    assert "None" not in first.text_content()


def test_activity_marks_orphans_and_stops_polling(page_factory, workbench):
    page = page_factory()
    page.goto(workbench["base"] + "/activity")
    row = page.locator("tr[data-run-id=stale01]")
    assert row.get_attribute("data-run-status") == "failed"
    assert "server restarted" in row.text_content()
    assert page.locator("tr[data-run-id=done0001] a[href*='run=done0001']").count() == 1
    assert "9 s" in page.locator("tr[data-run-id=done0001]").text_content()
    # No EventSource was opened for a terminal row.
    assert (
        page.evaluate(
            "() => performance.getEntriesByType('resource').filter(e => e.name.includes('/events')).length"
        )
        == 0
    )


def test_system_recheck_runs_as_job_and_reloads(page_factory, workbench):
    page = page_factory()
    page.goto(workbench["base"] + "/system")
    assert page.locator("tr.status-row--amber").count() == 1
    page.click("form[action='/system/recheck'] button")
    page.wait_for_url("**/system?run=*")
    page.wait_for_function(
        "() => !document.querySelector('[data-run-id] .cmd-status') || !/queued|running/.test(document.querySelector('[data-run-id] .cmd-status').textContent)",
        timeout=10000,
    )
    page.goto(workbench["base"] + "/activity")
    assert page.locator("tr[data-run-status=done] td:has-text('doctor')").count() >= 1


def test_mobile_nav_wraps_and_forms_stack(page_factory, workbench):
    page = page_factory(390)
    page.goto(workbench["base"] + "/discover?tab=topic")
    nav_overflow = page.evaluate(
        "() => { const n = document.querySelector('nav.wb-nav'); return n.scrollWidth > n.clientWidth + 1; }"
    )
    assert nav_overflow is False
    width = page.evaluate(
        "() => document.querySelector('#discoverQuery').getBoundingClientRect().width"
    )
    assert width > 250


def test_help_tip_is_focusable_and_described(page_factory, workbench):
    page = page_factory()
    page.goto(workbench["base"] + "/wanted")
    tip = page.locator("button.help-tip >> nth=0")
    described = tip.get_attribute("aria-describedby")
    assert described and page.locator(f"#{described}[role=tooltip]").count() == 1
    tip.focus()
    assert page.evaluate("() => document.activeElement.classList.contains('help-tip')")
