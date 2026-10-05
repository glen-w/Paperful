"""Linked-URL health. Report by default; rewrite only from a known playbook."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .page_signals import classify_page_block
from .playbooks import GreyPlaybook
from .sources.landing import rewrite_known_pdf_url
from .zot import Item, is_linked_url_pdf

FINDINGS = ("ok", "redirect", "soft_404", "hard_dead", "paywall_html")
_PAYWALL_LABELS = frozenset({"paywall", "login", "captcha", "cloudflare"})
_SOFT_404 = ("page not found", "404 not found", "does not exist", "no longer available")


@dataclass
class UrlTarget:
    item_key: str
    url: str
    role: str  # parent | linked_pdf
    attachment_key: str = ""


@dataclass
class UrlFinding:
    item_key: str
    url: str
    role: str
    code: str
    final_url: str = ""
    detail: str = ""
    rewrite: str | None = None
    attachment_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "url": self.url,
            "role": self.role,
            "code": self.code,
            "final_url": self.final_url,
            "detail": self.detail,
            "rewrite": self.rewrite or "",
            "attachment_key": self.attachment_key,
        }


def targets_for_item(item: Item, children: list[dict[str, Any]] | None = None) -> list[UrlTarget]:
    out: list[UrlTarget] = []
    url = (item.url or "").strip()
    if url.lower().startswith(("http://", "https://")):
        out.append(UrlTarget(item.key, url, "parent"))
    for child in children or []:
        data = child.get("data") or {}
        link = str(data.get("url") or "").strip()
        if is_linked_url_pdf(data) and link.lower().startswith(("http://", "https://")):
            out.append(
                UrlTarget(
                    item.key,
                    link,
                    "linked_pdf",
                    attachment_key=str(child.get("key") or data.get("key") or ""),
                )
            )
    return out


def classify_probe(
    *,
    status: int | None,
    url: str,
    final_url: str = "",
    content_type: str = "",
    body: str = "",
    error: str = "",
) -> str:
    """One finding code for a short HEAD/GET."""
    if error or status is None:
        return "hard_dead"
    if status in {404, 410} or status >= 500:
        return "hard_dead"
    text = body or ""
    low = text.lower()
    ctype = (content_type or "").lower()
    html = "html" in ctype or text.lstrip().startswith("<")
    if html:
        label = classify_page_block(text)
        if label in _PAYWALL_LABELS:
            return "paywall_html"
        if status == 200 and (
            any(hint in low for hint in _SOFT_404) or len(text.strip()) < 80
        ):
            return "soft_404"
    if status >= 400:
        return "hard_dead"
    final = (final_url or url).split("#", 1)[0].rstrip("/")
    original = url.split("#", 1)[0].rstrip("/")
    if final and final != original:
        return "redirect"
    return "ok"


def planned_rewrite(
    url: str, playbooks: list[GreyPlaybook] | None = None
) -> str | None:
    """Known landing→PDF rewrite, or None when nothing in the playbook list matches."""
    rewritten = rewrite_known_pdf_url(url, playbooks)
    if not rewritten or rewritten.rstrip("/") == url.rstrip("/"):
        return None
    return rewritten


def probe_target(
    client: httpx.Client,
    target: UrlTarget,
    *,
    timeout: float = 8.0,
    playbooks: list[GreyPlaybook] | None = None,
) -> UrlFinding:
    status: int | None = None
    final = ""
    ctype = ""
    body = ""
    error = ""
    try:
        resp = client.head(target.url, follow_redirects=True, timeout=timeout)
        status = resp.status_code
        final = str(resp.url)
        ctype = resp.headers.get("content-type", "")
        needs_body = status >= 400 or "html" in ctype.lower() or status < 300
        if needs_body and "pdf" not in ctype.lower():
            got = client.get(target.url, follow_redirects=True, timeout=timeout)
            status = got.status_code
            final = str(got.url)
            ctype = got.headers.get("content-type", "")
            body = got.text[:4000] if "pdf" not in ctype.lower() else ""
    except Exception as exc:
        error = type(exc).__name__
    code = classify_probe(
        status=status,
        url=target.url,
        final_url=final,
        content_type=ctype,
        body=body,
        error=error,
    )
    rewrite = planned_rewrite(target.url, playbooks)
    if rewrite is None and code == "redirect":
        rewrite = planned_rewrite(final, playbooks)
    return UrlFinding(
        item_key=target.item_key,
        url=target.url,
        role=target.role,
        code=code,
        final_url=final,
        detail=error or (f"HTTP {status}" if status else ""),
        rewrite=rewrite,
        attachment_key=target.attachment_key,
    )
