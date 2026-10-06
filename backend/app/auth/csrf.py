"""Double-submit CSRF check for mutating /api routes (spec §11.1, plan: API contract)."""

import hmac
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.sessions import CSRF_COOKIE

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EXEMPT_PREFIXES = (
    "/api/webhooks/",
    "/api/public/",
)


async def csrf_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    path = request.url.path
    if (
        request.method not in SAFE_METHODS
        and path.startswith("/api/")
        and not path.startswith(EXEMPT_PREFIXES)
    ):
        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get("x-csrf-token")
        if not cookie or not header or not hmac.compare_digest(cookie.encode(), header.encode()):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {"code": "csrf_failed", "message": "Missing or invalid CSRF token"}
                },
            )
    return await call_next(request)
