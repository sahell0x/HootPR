from starlette.exceptions import HTTPException
from starlette.requests import Request


def require_admin(request: Request) -> None:
    """Raise 403 unless the caller authenticated as an admin (set by the session middleware)."""
    if not request.scope.get("user_is_admin", False):
        raise HTTPException(status_code=403)
