"""FastAPI app factory. Run with: uvicorn --factory app.main:create_app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis as sync_redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api import (
    admin,
    analytics,
    auth,
    billing,
    change_stack,
    config,
    finishing,
    github_setup,
    gitlab,
    health,
    learnings,
    mcp_servers,
    members,
    meta,
    org_settings,
    orgs,
    public_v1,
    reports,
    repos,
    reviews,
    security,
    webhooks,
)
from app.auth.csrf import csrf_middleware
from app.auth.sessions import SessionStore
from app.crypto import Crypto
from app.db import async_session_factory, make_async_engine
from app.logging import configure_logging, get_logger
from app.settings import _DEV_WARNING, Settings, get_settings
from app.worker.queue import CeleryTaskQueue


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.http.aclose()
    await app.state.redis.aclose()
    app.state.sync_redis.close()
    await app.state.async_engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    if settings.using_dev_secrets:
        get_logger(__name__).warning(_DEV_WARNING, app_env=settings.app_env)
    app = FastAPI(title="HootPR API", version="0.1.0", lifespan=_lifespan)
    app.state.settings = settings
    app.state.async_engine = make_async_engine(settings.database_url)
    app.state.sessionmaker = async_session_factory(app.state.async_engine)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.sync_redis = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.sessions = SessionStore(app.state.redis, settings.session_key)
    app.state.http = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "HootPR"})
    app.state.crypto = Crypto(settings.fernet_key)
    app.state.queue = CeleryTaskQueue()
    app.middleware("http")(csrf_middleware)
    # Added last = outermost: preflights are answered before the CSRF check, and error responses
    # still carry the CORS headers the dashboard (a separate origin) needs to read them.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token", "Authorization", "X-API-Key"],
        max_age=600,
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(meta.router)
    app.include_router(orgs.router)
    app.include_router(github_setup.router)
    app.include_router(config.router)
    app.include_router(org_settings.router)
    app.include_router(learnings.router)
    app.include_router(mcp_servers.router)
    app.include_router(members.router)
    app.include_router(repos.router)
    app.include_router(gitlab.router)
    app.include_router(reviews.router)
    app.include_router(finishing.router)
    app.include_router(billing.router)
    app.include_router(webhooks.router)
    app.include_router(analytics.router)
    app.include_router(reports.router)
    app.include_router(admin.router)
    app.include_router(public_v1.router)
    app.include_router(change_stack.router)
    app.include_router(security.router)
    return app
