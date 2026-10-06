"""Shared async test helpers."""

from uuid import UUID

import httpx
from fastapi import FastAPI

from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE, SessionStore


async def login_as(client: httpx.AsyncClient, app: FastAPI, user_id: UUID) -> None:
    """Create a real Redis session for ``user_id`` and attach session + CSRF cookies/header."""
    store: SessionStore = app.state.sessions
    sid = await store.create(user_id)
    client.cookies.set(SESSION_COOKIE, sid)
    client.cookies.set(CSRF_COOKIE, "test-csrf")
    client.headers["X-CSRF-Token"] = "test-csrf"
