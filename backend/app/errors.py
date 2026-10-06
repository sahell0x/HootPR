"""Application errors: `{"detail": {"code": ..., "message": ...}}` (plan: API contract)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from app.config.validator import ConfigIssue


def api_error(status: int, code: str, message: str, **extra: object) -> HTTPException:
    detail: dict[str, object] = {"code": code, "message": message, **extra}
    return HTTPException(status_code=status, detail=detail)


def invalid_settings_error(issues: list[ConfigIssue]) -> HTTPException:
    return api_error(
        422,
        "invalid_settings",
        "Settings are invalid",
        errors=[{"line": i.line, "path": i.path, "message": i.message} for i in issues],
    )
