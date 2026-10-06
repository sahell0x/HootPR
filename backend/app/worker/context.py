"""Everything a worker task needs, injectable for tests."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.billing.ledger import CreditLedger
from app.billing.rate_limit import RateLimiter
from app.crypto import Crypto
from app.db import make_sync_engine, sync_session_factory
from app.kv import RedisKV
from app.llm.gateway import LLMGateway, build_gateway
from app.platforms.factory import PlatformFactory, make_platform_factory
from app.platforms.github.app_auth import make_github_app_auth
from app.platforms.gitlab.admin import GitLabAdmin
from app.sandbox.base import SandboxManager
from app.sandbox.factory import build_sandbox_manager
from app.settings import Settings, get_settings
from app.worker.queue import CeleryTaskQueue, TaskQueue

# A review may run for a long time (Phase 2+ agent); the per-PR lock outlives it.
PR_LOCK_TIMEOUT_S = 1800


@dataclass
class WorkerContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    platforms: PlatformFactory
    ledger: CreditLedger
    limiter: RateLimiter
    queue: TaskQueue
    lock: Callable[[str], AbstractContextManager[object]]
    crypto: Crypto
    github_repos: Callable[[int], list[dict[str, Any]]]
    gitlab_admin: Callable[[str], GitLabAdmin]
    sandboxes: SandboxManager
    # Built lazily on the first review: event processing never needs the LLM gateway.
    llm: Callable[[], LLMGateway]


def build_context(settings: Settings) -> WorkerContext:
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    kv = RedisKV(client)
    crypto = Crypto(settings.fernet_key)
    app_auth = make_github_app_auth(settings, kv)

    def lock(key: str) -> AbstractContextManager[object]:
        redis_lock: AbstractContextManager[object] = client.lock(
            key, timeout=PR_LOCK_TIMEOUT_S, blocking_timeout=PR_LOCK_TIMEOUT_S
        )
        return redis_lock

    gateway: list[LLMGateway] = []

    def llm() -> LLMGateway:
        if not gateway:
            gateway.append(build_gateway(settings))
        return gateway[0]

    return WorkerContext(
        settings=settings,
        session_factory=sync_session_factory(make_sync_engine(settings.database_url)),
        platforms=make_platform_factory(settings, kv, crypto),
        ledger=CreditLedger(),
        limiter=RateLimiter.from_settings(client, settings),
        queue=CeleryTaskQueue(),
        lock=lock,
        crypto=crypto,
        github_repos=app_auth.list_installation_repositories,
        gitlab_admin=lambda token: GitLabAdmin(token, base_url=settings.gitlab_base_url),
        sandboxes=build_sandbox_manager(settings),
        llm=llm,
    )


@lru_cache(maxsize=1)
def get_context() -> WorkerContext:
    return build_context(get_settings())
