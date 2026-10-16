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


@dataclass
class UiContext:
    app: FastAPI
    cfg: Config
    templates: Jinja2Templates
    health_cache: dict[str, Any] = field(default_factory=lambda: {"at": 0.0, "checks": []})

    def remember_doctor(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.health_cache["at"] = time.time()
        self.health_cache["checks"] = list(checks)
        return list(checks)

    def cached_doctor(self) -> list[dict[str, Any]]:
        return list(self.health_cache["checks"])

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
            **extra,
        }

    def page_url(self, path: str, **kwargs: Any) -> str:
        from urllib.parse import urlencode

        pairs = [(k, str(v)) for k, v in kwargs.items() if v not in (None, "")]
        return path + (("?" + urlencode(pairs)) if pairs else "")

    def after_job(self, path: str, cmd_id: str, **extra: Any) -> RedirectResponse:
        return RedirectResponse(url=self.page_url(path, run=cmd_id, **extra), status_code=303)

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
