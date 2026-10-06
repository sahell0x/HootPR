"""Shared fixtures. Containers start lazily, only for tests that request them.

Integration tests use testcontainers (`pgvector/pgvector:pg16`, `redis:7-alpine`) on random host
ports, unless TEST_DATABASE_URL / TEST_REDIS_URL point at existing services.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import redis
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.billing.ledger import CreditLedger
from app.billing.rate_limit import RateLimiter
from app.crypto import Crypto
from app.models import Base
from app.platforms.local import LocalPlatform
from app.settings import Settings
from app.worker.context import WorkerContext
from tests.fakes.engine_llm import EngineFakeLLM, make_test_gateway
from tests.fakes.queue import RecordingQueue
from tests.fakes.sandbox import FakeSandboxManager

BACKEND_DIR = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """``sandbox``-marked tests need Docker + the sandbox image: only ``make test-sandbox``."""
    if os.environ.get("HOOTPR_SANDBOX_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="needs Docker + hootpr/sandbox image: run `make test-sandbox`")
    for item in items:
        if item.get_closest_marker("sandbox") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def settings(rsa_pem: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        app_base_url="http://localhost:3000",
        api_base_url="http://localhost:8000",
        secret_encryption_key=Fernet.generate_key().decode(),
        session_secret="s" * 48,
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        redis_url="redis://127.0.0.1:1/0",
        github_app_id="12345",
        github_app_slug="hootpr-test",
        github_app_private_key=rsa_pem,
        github_webhook_secret="gh-webhook-secret",
        github_oauth_client_id="gh-client",
        github_oauth_client_secret="gh-client-secret",
        gitlab_oauth_client_id="gl-client",
        gitlab_oauth_client_secret="gl-client-secret",
        razorpay_key_id="rzp_test_key123",
        razorpay_key_secret="rzp-secret",
        razorpay_webhook_secret="rzp-webhook-secret",
        llm_review_base_url="http://fake-llm/v1",
        llm_review_api_key="k",
        llm_cheap_base_url="http://fake-llm/v1",
        llm_cheap_api_key="k",
        llm_embed_base_url="http://fake-llm/v1",
        llm_embed_api_key="k",
        docker_host="tcp://127.0.0.1:1",
    )


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="hootpr",
        password="hootpr",
        dbname="hootpr_test",
        driver="psycopg",
    ) as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_db(pg_url: str) -> str:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", pg_url)
    command.upgrade(cfg, "head")
    return pg_url


@pytest.fixture
def sync_engine(migrated_db: str) -> Iterator[Engine]:
    engine = create_engine(migrated_db)
    yield engine
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.fixture
def session_factory(sync_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(sync_engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture(scope="session")
def _redis_session_url() -> Iterator[str]:
    url = os.environ.get("TEST_REDIS_URL")
    if url:
        yield url
        return
    from testcontainers.community.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}/0"


@pytest.fixture
def redis_url(_redis_session_url: str) -> Iterator[str]:
    r = redis.Redis.from_url(_redis_session_url)
    r.flushdb()
    yield _redis_session_url
    r.flushdb()
    r.close()


@pytest.fixture
def redis_client(redis_url: str) -> Iterator[redis.Redis]:
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def int_settings(settings: Settings, migrated_db: str, redis_url: str) -> Settings:
    return settings.model_copy(update={"database_url": migrated_db, "redis_url": redis_url})


# --- app / HTTP client (Task 5) -------------------------------------------------------------


@pytest.fixture
async def app(int_settings: Settings, sync_engine: Engine) -> AsyncIterator[FastAPI]:
    """App wired to the test containers; depends on ``sync_engine`` so tables are truncated."""
    from app.main import create_app

    application = create_app(int_settings)
    application.state.queue = RecordingQueue()
    yield application
    await application.state.http.aclose()
    await application.state.redis.aclose()
    application.state.sync_redis.close()
    await application.state.async_engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def crypto(settings: Settings) -> Crypto:
    return Crypto(settings.fernet_key)


# --- worker context (Task 25) ----------------------------------------------------------------


@pytest.fixture
def local_platform() -> LocalPlatform:
    return LocalPlatform()


@pytest.fixture
def engine_llm() -> EngineFakeLLM:
    """The stage-aware fake LLM behind ``make_wctx``'s default gateway (no findings)."""
    return EngineFakeLLM()


@pytest.fixture
def make_wctx(
    int_settings: Settings,
    session_factory: sessionmaker[Session],
    redis_client: redis.Redis,
    crypto: Crypto,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
) -> Callable[..., WorkerContext]:
    def _make(**overrides: Any) -> WorkerContext:
        def no_gitlab(token: str) -> Any:
            raise AssertionError("gitlab_admin not configured for this test")

        base: dict[str, Any] = {
            "settings": int_settings,
            "session_factory": session_factory,
            "platforms": lambda s, repo: local_platform,
            "ledger": CreditLedger(),
            "limiter": RateLimiter.from_settings(redis_client, int_settings),
            "queue": RecordingQueue(),
            "lock": lambda key: contextlib.nullcontext(),
            "crypto": crypto,
            "github_repos": lambda installation_id: [],
            "gitlab_admin": no_gitlab,
            "sandboxes": FakeSandboxManager(),
            "llm": lambda: make_test_gateway(engine_llm)[0],
        }
        base.update(overrides)
        return WorkerContext(**base)

    return _make
