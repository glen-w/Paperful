"""Live check that a grey playbook's first candidate is a real PDF.

A pass means the first URL ``direct`` would hand to ``fetch_pdf`` starts with
``%PDF-`` and is at least ``min_bytes`` long. It does not prove that PDF is the
catalogue record a listing page was about. Section paths stay in the candidate
list, behind PDF-shaped links.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from .download import looks_like_pdf
from .playbooks import (
    GreyPlaybook,
    host_matches,
    load_pack_dir,
    merge_playbooks,
    scrape_playbooks_for_host,
)
from .sources.landing import (
    extract_pdf_urls,
    grey_playbook_name,
    grey_target,
    looks_like_pdf_url,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

EXAMPLES_DIR = Path(__file__).resolve().parent / "data" / "grey_playbooks_examples"
_TRACKING_QUERY = ("_ga", "_gl", "_gcl", "utm_", "fbclid", "mc_")
_HTML_CAP = 1_500_000
_PEEK_CAP = 64 * 1024
_ANCHOR_CAP = 160
_OTHER_ANCHOR_CAP = 80


@dataclass(frozen=True)
class ProbeTarget:
    playbook: str
    url: str = ""
    extra: str = ""
    note: str = ""


@dataclass
class ProbeRow:
    playbook: str
    url: str
    extra: str
    note: str
    stamp: str
    status: str
    chosen: str
    resolved: str
    detail: str
    nbytes: int = 0
    checked: list[dict[str, Any]] = field(default_factory=list)
    anchors: list[dict[str, str]] = field(default_factory=list)
    metas: list[dict[str, str]] = field(default_factory=list)
    probed_at: str = ""

    def to_dict(self, *, with_snapshot: bool = False) -> dict[str, Any]:
        row = {
            "playbook": self.playbook,
            "url": self.url,
            "extra": self.extra,
            "note": self.note,
            "stamp": self.stamp,
            "status": self.status,
            "chosen": self.chosen,
            "resolved": self.resolved,
            "detail": self.detail,
            "nbytes": self.nbytes,
            "checked": self.checked,
            "probed_at": self.probed_at,
        }
        if with_snapshot:
            row["anchors"] = self.anchors
            row["metas"] = self.metas
        return row


def playbooks_for_probe(cfg_books: list[GreyPlaybook], *, examples: bool) -> list[GreyPlaybook]:
    """Config playbooks, with the shipped energy and intl-org examples underneath."""
    if not examples:
        return list(cfg_books)
    return merge_playbooks(False, cfg_books, extra=load_pack_dir(EXAMPLES_DIR))


def load_corpus(path: Path) -> list[ProbeTarget]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    out: list[ProbeTarget] = []
    for i, row in enumerate(raw.get("targets") or []):
        if not isinstance(row, dict):
            raise ValueError(f"targets[{i}] is not a table")
        playbook = str(row.get("playbook") or "").strip()
        url = str(row.get("url") or "").strip()
        extra = str(row.get("extra") or "").strip()
        if not playbook or not (url or extra):
            raise ValueError(f"targets[{i}] needs playbook and url or extra")
        out.append(
            ProbeTarget(
                playbook=playbook,
                url=url,
                extra=extra,
                note=str(row.get("note") or "").strip(),
            )
        )
    if not out:
        raise ValueError(f"{path} has no targets")
    return out


def redact_url(url: str) -> str:
    """Drop analytics query parameters before a URL is stored or printed."""
    if not url or "://" not in url:
        return url
    parts = urlparse(url)
    if not parts.query:
        return url
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_QUERY)
    ]
    return urlunparse(parts._replace(query=urlencode(kept, doseq=True)))


def anchors_to_html(
    anchors: list[dict[str, str]], metas: list[dict[str, str]] | None = None
) -> str:
    """Rebuild a landing from the links a probe stored, for an offline replay."""
    parts: list[str] = ["<html><head>"]
    for meta in metas or []:
        name = escape(meta.get("name") or "", quote=True)
        content = escape(meta.get("content") or "", quote=True)
        parts.append(f'<meta name="{name}" content="{content}">')
    parts.append("</head><body>")
    for anchor in anchors:
        href = escape(anchor.get("href") or "", quote=True)
        text = escape(anchor.get("text") or "Annex")
        parts.append(f'<a href="{href}">{text}</a>')
    parts.append("</body></html>")
    return "".join(parts)


def snapshot_links(html: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Keep PDF-shaped anchors plus a capped set of the other links, in order."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    metas: list[dict[str, str]] = []
    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "").lower()
        content = str(meta.get("content") or "")
        if name in {"citation_pdf_url", "bepress_citation_pdf_url"} and content:
            metas.append({"name": name, "content": content[:500]})
    anchors: list[dict[str, str]] = []
    others = 0
    for tag in soup.find_all("a", href=True):
        href = str(tag["href"]).strip()
        if not href or href.lower().startswith(("mailto:", "javascript:")):
            continue
        item = {"href": href[:500], "text": tag.get_text(" ", strip=True)[:120]}
        if looks_like_pdf_url(href) or href.lower().endswith(".pdf"):
            anchors.append(item)
            continue
        if others >= _OTHER_ANCHOR_CAP or len(anchors) >= _ANCHOR_CAP:
            continue
        anchors.append(item)
        others += 1
    return anchors[:_ANCHOR_CAP], metas


def probe_corpus(
    targets: list[ProbeTarget],
    playbooks: list[GreyPlaybook],
    client: httpx.Client,
    *,
    check: int = 3,
    min_bytes: int = 10_000,
    delay_s: float = 0.0,
) -> list[ProbeRow]:
    rows: list[ProbeRow] = []
    for i, target in enumerate(targets):
        if i and delay_s > 0:
            time.sleep(delay_s)
        rows.append(
            _redact_row(
                probe_one(
                    target, playbooks, client, check=check, min_bytes=min_bytes
                )
            )
        )
    return rows


def probe_one(
    target: ProbeTarget,
    playbooks: list[GreyPlaybook],
    client: httpx.Client,
    *,
    check: int = 3,
    min_bytes: int = 10_000,
) -> ProbeRow:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    item = SimpleNamespace(url=target.url, extra=target.extra, title="", doi=None)
    resolved = grey_target(item, playbooks) or ""
    row = ProbeRow(
        playbook=target.playbook,
        url=target.url,
        extra=target.extra,
        note=target.note,
        stamp="",
        status="error",
        chosen="",
        resolved=resolved,
        detail="",
        probed_at=now,
    )
    if not resolved:
        row.status = "miss"
        row.detail = "no URL after rewrite and synthesize"
        return row
    row.stamp = _stamp(item, resolved, playbooks)
    rewritten = bool(target.url) and resolved != target.url
    synthesized = not target.url and bool(target.extra)
    if rewritten or synthesized or looks_like_pdf_url(resolved):
        hit = _peek_pdf(client, resolved, referer=target.url or None, min_bytes=min_bytes)
        row.checked = [hit]
        row.chosen = resolved
        row.nbytes = int(hit.get("nbytes") or 0)
        row.detail = str(hit.get("detail") or "")
        row.status = _status(hit.get("pdf") is True, False, row.stamp, target.playbook)
        return row

    landing = _read_landing(client, resolved, min_bytes=min_bytes)
    final = landing["final_url"]
    row.resolved = final
    row.stamp = _stamp(item, final, playbooks)
    if landing["error"]:
        row.detail = landing["error"]
        row.status = "error" if landing["status_code"] == 0 else "miss"
        return row
    if landing["pdf"]:
        row.chosen = final
        row.nbytes = int(landing["nbytes"])
        row.checked = [
            {
                "url": final,
                "pdf": True,
                "nbytes": landing["nbytes"],
                "status_code": landing["status_code"],
                "detail": "landing is a PDF",
            }
        ]
        row.detail = "landing is a PDF"
        row.status = _status(True, False, row.stamp, target.playbook)
        return row

    html = landing["html"]
    row.anchors, row.metas = snapshot_links(html)
    urls = extract_pdf_urls(html, final, playbooks)
    if not urls:
        row.detail = "no PDF-shaped link on the landing"
        row.status = "wrong-playbook" if row.stamp != target.playbook else "miss"
        return row
    first_ok = False
    later_ok = False
    for index, cand in enumerate(urls[: max(1, check)]):
        hit = _peek_pdf(client, cand, referer=final, min_bytes=min_bytes)
        row.checked.append(hit)
        if hit.get("pdf"):
            row.chosen = cand
            row.nbytes = int(hit.get("nbytes") or 0)
            row.detail = str(hit.get("detail") or "")
            if index == 0:
                first_ok = True
            else:
                later_ok = True
            break
        row.detail = str(hit.get("detail") or "not a PDF")
    if not first_ok and not later_ok:
        row.chosen = urls[0]
    row.status = _status(first_ok, later_ok, row.stamp, target.playbook)
    return row


def save_recorded(directory: Path, rows: list[ProbeRow]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    counts = {"pass": 0, "alternate": 0, "miss": 0, "wrong-playbook": 0, "error": 0}
    slim: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        counts[row.status] = counts.get(row.status, 0) + 1
        name = f"{i:02d}-{_file_slug(row.playbook)}.json"
        (directory / name).write_text(
            json.dumps(row.to_dict(with_snapshot=True), indent=2) + "\n",
            encoding="utf-8",
        )
        slim.append(row.to_dict(with_snapshot=False))
    index = {
        "probed_at": rows[0].probed_at if rows else "",
        "counts": counts,
        "rows": slim,
    }
    path = directory / "index.json"
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return path


def _redact_row(row: ProbeRow) -> ProbeRow:
    row.chosen = redact_url(row.chosen)
    row.resolved = redact_url(row.resolved)
    row.url = redact_url(row.url)
    for hit in row.checked:
        if isinstance(hit.get("url"), str):
            hit["url"] = redact_url(hit["url"])
    for anchor in row.anchors:
        anchor["href"] = redact_url(anchor.get("href") or "")
    for meta in row.metas:
        meta["content"] = redact_url(meta.get("content") or "")
    return row


def _stamp(item: object, url: str, playbooks: list[GreyPlaybook]) -> str:
    name = grey_playbook_name(item, playbooks)
    if name:
        return name
    host = (urlparse(url).hostname or "").lower()
    scrape = scrape_playbooks_for_host(host, playbooks)
    if scrape:
        return scrape[0].name
    for pb in playbooks:
        if pb.kind == "rewrite" and pb.hosts and host_matches(host, pb.hosts):
            return pb.name
    return ""


def _status(first_ok: bool, later_ok: bool, stamp: str, expected: str) -> str:
    if stamp != expected:
        return "wrong-playbook"
    if first_ok:
        return "pass"
    if later_ok:
        return "alternate"
    return "miss"


def _read_landing(client: httpx.Client, url: str, *, min_bytes: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "final_url": url,
        "html": "",
        "pdf": False,
        "nbytes": 0,
        "status_code": 0,
        "error": "",
    }
    try:
        with client.stream(
            "GET", url, headers={"Accept": "text/html,application/pdf,*/*"}
        ) as resp:
            out["status_code"] = resp.status_code
            out["final_url"] = str(resp.url)
            if resp.status_code >= 400:
                out["error"] = f"HTTP {resp.status_code}"
                return out
            buf = _read_capped(resp, _HTML_CAP)
            length = _content_length_from(resp)
    except httpx.HTTPError as exc:
        out["error"] = type(exc).__name__
        return out
    if looks_like_pdf(buf):
        nbytes = length if length >= len(buf) else len(buf)
        out["nbytes"] = nbytes
        out["pdf"] = nbytes >= min_bytes
        if not out["pdf"]:
            out["error"] = f"too small ({nbytes} bytes)"
        return out
    out["html"] = buf.decode("utf-8", "replace")
    return out


def _peek_pdf(
    client: httpx.Client,
    url: str,
    *,
    referer: str | None,
    min_bytes: int,
) -> dict[str, Any]:
    headers = {"Accept": "application/pdf,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    hit: dict[str, Any] = {
        "url": url,
        "pdf": False,
        "nbytes": 0,
        "status_code": 0,
        "detail": "",
    }
    try:
        with client.stream("GET", url, headers=headers) as resp:
            hit["status_code"] = resp.status_code
            hit["url"] = str(resp.url)
            if resp.status_code >= 400:
                hit["detail"] = f"HTTP {resp.status_code}"
                return hit
            buf = _read_capped(resp, max(min_bytes, _PEEK_CAP))
            length = _content_length_from(resp)
    except httpx.HTTPError as exc:
        hit["detail"] = type(exc).__name__
        return hit
    nbytes = length if length >= len(buf) else len(buf)
    hit["nbytes"] = nbytes
    if not looks_like_pdf(buf):
        hit["detail"] = "not a PDF"
        return hit
    if nbytes < min_bytes:
        hit["detail"] = f"too small ({nbytes} bytes)"
        return hit
    hit["pdf"] = True
    hit["detail"] = "pdf"
    return hit


def _content_length_from(resp: httpx.Response) -> int:
    raw = resp.headers.get("content-length") or ""
    try:
        return int(raw)
    except ValueError:
        return 0


def _read_capped(resp: httpx.Response, limit: int) -> bytes:
    buf = bytearray()
    for chunk in resp.iter_bytes():
        if not chunk:
            continue
        buf += chunk
        if len(buf) >= limit:
            break
    return bytes(buf)


def _file_slug(name: str) -> str:
    keep = [ch.lower() if ch.isalnum() else "-" for ch in name]
    slug = "".join(keep).strip("-")
    return slug or "playbook"
