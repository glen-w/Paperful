"""Shared workbench UI context passed to route registrars."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import Config
from .prefs import prefs_from_request
from .rag_form import resolve_prompt_from_form, save_prompt_as
from .pages import DEST_OPTIONS


def static_asset_version() -> str:
    """Short content hash over the workbench's own static files.

    Templates append ``?v=<hash>`` so browsers refetch after a change without
    anyone hand-bumping version numbers.
    """
    import hashlib

    static_dir = Path(__file__).resolve().parent / "static"
    digest = hashlib.sha256()
    for name in sorted(p.name for p in static_dir.glob("*.*")):
        try:
            digest.update(name.encode("utf-8"))
            digest.update((static_dir / name).read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:10]


@dataclass
class UiContext:
    app: FastAPI
    cfg: Config
    templates: Jinja2Templates
    health_cache: dict[str, Any] = field(
        default_factory=lambda: {"at": 0.0, "checks": []}
    )
    static_version: str = ""

    def __post_init__(self) -> None:
        if not self.static_version:
            self.static_version = static_asset_version()

    def remember_doctor(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.health_cache["at"] = time.time()
        self.health_cache["checks"] = list(checks)
        return list(checks)

    def cached_doctor(self) -> list[dict[str, Any]]:
        return list(self.health_cache["checks"])

    # Collection tree (Library page, Discover pickers). Computing it walks
    # every collection's item count, which took 36 s on a 50k-item mirror.
    collections_cache: dict[str, Any] = field(
        default_factory=lambda: {"at": 0.0, "tree": None}
    )
    COLLECTIONS_TTL: float = 10 * 60

    def collections(self, *, force: bool = False) -> dict[str, Any]:
        from .app import collections_tree as _collections_tree

        now = time.time()
        cached = self.collections_cache.get("tree")
        fresh = (
            now - float(self.collections_cache.get("at") or 0.0) < self.COLLECTIONS_TTL
        )
        if cached is not None and cached.get("ok") and fresh and not force:
            return cached
        tree = _collections_tree(self.cfg)
        self.collections_cache = {"at": now, "tree": tree}
        return tree

    def collections_checked_at(self) -> float:
        return float(self.collections_cache.get("at") or 0.0)

    def invalidate_collections(self) -> None:
        self.collections_cache = {"at": 0.0, "tree": None}

    def ctx(self, request: Request, active: str, **extra: Any) -> dict[str, Any]:
        from .app import _health_label, _health_status, _health_tooltip

        prefs = prefs_from_request(request)
        checks = self.cached_doctor()
        return {
            "request": request,
            "prefs": prefs,
            "active": active,
            "health": _health_status(checks),
            "health_label": _health_label(checks),
            "health_tooltip": _health_tooltip(checks),
            "health_checked_at": float(self.health_cache.get("at") or 0.0),
            "static_v": self.static_version,
            "library_label": {
                "zotero": "Zotero",
                "mendeley": "Mendeley",
                "endnote": "EndNote",
            }.get(str(getattr(self.cfg, "manager", "zotero")).lower(), "the library"),
            **extra,
        }

    def page_url(self, path: str, **kwargs: Any) -> str:
        from urllib.parse import urlencode

        pairs = [(k, str(v)) for k, v in kwargs.items() if v not in (None, "")]
        return path + (("?" + urlencode(pairs)) if pairs else "")

    def after_job(self, path: str, cmd_id: str, **extra: Any) -> RedirectResponse:
        return RedirectResponse(
            url=self.page_url(path, run=cmd_id, **extra), status_code=303
        )

    def optional_int(self, raw: object, *, positive: bool = False) -> int | None:
        text = str(raw or "").strip()
        if not text:
            return None
        value = int(text)
        if positive and value <= 0:
            raise ValueError("limit")
        return value

    async def upload_bytes(self, form: Any, key: str) -> bytes | None:
        upload = form.get(key)
        if upload is None or not getattr(upload, "filename", None):
            return None
        data = await upload.read()  # type: ignore[union-attr]
        return data if data else None

    async def resolved_prompt(self, form: Any) -> Any:
        upload = form.get("prompt_upload")
        data = None
        name = None
        if upload is not None and getattr(upload, "filename", None):
            name = str(upload.filename)
            data = await upload.read()  # type: ignore[union-attr]
            if not data:
                data = None
        return resolve_prompt_from_form(
            self.cfg, form, upload_bytes=data, upload_name=name
        )

    def save_prompt_if_asked(self, form: Any, resolved: Any) -> None:
        if form.get("save_prompt") != "1":
            return
        name = str(form.get("prompt_save_name") or "").strip()
        if not name:
            return
        text = resolved.prompt_text
        if not text and resolved.prompt_path:
            text = Path(resolved.prompt_path).read_text(encoding="utf-8")
        if not text:
            return
        save_prompt_as(self.cfg, name, text)

    def parse_dest(self, raw: object, default: str) -> str:
        value = str(raw or "").strip() or default
        if value not in DEST_OPTIONS:
            raise ValueError("dest")
        return value
