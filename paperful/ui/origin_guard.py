"""Block cross-site POSTs to the loopback workbench (no session auth)."""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _allowed_origin(request: Request) -> bool:
    origin = (request.headers.get("origin") or "").strip()
    referer = (request.headers.get("referer") or "").strip()
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site in {"same-origin", "none", "same-site"}:
        return True
    if site in {"cross-site", "cross-origin"}:
        return False
    host = request.headers.get("host") or ""
    if not host:
        return True
    for header in (origin, referer):
        if not header:
            continue
        try:
            parsed = urlparse(header)
        except ValueError:
            return False
        if parsed.netloc and parsed.netloc != host:
            return False
    return True


class OriginGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        if not _allowed_origin(request):
            return JSONResponse(
                {"ok": False, "error": "cross-origin request blocked"},
                status_code=403,
            )
        return await call_next(request)
