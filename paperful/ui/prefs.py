"""Workbench UI preferences (cookies only; Advanced does not change config)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

COOKIE_COLLECTION = "pf_collection"
COOKIE_PRESET = "pf_preset"
COOKIE_ADVANCED = "pf_advanced"
COOKIE_ATTACH_VERIFIED = "pf_attach_verified"

PRESETS = frozenset({"oa", "eoi"})


@dataclass
class WorkbenchPrefs:
    collection: str = ""
    preset: str = "oa"
    advanced: bool = False
    attach_verified: bool = True


def prefs_from_request(request: Any) -> WorkbenchPrefs:
    cookies = request.cookies
    preset = (cookies.get(COOKIE_PRESET) or "oa").strip().lower()
    if preset not in PRESETS:
        preset = "oa"
    advanced = (cookies.get(COOKIE_ADVANCED) or "0") == "1"
    attach = (cookies.get(COOKIE_ATTACH_VERIFIED) or "1") == "1"
    return WorkbenchPrefs(
        collection=(cookies.get(COOKIE_COLLECTION) or "").strip(),
        preset=preset,
        advanced=advanced,
        attach_verified=attach,
    )


def set_cookie(response: Any, name: str, value: str, *, max_age: int = 31536000) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=False,
        samesite="lax",
    )
