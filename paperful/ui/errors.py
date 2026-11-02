"""HTML error pages for browser requests; JSON stays for API clients.

A form POST that trips a 403 (origin guard), 404, 409 (stale review token),
or 500 used to land on a bare JSON body. Browsers that ask for ``text/html``
now get the shell with a one-line cause and a way back. ``/v1/*`` and
``/static/*`` are never touched.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

TITLES = {
    400: "That request was not valid",
    403: "Blocked",
    404: "Page not found",
    405: "Wrong method",
    409: "The library changed since Preview",
    413: "Upload too large",
    422: "That form was not valid",
    500: "Something went wrong",
}

HINTS = {
    400: "Go back and check the highlighted field, then try again.",
    403: "The request did not come from this workbench. Open the page directly at the address in the browser bar and try again.",
    404: "The address may be out of date. Use the navigation above.",
    405: "Open the page from the navigation rather than reloading a form result.",
    409: "Run Preview again, read the new counts, then Apply.",
    413: "Choose a smaller file (the limit is shown next to the upload field).",
    422: "Go back and fix the field named below, then try again.",
    500: "Open Activity to see whether a job failed, then System for the red check. The full trace is in the server log.",
}


def same_host_path(url: str, host: str) -> str:
    """Path (+query) of ``url`` when it points at ``host``; else ``""``.

    Used for "Go back" links and post-toggle redirects so a Referer can never
    send the browser off this workbench.
    """
    from urllib.parse import urlparse

    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    # Covers absolute URLs and protocol-relative ``//other.host/...``.
    if parsed.netloc and parsed.netloc != host:
        return ""
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return ""
    return path + (f"?{parsed.query}" if parsed.query else "")


def wants_html(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/v1/") or path.startswith("/static/"):
        return False
    accept = request.headers.get("accept") or ""
    if "text/html" in accept:
        return True
    # Browsers always send Accept with text/html on navigations; a form POST
    # with Sec-Fetch-Mode: navigate is a browser even when Accept is odd.
    return (request.headers.get("sec-fetch-mode") or "").lower() == "navigate"


def _render(
    templates: Jinja2Templates,
    ctx: Any,
    request: Request,
    *,
    status_code: int,
    message: str,
    detail: str = "",
):
    back = same_host_path(
        request.headers.get("referer") or "", request.headers.get("host") or ""
    )
    return templates.TemplateResponse(
        request,
        "error.html",
        ctx(
            request,
            "",
            status_code=status_code,
            title=TITLES.get(status_code, f"Error {status_code}"),
            message=message,
            hint=HINTS.get(status_code, HINTS[500]),
            detail=detail,
            back=back,
        ),
        status_code=status_code,
    )


def install_error_pages(app: FastAPI, templates: Jinja2Templates, ctx: Any) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if not wants_html(request):
            body: dict[str, Any] = {"ok": False, "error": detail or "error"}
            if isinstance(exc.detail, dict):
                body.update(exc.detail)
            return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)
        message = detail or TITLES.get(exc.status_code, "")
        if exc.status_code == 404 and detail in ("", "Not Found"):
            message = f"There is no page at {request.url.path}."
        return _render(
            templates, ctx, request, status_code=exc.status_code, message=message
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        fields = ", ".join(
            ".".join(
                str(p) for p in (err.get("loc") or []) if p not in ("body", "query")
            )
            for err in exc.errors()
        )
        if not wants_html(request):
            return JSONResponse(
                {"ok": False, "error": "validation", "fields": fields},
                status_code=422,
            )
        return _render(
            templates,
            ctx,
            request,
            status_code=422,
            message=f"Check: {fields}." if fields else "A field was missing.",
        )

    @app.exception_handler(Exception)
    async def _server_error(request: Request, exc: Exception):
        log.exception(
            "workbench request failed: %s %s", request.method, request.url.path
        )
        message = str(exc) or exc.__class__.__name__
        if not wants_html(request):
            return JSONResponse({"ok": False, "error": message}, status_code=500)
        return _render(
            templates,
            ctx,
            request,
            status_code=500,
            message=message[:300],
            detail=exc.__class__.__name__,
        )
