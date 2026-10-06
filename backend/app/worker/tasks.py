"""Celery tasks. Names are the contract with the API. All use ``shared_task`` so they register on
every Celery app (incl. tests)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import shared_task

from app.events.processing import process_delivery
from app.orgs.sync_jobs import sync_github_installation, sync_gitlab_orgs
from app.review.pipeline import run_review, sweep_stuck_reviews
from app.worker.context import get_context
from app.worker.maintenance import (
    DOCKER_HEARTBEAT_KEY,
    DOCKER_HEARTBEAT_TTL_S,
    probe_docker_proxy,
    purge_llm_excerpts,
)


@shared_task(name="hootpr.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"


@shared_task(name="events.process")  # type: ignore[untyped-decorator]
def events_process(delivery_row_id: str, event: dict[str, Any]) -> str:
    return process_delivery(get_context(), delivery_row_id, event)


@shared_task(name="review.run")  # type: ignore[untyped-decorator]
def review_run(review_id: str) -> None:
    run_review(get_context(), UUID(review_id))


@shared_task(name="installations.sync_github")  # type: ignore[untyped-decorator]
def installations_sync_github(installation_id: int) -> int:
    return sync_github_installation(get_context(), installation_id)


@shared_task(name="gitlab.sync_hooks")  # type: ignore[untyped-decorator]
def gitlab_sync_hooks(org_id: str | None = None) -> int:
    return sync_gitlab_orgs(get_context(), org_id)


@shared_task(name="maintenance.cleanup_llm_logs")  # type: ignore[untyped-decorator]
def cleanup_llm_logs() -> int:
    ctx = get_context()
    with ctx.session_factory() as s:
        n = purge_llm_excerpts(
            s, retention_days=ctx.settings.llm_log_retention_days, now=datetime.now(UTC)
        )
        s.commit()
        return n


@shared_task(name="maintenance.sweep_stuck_reviews")  # type: ignore[untyped-decorator]
def sweep_stuck_reviews_task() -> int:
    return sweep_stuck_reviews(get_context())


@shared_task(name="maintenance.docker_heartbeat")  # type: ignore[untyped-decorator]
def docker_heartbeat() -> str:
    import redis

    settings = get_context().settings
    state = probe_docker_proxy(settings.docker_host)
    client = redis.Redis.from_url(settings.redis_url)
    try:
        client.set(DOCKER_HEARTBEAT_KEY, state, ex=DOCKER_HEARTBEAT_TTL_S)
    finally:
        client.close()
    return state


@shared_task(name="maintenance.gc_sandboxes")  # type: ignore[untyped-decorator]
def gc_sandboxes() -> int:
    """Remove sandbox containers a crashed/killed worker left behind (spec §4.3)."""
    settings = get_context().settings
    if settings.sandbox_backend != "docker":
        return 0
    from app.sandbox.docker import DockerSandboxManager

    return DockerSandboxManager.from_settings(settings).gc_orphans(
        settings.sandbox_orphan_max_age_minutes * 60
    )


@shared_task(name="maintenance.purge_review_cache")  # type: ignore[untyped-decorator]
def purge_review_cache_task() -> int:
    from app.review.cache import purge_review_cache

    ctx = get_context()
    with ctx.session_factory() as s:
        n = purge_review_cache(
            s, ttl_days=ctx.settings.review_cache_ttl_days, now=datetime.now(UTC)
        )
        s.commit()
        return n


@shared_task(name="learnings.embed")  # type: ignore[untyped-decorator]
def learnings_embed(learning_id: str) -> bool:
    from app.knowledge.learnings import embed_learning

    ctx = get_context()
    return embed_learning(ctx.session_factory, ctx.llm(), ctx.settings, UUID(learning_id))


@shared_task(name="maintenance.embed_missing_learnings")  # type: ignore[untyped-decorator]
def embed_missing_learnings() -> int:
    from app.knowledge.learnings import embed_missing

    ctx = get_context()
    return embed_missing(ctx.session_factory, ctx.llm(), ctx.settings)


@shared_task(name="maintenance.sweep_stuck_chats")  # type: ignore[untyped-decorator]
def sweep_stuck_chats_task() -> int:
    from app.chat.run import sweep_stuck_chats

    return sweep_stuck_chats(get_context())


@shared_task(name="chat.run")  # type: ignore[untyped-decorator]
def chat_run(chat_message_id: str) -> None:
    from app.chat.run import run_chat

    run_chat(get_context(), UUID(chat_message_id))


@shared_task(name="security.run")  # type: ignore[untyped-decorator]
def security_run(scan_id: str) -> None:
    from app.security.jobs import run_security_scan

    run_security_scan(get_context(), UUID(scan_id))
