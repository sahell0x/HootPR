from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_admin
from api.db import audit_log, users


async def list_admins(request: Request) -> JSONResponse:
    require_admin(request)
    return JSONResponse([u for u in users() if u["admin"]])


async def export_audit_log(request: Request) -> JSONResponse:
    limit = int(request.query_params.get("limit", "100"))
    return JSONResponse(audit_log()[:limit])
