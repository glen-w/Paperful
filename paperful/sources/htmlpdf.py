"""Render web pages to PDF via Playwright Chromium.

Web and news items print when the page is the article. DOI journal items
print only when ``[htmlpdf].academic`` is ``gated`` or ``auto``. A print is
a page snapshot, not a publisher PDF. Landing pages, cookie walls, and pages
that still offer a native PDF are not printed.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..page_signals import print_page_refusal
from ..playbooks import url_is_direct_skip
from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "htmlpdf"
SCHEMA = "paperful.htmlpdf.proposal.v1"

_WEB_TYPES = frozenset(
    {
        "webpage",
        "blogPost",
        "forumPost",
        "newspaperArticle",
        "magazineArticle",
    }
)
_DOC_TYPES = frozenset({"document", "report"})
_PAYWALL_HINTS = (
    "subscribe to continue",
    "create an account to read",
    "sign in to read",
    "metered paywall",
    "subscription required",
    "pour lire la suite",
    "articles restants",
)


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def academic_mode(item: Item, cfg: object) -> str:
    """``off`` for web/news. Journals follow ``[htmlpdf].academic``."""
    mode = str(getattr(cfg, "htmlpdf_academic", "off") or "off")
    if mode not in {"gated", "auto"}:
        return "off"
    if item.item_type in _WEB_TYPES:
        return "off"
    if item.item_type in _DOC_TYPES and not item.doi:
        return "off"
    return mode


def _webish(item: Item) -> bool:
    if item.item_type in _WEB_TYPES:
        return True
    return item.item_type in _DOC_TYPES and bool(item.url) and not item.doi


def find(item: Item, ctx: Context) -> Candidate:
    mode = academic_mode(item, ctx.config)
    if not _webish(item) and mode == "off":
        return Candidate.miss(NAME, Outcome.SKIPPED, "not a web/news item")
    url = (item.url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return Candidate.miss(NAME, Outcome.SKIPPED, "no URL")
    if url_is_direct_skip(url):
        return Candidate.miss(NAME, Outcome.SKIPPED, "resolver/aggregator URL")
    use_browser = ctx.browser is not None and ctx.browser.available()
    if not use_browser and not playwright_available():
        return Candidate.miss(
            NAME,
            Outcome.SKIPPED,
            "install paperful + playwright install chromium",
        )

    require = mode in {"gated", "auto"}
    capture: dict[str, str] = {}
    try:
        if use_browser:
            pdf_bytes, final_url, note = ctx.browser.render_pdf(
                url,
                _PAYWALL_HINTS,
                title=item.title,
                require_article=require,
                capture=capture,
            )
        else:
            pdf_bytes, final_url, note = _render_pdf(
                url,
                ctx.config.user_agent,
                title=item.title,
                require_article=require,
                capture=capture,
            )
    except Exception as exc:  # Playwright / browser errors
        return Candidate.miss(NAME, Outcome.ERROR, type(exc).__name__)

    if note == "paywall" or (note or "").startswith("refuse:"):
        return Candidate.miss(NAME, Outcome.NOT_FOUND, note or "paywall-like page")
    if not pdf_bytes or not pdf_bytes.lstrip().startswith(b"%PDF"):
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "render produced no PDF")
    if len(pdf_bytes) < ctx.config.min_pdf_bytes:
        return Candidate.miss(
            NAME, Outcome.NOT_FOUND, f"too small ({len(pdf_bytes)} bytes)"
        )

    if mode == "gated":
        path = write_proposal(
            ctx.config,
            item,
            pdf_bytes,
            final_url or url,
            body=capture.get("body", ""),
        )
        return Candidate.miss(NAME, Outcome.SKIPPED, f"proposal {path.name}")

    return Candidate(
        url=final_url or url,
        source=NAME,
        note=note or "chromium print",
        content=pdf_bytes,
    )


def _render_pdf(
    url: str,
    user_agent: str,
    title: str = "",
    require_article: bool = False,
    capture: dict[str, str] | None = None,
) -> tuple[bytes, str, str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=user_agent)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            body = ""
            try:
                body = page.inner_text("body")[:8000]
            except Exception:
                pass
            if capture is not None:
                capture["body"] = body
                capture["url"] = str(page.url)
            low = body.lower()
            if any(h in low for h in _PAYWALL_HINTS):
                return b"", str(page.url), "paywall"
            refusal = print_page_refusal(
                str(page.url), body, title=title, require_article=require_article
            )
            if refusal:
                return b"", str(page.url), f"refuse:{refusal}"
            pdf = page.pdf(
                format="A4",
                print_background=True,
                margin={
                    "top": "12mm",
                    "bottom": "12mm",
                    "left": "12mm",
                    "right": "12mm",
                },
            )
            return pdf, str(page.url), "chromium print"
        finally:
            browser.close()


def proposals_dir(cfg: object) -> Path:
    state = Path(getattr(cfg, "state_dir"))
    return state / "htmlpdf" / "proposals"


def write_proposal(
    cfg: object,
    item: Item,
    pdf_bytes: bytes,
    url: str,
    *,
    body: str = "",
) -> Path:
    folder = proposals_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    pid = item.key or uuid.uuid4().hex[:12]
    pdf_path = folder / f"{pid}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    payload = {
        "schema": SCHEMA,
        "id": pid,
        "status": "pending",
        "item_key": item.key,
        "title": item.title,
        "url": url,
        "pdf": str(pdf_path),
        "body": body[:8000],
    }
    path = folder / f"{pid}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def list_proposals(cfg: object, *, status: str | None = "pending") -> list[dict]:
    folder = proposals_dir(cfg)
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if status and payload.get("status") != status:
            continue
        rows.append(payload)
    return rows


def load_proposal(cfg: object, proposal_id: str) -> tuple[Path, dict]:
    path = proposals_dir(cfg) / f"{proposal_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no htmlpdf proposal {proposal_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return path, payload


def reject_proposal(cfg: object, proposal_id: str) -> dict:
    path, payload = load_proposal(cfg, proposal_id)
    payload["status"] = "rejected"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    pdf = Path(str(payload.get("pdf") or ""))
    if pdf.is_file():
        pdf.unlink()
    return payload


def proposal_gate(payload: dict) -> str | None:
    """Re-check a saved page before attach. Empty text fails closed."""
    from ..page_signals import print_page_refusal

    body = str(payload.get("body") or "")
    if not body.strip():
        return "no page text"
    return print_page_refusal(
        str(payload.get("url") or ""),
        body,
        title=str(payload.get("title") or ""),
        require_article=True,
    )


def mark_applied(cfg: object, proposal_id: str, *, item_key: str) -> dict:
    path, payload = load_proposal(cfg, proposal_id)
    payload["status"] = "applied"
    payload["item_key"] = item_key or payload.get("item_key")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
