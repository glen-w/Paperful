"""Scripted DOI→PDF recover via an external camofox-browser server."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

from .browser_agent import recover_start_url
from .camofox_client import CamofoxClient, CamofoxError, CamofoxLink
from .config import Config
from .download import looks_like_pdf
from .page_signals import classify_page_block
from .playbooks import looks_like_pdf_url
from .zot import Item

_PDF_HREF_RE = re.compile(
    r"pdfft|/pdf(?:\?|$)|citation_pdf_url|download=true|viewcontent\.cgi|"
    r"\.pdf(?:\?|$)|/download/|/bitstream/",
    re.I,
)
_PDF_TEXT_RE = re.compile(
    r"\b(?:pdf|download\s+pdf|view\s+pdf|full\s+text(?:\s+pdf)?|"
    r"télécharger|telecharger|lire\s+le\s+pdf)\b",
    re.I,
)
_BLOCK_LABELS = frozenset({"captcha", "cloudflare", "blocked"})
_USER_ID = "paperful"
_MAX_LINK_TRIES = 4
_DOWNLOAD_POLLS = 4
_DOWNLOAD_PAUSE_S = 0.75


@dataclass
class CamofoxResult:
    pdf_bytes: bytes | None
    note: str
    captcha: bool = False
    final_url: str = ""


def camofox_server_ready(cfg: Config) -> bool:
    base = (cfg.camofox_base_url or "").strip()
    if not base:
        return False
    with CamofoxClient(base, timeout=5.0) as client:
        return client.health()


def run_camofox_recover(cfg: Config, item: Item, url: str | None = None) -> CamofoxResult:
    start = (url or recover_start_url(item) or "").strip()
    if not start:
        return CamofoxResult(None, "no DOI or URL")
    base = (cfg.camofox_base_url or "").strip()
    if not base:
        return CamofoxResult(None, "camofox.base_url empty")
    wall = max(5.0, float(cfg.camofox_max_wall_s))
    deadline = time.monotonic() + wall
    session_key = f"item-{item.key or 'anon'}"
    min_bytes = max(1, int(cfg.min_pdf_bytes))

    with CamofoxClient(base, timeout=min(60.0, wall)) as client:
        if not client.health():
            return CamofoxResult(None, "camofox server unreachable")
        tab_id: str | None = None
        try:
            tab_id = client.create_tab(
                user_id=_USER_ID, session_key=session_key, url=start
            )
            hit = _try_inline_or_downloads(client, tab_id, min_bytes)
            if hit is not None:
                return CamofoxResult(hit, "camofox download", final_url=start)

            snap = _safe_snapshot(client, tab_id)
            block = classify_page_block(snap)
            if block in _BLOCK_LABELS:
                return CamofoxResult(None, block, captcha=True, final_url=start)

            candidates = _rank_pdf_links(_safe_links(client, tab_id), start)
            for link in candidates[:_MAX_LINK_TRIES]:
                if time.monotonic() > deadline:
                    return CamofoxResult(None, "timeout", final_url=start)
                try:
                    if link.ref:
                        client.click(tab_id, user_id=_USER_ID, ref=link.ref)
                    else:
                        client.navigate(tab_id, user_id=_USER_ID, url=link.href)
                except CamofoxError:
                    continue
                hit = _try_inline_or_downloads(client, tab_id, min_bytes)
                if hit is not None:
                    return CamofoxResult(
                        hit, "camofox download", final_url=link.href or start
                    )
                snap = _safe_snapshot(client, tab_id)
                block = classify_page_block(snap)
                if block in _BLOCK_LABELS:
                    return CamofoxResult(
                        None, block, captcha=True, final_url=link.href or start
                    )

            return CamofoxResult(None, "no downloadable pdf", final_url=start)
        except CamofoxError as exc:
            return CamofoxResult(None, str(exc) or type(exc).__name__)
        finally:
            if tab_id:
                client.close_tab(tab_id, user_id=_USER_ID)
            client.close_session(_USER_ID)


def _safe_snapshot(client: CamofoxClient, tab_id: str) -> str:
    try:
        return client.snapshot(tab_id, user_id=_USER_ID)
    except CamofoxError:
        return ""


def _safe_links(client: CamofoxClient, tab_id: str) -> list[CamofoxLink]:
    try:
        return client.links(tab_id, user_id=_USER_ID)
    except CamofoxError:
        return []


def _try_inline_or_downloads(
    client: CamofoxClient, tab_id: str, min_bytes: int
) -> bytes | None:
    try:
        client.fetch_current_resource(tab_id, user_id=_USER_ID)
    except CamofoxError:
        pass
    for _ in range(_DOWNLOAD_POLLS):
        pdf = _largest_pdf(client, tab_id, min_bytes)
        if pdf is not None:
            return pdf
        time.sleep(_DOWNLOAD_PAUSE_S)
    return None


def _largest_pdf(
    client: CamofoxClient, tab_id: str, min_bytes: int
) -> bytes | None:
    try:
        rows = client.downloads(
            tab_id, user_id=_USER_ID, include_data=True, consume=True
        )
    except CamofoxError:
        return None
    best: bytes | None = None
    for row in rows:
        data = row.data
        if not data or len(data) < min_bytes:
            continue
        if not looks_like_pdf(data):
            continue
        if best is None or len(data) > len(best):
            best = data
    return best


def _rank_pdf_links(links: list[CamofoxLink], base_url: str) -> list[CamofoxLink]:
    scored: list[tuple[int, CamofoxLink]] = []
    seen: set[str] = set()
    for link in links:
        href = (link.href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_href = urljoin(base_url, href)
        key = abs_href.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        text = link.text or ""
        score = 0
        if looks_like_pdf_url(abs_href) or _PDF_HREF_RE.search(abs_href):
            score += 3
        if _PDF_TEXT_RE.search(text):
            score += 2
        if score <= 0:
            continue
        scored.append((score, CamofoxLink(href=abs_href, text=text, ref=link.ref)))
    scored.sort(key=lambda pair: (-pair[0], pair[1].href))
    return [link for _, link in scored]
