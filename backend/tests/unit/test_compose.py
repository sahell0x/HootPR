"""Guards on docker-compose.yml security/resource settings (spec §3.1, §11.3)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml not present (e.g. inside the backend image)")
    data: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    return data["services"]


def test_only_worker_reaches_the_docker_proxy(services: dict[str, Any]) -> None:
    on_proxy_net = sorted(
        name for name, svc in services.items() if "dockerapi" in (svc.get("networks") or [])
    )
    assert on_proxy_net == ["docker-proxy", "worker"]


def test_api_runs_a_single_uvicorn_worker_by_default(services: dict[str, Any]) -> None:
    command = " ".join(services["api"]["command"])
    assert "--workers $${API_WORKERS:-1}" in command


def test_env_example_does_not_hijack_the_docker_cli() -> None:
    """`docker compose` reads DOCKER_*/COMPOSE_* from .env, so `make init`'s copy of
    .env.example must not point the host CLI at the in-network docker-proxy."""
    example = COMPOSE.parent / ".env.example"
    if not example.exists():
        pytest.skip(".env.example not present")
    assigned = [
        line.split("=", 1)[0]
        for line in example.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    ]
    assert not [k for k in assigned if k.startswith(("DOCKER_", "COMPOSE_"))]
