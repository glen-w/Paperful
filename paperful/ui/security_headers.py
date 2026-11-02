"""Response headers for the loopback workbench.

The templates carry no inline scripts or event handlers, so a strict
``script-src 'self'`` is enforceable: a reflected value can no longer become
executable code. Styles keep ``'unsafe-inline'`` because D3 writes ``style``
attributes on SVG nodes. Hashed static assets (``?v=<hash>``) are cacheable
for a year; everything else is ``no-store`` because pages embed review
tokens and library state.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

STATIC_PREFIX = "/static/"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith(STATIC_PREFIX):
            if request.query_params.get("v"):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                headers.setdefault("Cache-Control", "public, max-age=300")
        else:
            headers.setdefault("Cache-Control", "no-store")
        return response
