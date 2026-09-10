"""Load browser-exported Netscape cookie files into httpx."""

from __future__ import annotations

from pathlib import Path

import httpx


def load_netscape_cookies(path: Path) -> httpx.Cookies:
    """Parse a Netscape cookies.txt (as exported by 'Get cookies.txt LOCALLY' etc.)."""
    cookies = httpx.Cookies()
    if not path.is_file():
        return cookies
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, cookie_path, _secure, _expires, name, value = parts[:7]
        cookies.set(
            name, value, domain=domain.lstrip(".") or domain, path=cookie_path or "/"
        )
    return cookies


def cookie_domains(cookies: httpx.Cookies) -> set[str]:
    return {c.domain for c in cookies.jar}


def apply_netscape_cookies(client: httpx.Client, path: Path) -> None:
    """Merge a Netscape cookies.txt into an httpx client."""
    if not path.is_file():
        return
    for c in load_netscape_cookies(path).jar:
        client.cookies.set(c.name, c.value, domain=c.domain, path=c.path)


def has_domain_cookies(client: httpx.Client, *fragments: str) -> bool:
    """True if the client jar has a cookie for any domain containing a fragment."""
    needles = [f.lower() for f in fragments]
    return any(
        any(n in (c.domain or "").lower() for n in needles) for c in client.cookies.jar
    )
