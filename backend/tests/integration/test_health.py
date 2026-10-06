import httpx
import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.integration


async def test_health_reports_components(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert body["checks"]["docker_proxy"] == "unknown"  # no worker heartbeat yet


async def test_health_reads_worker_docker_heartbeat(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    from app.worker.maintenance import DOCKER_HEARTBEAT_KEY

    await app.state.redis.set(DOCKER_HEARTBEAT_KEY, "ok", ex=60)
    assert (await client.get("/api/health")).json()["checks"]["docker_proxy"] == "ok"
    await app.state.redis.set(DOCKER_HEARTBEAT_KEY, "unreachable", ex=60)
    assert (await client.get("/api/health")).json()["checks"]["docker_proxy"] == "unreachable"


def test_probe_docker_proxy() -> None:
    from app.worker.maintenance import probe_docker_proxy

    seen: list[str] = []

    def ok(url: str, timeout: float) -> httpx.Response:
        seen.append(url)
        return httpx.Response(200, text="OK")

    def down(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert probe_docker_proxy("tcp://docker-proxy:2375", ok) == "ok"
    assert seen == ["http://docker-proxy:2375/_ping"]
    assert probe_docker_proxy("tcp://docker-proxy:2375", down) == "unreachable"


async def test_openapi_is_served(client: httpx.AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "HootPR API"
