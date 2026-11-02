#!/usr/bin/env python3
"""Record short workflow GIFs of the workbench for the docs.

Companion to ``capture_workbench.py``. Requires a running workbench
(``docker compose up`` or ``paperful serve``), Playwright Chromium, and
``ffmpeg`` on PATH. Usage from the repo root:

    uv run python scripts/docs/record_workflows.py
    PAPERFUL_UI=http://127.0.0.1:8765 uv run python scripts/docs/record_workflows.py

Each GIF is assembled from a handful of still frames (stop-motion) with a
drawn cursor, so the files stay small and deterministic. Flows are read-only
except **Preview** on Wanted (a dry-run that writes a review token under
``state/gui/reviews/``) and the Library **Set scope** click (a cookie).
Nothing here submits Grab / Attach / Apply / Add selected.

Outputs land in ``docs/_static/workflows/*.gif``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "_static" / "workflows"
BASE = os.environ.get("PAPERFUL_UI", "http://127.0.0.1:8765").rstrip("/")
COLLECTION = os.environ.get("PAPERFUL_SHOT_COLLECTION", "ocean/BBNJ")
VIEWPORT = {"width": 1280, "height": 800}
GIF_WIDTH = 960
FPS = 12

CURSOR_JS = """
(() => {
  if (window.__pfCursor) return;
  const c = document.createElement('div');
  c.id = 'pf-cursor';
  c.style.cssText = [
    'position:fixed', 'left:0', 'top:0', 'width:18px', 'height:26px',
    'pointer-events:none', 'z-index:2147483647', 'transform:translate(-2px,-2px)',
    'opacity:0', 'transition:opacity .12s',
  ].join(';');
  c.innerHTML = '<svg width="18" height="26" viewBox="0 0 18 26">'
    + '<path d="M1 1 L1 20 L6 15 L9 24 L12 23 L9 14 L16 14 Z" '
    + 'fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const ring = document.createElement('div');
  ring.id = 'pf-cursor-ring';
  ring.style.cssText = [
    'position:fixed', 'left:0', 'top:0', 'width:36px', 'height:36px',
    'margin:-18px 0 0 -18px', 'border-radius:50%', 'pointer-events:none',
    'z-index:2147483646', 'border:3px solid #c2410c', 'opacity:0',
    'transform:scale(.4)', 'transition:opacity .25s, transform .25s',
  ].join(';');
  const attach = () => {
    if (!document.body) return;
    document.body.appendChild(c);
    document.body.appendChild(ring);
  };
  if (document.body) attach(); else document.addEventListener('DOMContentLoaded', attach);
  window.__pfCursor = {
    move(x, y) {
      c.style.opacity = '1';
      c.style.left = x + 'px'; c.style.top = y + 'px';
      ring.style.left = x + 'px'; ring.style.top = y + 'px';
    },
    pulse(on) {
      ring.style.opacity = on ? '1' : '0';
      ring.style.transform = on ? 'scale(1)' : 'scale(.4)';
    },
  };
})();
"""


class Recorder:
    def __init__(self, page, workdir: Path) -> None:
        self.page = page
        self.workdir = workdir
        self.frames: list[tuple[Path, float]] = []
        self.pos = (VIEWPORT["width"] // 2, VIEWPORT["height"] // 2)
        self.n = 0

    # -- frames -----------------------------------------------------------
    def frame(self, hold: float = 0.6) -> None:
        self.n += 1
        path = self.workdir / f"f{self.n:03d}.png"
        self._cursor_sync()
        self.page.screenshot(path=str(path), full_page=False)
        self.frames.append((path, hold))

    def _cursor_sync(self) -> None:
        x, y = self.pos
        self.page.evaluate(
            "([x, y]) => { if (window.__pfCursor) window.__pfCursor.move(x, y); }",
            [x, y],
        )

    # -- pointer ----------------------------------------------------------
    def move_to(self, target, steps: int = 5, hold: float = 0.07) -> None:
        box = target.bounding_box() if hasattr(target, "bounding_box") else None
        if box is None:
            x, y = target
        else:
            x = box["x"] + min(box["width"] / 2, 60)
            y = box["y"] + box["height"] / 2
        x0, y0 = self.pos
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)
            px = x0 + (x - x0) * ease
            py = y0 + (y - y0) * ease
            self.pos = (px, py)
            self.page.mouse.move(px, py)
            self.frame(hold if i < steps else 0.35)

    def click(
        self,
        target,
        hold_before: float = 0.4,
        hold_after: float = 0.6,
        navigates: bool = False,
    ) -> None:
        self.move_to(target)
        self.page.evaluate("() => window.__pfCursor && window.__pfCursor.pulse(true)")
        self.frame(hold_before)
        x, y = self.pos
        if navigates:
            # The click submits a form; wait for the new document.
            with self.page.expect_navigation(wait_until="domcontentloaded", timeout=120_000):
                self.page.mouse.click(x, y)
            self.settle()
            return
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(250)
        self.page.evaluate("() => window.__pfCursor && window.__pfCursor.pulse(false)")
        self.frame(hold_after)

    # -- navigation -------------------------------------------------------
    def settle(self) -> None:
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(300)
        self.page.evaluate("() => document.fonts.ready")
        self._cursor_sync()

    def scroll_to_heading(self, text: str, offset: int = 16) -> None:
        self.page.evaluate(
            """([text, offset]) => {
              const h = [...document.querySelectorAll('h1,h2')].find(
                (el) => (el.textContent || '').trim().startsWith(text)
              );
              if (!h) return;
              const nav = document.querySelector('.wb-nav');
              const top = (nav ? nav.getBoundingClientRect().bottom : 80) + offset;
              window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - top);
            }""",
            [text, offset],
        )
        self.page.wait_for_timeout(200)

    # -- output -----------------------------------------------------------
    def write_gif(self, dest: Path) -> None:
        concat = self.workdir / "frames.txt"
        lines = []
        for path, hold in self.frames:
            lines.append(f"file '{path.name}'")
            lines.append(f"duration {max(hold, 1 / FPS):.3f}")
        # concat demuxer needs the last file repeated to honour its duration
        lines.append(f"file '{self.frames[-1][0].name}'")
        concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
        vf = (
            f"fps={FPS},scale={GIF_WIDTH}:-1:flags=lanczos,"
            "split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-vf",
                vf,
                "-loop",
                "0",
                str(dest),
            ],
            check=True,
            cwd=str(self.workdir),
        )
        size_kb = dest.stat().st_size // 1024
        print(f"wrote {dest.relative_to(ROOT)} ({len(self.frames)} frames, {size_kb} KB)")


def _context(browser, *, advanced: bool, collection: str | None = COLLECTION):
    ctx = browser.new_context(
        viewport=VIEWPORT, device_scale_factor=1, color_scheme="light"
    )
    cookies = [{"name": "pf_preset", "value": "oa", "url": BASE}]
    if collection:
        cookies.append({"name": "pf_collection", "value": collection, "url": BASE})
    if advanced:
        cookies.append({"name": "pf_advanced", "value": "1", "url": BASE})
    ctx.add_cookies(cookies)
    ctx.add_init_script(CURSOR_JS)
    return ctx


def _wait_job_done(page, timeout_s: int = 240) -> None:
    """Wait until the workbench's queued/running status line goes away."""
    page.wait_for_function(
        """() => {
          const st = document.querySelector('p[role=status] .cmd-status');
          return !st || !/queued|running/.test(st.textContent || '');
        }""",
        timeout=timeout_s * 1000,
    )
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)


# -- flows ------------------------------------------------------------------


def flow_wanted_preview(browser, workdir: Path) -> None:
    """Tick three Missing rows, Preview them, watch the dry-run finish."""
    ctx = _context(browser, advanced=False)
    page = ctx.new_page()
    rec = Recorder(page, workdir)
    page.goto(f"{BASE}/wanted", wait_until="domcontentloaded")
    rec.settle()
    rec.frame(1.2)
    rec.scroll_to_heading("Items")
    rec.frame(0.8)
    boxes = page.locator("input.row-select")
    for i in range(min(3, boxes.count())):
        rec.click(boxes.nth(i), hold_before=0.25, hold_after=0.45)
    rec.move_to(page.locator("#preview-btn"))
    rec.frame(1.0)
    rec.click(page.locator("#preview-btn"), hold_before=0.4, navigates=True)
    page.wait_for_url("**/wanted?poll=*", timeout=15_000)
    rec.settle()
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(200)
    rec.frame(1.6)
    _wait_job_done(page)
    rec.settle()
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(200)
    rec.frame(1.2)
    rec.scroll_to_heading("Items")
    rec.frame(2.4)
    rec.write_gif(OUT / "wanted-preview.gif")
    ctx.close()


def flow_advanced_nav(browser, workdir: Path) -> None:
    """Turn on Advanced and open one of the pages it reveals."""
    ctx = _context(browser, advanced=False)
    page = ctx.new_page()
    rec = Recorder(page, workdir)
    page.goto(f"{BASE}/wanted", wait_until="domcontentloaded")
    rec.settle()
    rec.frame(1.0)
    toggle = page.locator("form.advanced-toggle input[name='advanced']")
    rec.click(toggle, hold_before=0.5, navigates=True)
    rec.frame(1.4)
    rec.click(page.locator("nav.wb-nav a[href='/critique']"), hold_before=0.5, navigates=True)
    rec.frame(2.2)
    rec.write_gif(OUT / "advanced-nav.gif")
    ctx.close()


def flow_discover_map(browser, workdir: Path) -> None:
    """Open the Queue map, switch direction, click a paper."""
    ctx = _context(browser, advanced=False)
    page = ctx.new_page()
    rec = Recorder(page, workdir)
    page.goto(f"{BASE}/discover?tab=queue", wait_until="domcontentloaded")
    rec.settle()
    try:
        page.wait_for_selector("#citationCanvas circle", timeout=30_000)
    except Exception:
        print("skip discover-map.gif (no citation map nodes; run a Topic search first)")
        ctx.close()
        return
    page.wait_for_timeout(1500)  # let the force layout settle
    rec.frame(1.0)
    rec.scroll_to_heading("Map")
    rec.frame(1.2)
    rec.click(
        page.locator("button.citation-filter[data-direction='cites']"),
        hold_before=0.4,
        hold_after=1.0,
    )
    page.locator("#citationCanvas").scroll_into_view_if_needed()
    page.evaluate("() => window.scrollBy(0, -140)")
    page.wait_for_timeout(300)
    rec.frame(1.0)
    nodes = page.locator("#citationCanvas circle")
    count = nodes.count()
    if count:
        rec.click(nodes.nth(min(2, count - 1)), hold_before=0.4, hold_after=0.3)
        page.wait_for_timeout(800)
        rec.frame(2.4)
    rec.write_gif(OUT / "discover-map.gif")
    ctx.close()


def flow_library_scope(browser, workdir: Path) -> None:
    """Expand the tree and set the collection chip."""
    ctx = _context(browser, advanced=False, collection=None)
    page = ctx.new_page()
    rec = Recorder(page, workdir)
    page.goto(f"{BASE}/library", wait_until="domcontentloaded")
    rec.settle()
    rec.frame(1.0)
    parent, child = (COLLECTION.split("/", 1) + [""])[:2]
    parent_node = page.locator(
        ".coll-tree > .coll-node", has=page.locator(":scope > summary .coll-name", has_text=parent)
    ).first
    if parent_node.count():
        rec.click(parent_node.locator(":scope > summary .coll-name").first, hold_after=0.8)
    target_name = child or parent
    row = page.locator(".coll-head", has=page.locator(".coll-name", has_text=target_name)).first
    if not row.count():
        print("skip library-scope.gif (collection not found in tree)")
        ctx.close()
        return
    row.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    rec.frame(0.6)
    rec.click(row.locator("button.icon-btn").first, hold_before=0.5, navigates=True)
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(200)
    rec.frame(1.0)
    rec.click(page.locator("nav.wb-nav a[href='/wanted']"), hold_before=0.4, navigates=True)
    rec.frame(2.2)
    rec.write_gif(OUT / "library-scope.gif")
    ctx.close()


FLOWS = {
    "wanted-preview": flow_wanted_preview,
    "advanced-nav": flow_advanced_nav,
    "discover-map": flow_discover_map,
    "library-scope": flow_library_scope,
}


def main(argv: list[str]) -> int:
    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2
    wanted = argv or list(FLOWS)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in wanted:
            fn = FLOWS.get(name)
            if fn is None:
                print(f"unknown flow {name!r}; choose from {', '.join(FLOWS)}")
                continue
            with tempfile.TemporaryDirectory(prefix=f"pf-{name}-") as tmp:
                fn(browser, Path(tmp))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
