from typing import Any

_USERS: list[dict[str, Any]] = [{"id": 1, "name": "ada", "admin": True}]
_AUDIT: list[dict[str, Any]] = [{"actor": 1, "action": "login"}]


def users() -> list[dict[str, Any]]:
    return list(_USERS)


def audit_log() -> list[dict[str, Any]]:
    return list(_AUDIT)
