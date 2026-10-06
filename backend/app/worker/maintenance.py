"""Periodic housekeeping (beat)."""

from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import LlmCall


def purge_llm_excerpts(s: Session, *, retention_days: int, now: datetime) -> int:
    """Null request/response excerpts older than the retention window; keep the metering row."""
    cutoff = now - timedelta(days=retention_days)
    res = s.execute(
        update(LlmCall)
        .where(
            LlmCall.created_at < cutoff,
            (LlmCall.request_excerpt.is_not(None)) | (LlmCall.response_excerpt.is_not(None)),
        )
        .values(request_excerpt=None, response_excerpt=None)
    )
    return int(getattr(res, "rowcount", 0) or 0)


# The worker (the only service on the docker-proxy network, spec §3.1) reports the proxy's
# liveness here; ``/api/health`` reads it instead of reaching the Docker API itself.
DOCKER_HEARTBEAT_KEY = "health:docker_proxy"
DOCKER_HEARTBEAT_TTL_S = 120


def probe_docker_proxy(docker_host: str, get: Callable[..., httpx.Response] = httpx.get) -> str:
    url = docker_host.replace("tcp://", "http://", 1).rstrip("/") + "/_ping"
    try:
        resp = get(url, timeout=2.0)
    except httpx.HTTPError:
        return "unreachable"
    return "ok" if resp.status_code == 200 else "unreachable"
