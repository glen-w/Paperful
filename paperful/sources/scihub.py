"""Sci-Hub: ordered mirrors, ALTCHA proof-of-work robot check, HTML parsing, per-mirror circuit breaker.

Mirrors share one database, so a definitive "not found" on one mirror is final; network
errors and robot checks that cannot be passed fall through to the next mirror.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "scihub"
_ALTCHA_HASHES = {
    "SHA-256": hashlib.sha256,
    "SHA-1": hashlib.sha1,
    "SHA-512": hashlib.sha512,
}
_NOT_FOUND_MARKERS = (
    "не найден",  # "статьи по запросу не найдены"
    "отсутствует в базе",  # "статья отсутствует в базе"
    "нет в моей базе",
    "у меня нет",
    "not found",
    "not in my database",
    "unfortunately",
)
_MAX_CAPTCHA_ROUNDS = 2


@dataclass
class PageResult:
    outcome: Outcome
    pdf_url: str | None = None
    note: str = ""


# ---- pure HTML parsing (unit-tested) --------------------------------------


def parse_page(html: str, base_url: str) -> PageResult:
    """Classify a Sci-Hub response and pull out the absolute PDF URL if present."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").lower()

    candidates: list[str] = []
    meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
    if meta and meta.get("content"):
        candidates.append(str(meta["content"]))
    for obj in soup.find_all("object"):
        if "pdf" in (obj.get("type") or "").lower() and obj.get("data"):
            candidates.append(str(obj["data"]))
    for tag in soup.select("#pdf, embed, iframe"):
        if tag.get("src"):
            candidates.append(str(tag["src"]))
    dl = soup.select_one("div.download a[href], #buttons a[href], a[href$='.pdf']")
    if dl:
        candidates.append(str(dl["href"]))
    for btn in soup.find_all(onclick=True):
        m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)", btn["onclick"])
        if m:
            candidates.append(m.group(1))

    for raw in candidates:
        url = _absolutise(raw, base_url)
        if url:
            return PageResult(Outcome.FOUND, pdf_url=url)

    if is_captcha_page(html):
        return PageResult(Outcome.CAPTCHA, note="altcha robot check")

    if soup.select_one("div.notfound, block-rounded.message") or any(
        m in title for m in _NOT_FOUND_MARKERS
    ):
        return PageResult(Outcome.NOT_FOUND, note="article not in Sci-Hub")
    body = soup.get_text(" ", strip=True).lower()
    if any(m in body for m in _NOT_FOUND_MARKERS):
        return PageResult(Outcome.NOT_FOUND, note="article not in Sci-Hub")
    return PageResult(Outcome.ERROR, note="unrecognised page layout")


def is_captcha_page(html: str) -> bool:
    """The robot-check interstitial, not the article page (which also embeds an ALTCHA widget for its report form)."""
    low = html.lower()
    if "citation_pdf_url" in low:
        return False
    return (
        "проверка на робота" in low
        or "are you a robot" in low
        or "verification - sci-hub" in low
        or "cf-turnstile" in low
        or "challenges.cloudflare.com/turnstile" in low
        or bool(re.search(r"fetch\(\s*['\"]/captcha/solution/", html))
    )


def _absolutise(raw: str, base_url: str) -> str | None:
    raw = raw.strip().split("#", 1)[0]
    if not raw or raw.lower().startswith(("javascript:", "data:")):
        return None
    if raw.startswith("//"):
        raw = "https:" + raw
    url = urljoin(base_url, raw)
    if not url.lower().startswith("http"):
        return None
    return url


def extract_altcha_urls(html: str) -> tuple[str | None, str | None]:
    """(challenge_path, solution_path) from the robot-check page."""
    ch = re.search(r'challengeurl\s*=\s*["\']([^"\']+)', html)
    sol = re.search(r"fetch\(\s*['\"](/captcha/solution/[^'\"]+)", html)
    return (ch.group(1) if ch else None, sol.group(1) if sol else None)


def solve_altcha(challenge: dict) -> str:
    """Brute-force the ALTCHA proof-of-work and return the base64 payload the widget would post."""
    alg = challenge.get("algorithm", "SHA-256")
    hasher = _ALTCHA_HASHES.get(alg, hashlib.sha256)
    salt = challenge["salt"]
    target = challenge["challenge"]
    max_number = int(
        challenge.get("maxNumber") or challenge.get("maxnumber") or 1_000_000
    )
    number = None
    for n in range(max_number + 1):
        if hasher(f"{salt}{n}".encode()).hexdigest() == target:
            number = n
            break
    if number is None:
        raise ValueError("ALTCHA challenge not solvable within maxNumber")
    payload = {
        "algorithm": alg,
        "challenge": target,
        "number": number,
        "salt": salt,
        "signature": challenge.get("signature", ""),
        "took": 800,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


# ---- network -----------------------------------------------------------------


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    notes: list[str] = []
    saw_captcha = False
    for mirror in ctx.config.scihub_mirrors:
        if not ctx.mirror_ok(mirror):
            notes.append(f"{mirror}=skipped")
            continue
        result = fetch_from_mirror(ctx, mirror, item.doi)
        if result.outcome is Outcome.FOUND:
            ctx.mirror_succeeded(mirror)
            return Candidate(
                url=result.pdf_url or "",
                source=NAME,
                referer=f"https://{mirror}/{item.doi}",
                note=mirror,
            )
        if result.outcome is Outcome.NOT_FOUND:
            ctx.mirror_succeeded(mirror)
            return Candidate.miss(NAME, Outcome.NOT_FOUND, f"{mirror}: {result.note}")
        notes.append(f"{mirror}={result.note}")
        if result.outcome is Outcome.CAPTCHA:
            saw_captcha = True
            continue  # try another mirror without penalising this one
        ctx.mirror_failed(mirror)
    summary = "; ".join(notes) or "no mirror configured"
    return Candidate.miss(
        NAME, Outcome.CAPTCHA if saw_captcha else Outcome.ERROR, summary
    )


def fetch_from_mirror(ctx: Context, mirror: str, doi: str) -> PageResult:
    base = f"https://{mirror}/"
    page_url = base + doi
    try:
        for _round in range(_MAX_CAPTCHA_ROUNDS + 1):
            resp = ctx.client.get(page_url, timeout=40, headers={"Referer": base})
            if resp.status_code >= 500:
                return PageResult(Outcome.ERROR, note=f"HTTP {resp.status_code}")
            if resp.status_code == 404:
                return PageResult(Outcome.NOT_FOUND, note="HTTP 404")
            if resp.status_code >= 400:
                return PageResult(Outcome.ERROR, note=f"HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "")
            if "application/pdf" in ctype:
                return PageResult(Outcome.FOUND, pdf_url=str(resp.url))
            html = resp.text
            if not is_captcha_page(html):
                return parse_page(html, str(resp.url))
            if not _pass_robot_check(ctx, base, page_url, html):
                return PageResult(Outcome.CAPTCHA, note="captcha unsolved")
        return PageResult(Outcome.CAPTCHA, note="captcha loop")
    except httpx.HTTPError as exc:
        return PageResult(Outcome.ERROR, note=f"{type(exc).__name__}")


def _pass_robot_check(ctx: Context, base: str, page_url: str, html: str) -> bool:
    challenge_path, solution_path = extract_altcha_urls(html)
    if not challenge_path or not solution_path:
        return False
    try:
        ch = ctx.client.get(
            urljoin(base, challenge_path), timeout=30, headers={"Referer": page_url}
        ).json()
        payload = solve_altcha(ch)
        resp = ctx.client.post(
            urljoin(base, solution_path),
            json={"captcha": payload},
            timeout=30,
            headers={"Referer": page_url},
        )
        return resp.status_code == 200 and bool(resp.json().get("success"))
    except (httpx.HTTPError, ValueError, KeyError):
        return False


def ping_mirrors(ctx: Context) -> list[tuple[str, str]]:
    """(mirror, status) for each configured mirror; used by `paperful mirrors`."""
    out = []
    for mirror in ctx.config.scihub_mirrors:
        try:
            resp = ctx.client.get(f"https://{mirror}/", timeout=10)
            out.append((mirror, f"HTTP {resp.status_code}"))
        except httpx.HTTPError as exc:
            out.append((mirror, f"down ({type(exc).__name__})"))
    return out
