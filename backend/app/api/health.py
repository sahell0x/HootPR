"""`GET /api/health`: liveness of Postgres, Redis and the Docker socket proxy (spec §11.2).

The api container is deliberately NOT on the docker-proxy network (only ``worker`` may reach the
Docker API, spec §3.1), so the proxy state is the worker's heartbeat in Redis: ``ok`` /
``unreachable``, or ``unknown`` when no worker has reported in the last two minutes.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import Health, HealthChecks
from app.deps import get_db, get_redis
from app.logging import get_logger
from app.worker.maintenance import DOCKER_HEARTBEAT_KEY

router = APIRouter(tags=["health"])
log = get_logger(__name__)

_CHECK_TIMEOUT_S = 2.0


async def _check_db(db: AsyncSession) -> str:
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), _CHECK_TIMEOUT_S)
    except Exception as exc:
        log.warning("health.db_failed", error=type(exc).__name__)
        return "error"
    return "ok"


async def _check_redis(redis: Redis) -> str:
    try:
        await asyncio.wait_for(redis.ping(), _CHECK_TIMEOUT_S)
    except Exception as exc:
        log.warning("health.redis_failed", error=type(exc).__name__)
        return "error"
    return "ok"


async def _check_docker_proxy(redis: Redis) -> str:
    try:
        raw = await asyncio.wait_for(redis.get(DOCKER_HEARTBEAT_KEY), _CHECK_TIMEOUT_S)
    except Exception:
        return "unknown"
    if raw is None:
        return "unknown"
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    return value if value in ("ok", "unreachable") else "unknown"


@router.get("/api/health", response_model=Health)
async def health(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Health:
    db_state = await _check_db(db)
    redis_state = await _check_redis(redis)
    proxy_state = await _check_docker_proxy(redis)
    status = "ok" if db_state == "ok" and redis_state == "ok" else "degraded"
    return Health(
        status=status,
        checks=HealthChecks(db=db_state, redis=redis_state, docker_proxy=proxy_state),
    )
