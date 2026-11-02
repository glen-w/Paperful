"""Workbench UI preferences (cookies only; Advanced does not change config).

Cookies are host-scoped, not port-scoped, so two workbenches on
``127.0.0.1`` (say 8765 and a scratch 8799) would otherwise share the
collection chip and the Advanced toggle. Names are suffixed with the port
whenever it is not the default, and the request's own port decides which
name to read. ``SameSite=Strict`` keeps them off cross-site navigations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_PORT = 8765

COOKIE_COLLECTION = "pf_collection"
COOKIE_LIBRARY_PER_PAGE = "pf_library_per_page"
COOKIE_PRESET = "pf_preset"
COOKIE_ADVANCED = "pf_advanced"
# Legacy cookie name; no longer read (Grab is always fetch-only).
COOKIE_ATTACH_VERIFIED = "pf_attach_verified"

PRESETS = frozenset({"oa", "eoi"})


@dataclass
class WorkbenchPrefs:
    collection: str = ""
    preset: str = "oa"
    advanced: bool = False


def _port(request: Any) -> int | None:
    try:
        port = request.url.port
    except AttributeError:  # pragma: no cover - duck typing for tests
        return None
    if port:
        return int(port)
    host = (request.headers.get("host") or "") if hasattr(request, "headers") else ""
    if ":" in host:
        try:
            return int(host.rsplit(":", 1)[1])
        except ValueError:
            return None
    return None


def cookie_name(request: Any, base: str) -> str:
    """``base`` on the default port (and in tests), ``base_<port>`` elsewhere."""
    port = _port(request)
    if port is None or port == DEFAULT_PORT:
        return base
    return f"{base}_{port}"


def read_cookie(request: Any, base: str) -> str:
    cookies = request.cookies
    return str(cookies.get(cookie_name(request, base)) or "")


def prefs_from_request(request: Any) -> WorkbenchPrefs:
    preset = (read_cookie(request, COOKIE_PRESET) or "oa").strip().lower()
    if preset not in PRESETS:
        preset = "oa"
    advanced = (read_cookie(request, COOKIE_ADVANCED) or "0") == "1"
    return WorkbenchPrefs(
        collection=read_cookie(request, COOKIE_COLLECTION).strip(),
        preset=preset,
        advanced=advanced,
    )


def set_cookie(
    response: Any,
    name: str,
    value: str,
    *,
    max_age: int = 31536000,
    request: Any = None,
) -> None:
    response.set_cookie(
        key=cookie_name(request, name) if request is not None else name,
        value=value,
        max_age=max_age,
        httponly=False,
        samesite="strict",
    )
