"""Celery-side event dispatch (spec §6.5)."""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app.events.models import (
    CommentCreated,
    InstallationChanged,
    IssueOpened,
    PipelineFailed,
    PrEvent,
    ThreadStatusChanged,
    event_adapter,
)
from app.logging import get_logger
from app.models import Installation, PullRequest, WebhookDelivery
from app.orgs.installations import (
    remove_github_repositories,
    sync_github_repositories,
    upsert_github_installation,
)
from app.orgs.service import ensure_organization
from app.review.blocking import refresh_blocking
from app.review.pipeline import find_reviewable_repo, handle_pr_event
from app.worker.context import WorkerContext

log = get_logger(__name__)
_REMOVALS = ("deleted", "repos_removed", "suspend")


def handle_installation(ctx: WorkerContext, ev: InstallationChanged) -> str:
    with ctx.session_factory() as s:
        inst = s.execute(
            select(Installation).where(Installation.github_installation_id == ev.installation_id)
        ).scalar_one_or_none()
        if inst is None and ev.action in _REMOVALS:
            return "ignored"
        if inst is None or ev.action in ("created", "unsuspend", "repos_added"):
            kind = "personal" if ev.account.type == "User" else "org"
            org, _ = ensure_organization(
                s,
                ctx.ledger,
                ctx.settings,
                provider="github",
                provider_org_id=ev.account.id,
                kind=kind,
                name=ev.account.login,
                path=ev.account.login,
                avatar_url=ev.account.avatar_url,
            )
            inst = upsert_github_installation(s, org.id, ev.installation_id, "active")
            s.commit()
            sync_github_repositories(s, inst, ctx.github_repos(ev.installation_id), replace=True)
        elif ev.action == "deleted":
            inst.status = "revoked"
            sync_github_repositories(s, inst, [], replace=True)
        elif ev.action == "suspend":
            inst.status = "suspended"
        elif ev.action == "repos_removed":
            remove_github_repositories(
                s, inst, [r.provider_repo_id for r in ev.repositories_removed]
            )
        s.commit()
    return "processed"


def handle_thread_status(ctx: WorkerContext, ev: ThreadStatusChanged) -> str:
    """A review thread was (un)resolved: re-evaluate request_changes_workflow (R18)."""
    with ctx.session_factory() as s:
        found = find_reviewable_repo(s, ev.provider, ev.repo.provider_repo_id)
        if found is None:
            return "ignored"
        pr_id = s.execute(
            select(PullRequest.id).where(
                PullRequest.repo_id == found[0].id, PullRequest.number == ev.pr_number
            )
        ).scalar_one_or_none()
    if pr_id is None:
        return "ignored"
    refresh_blocking(ctx, pr_id)
    return "processed"


def _dispatch(ctx: WorkerContext, event_json: dict[str, Any]) -> str:
    event = event_adapter.validate_python(event_json)
    structlog.contextvars.bind_contextvars(delivery_id=event.delivery_id)
    if isinstance(event, PrEvent):
        status = handle_pr_event(ctx, event)
        if status == "processed" and event.kind == "pr_closed" and event.pr.state == "merged":
            from app.merge.events import queue_post_merge  # phase 5

            queue_post_merge(ctx, event)
        return status
    if isinstance(event, IssueOpened):
        from app.merge.events import queue_issue_enrichment  # phase 5

        return queue_issue_enrichment(ctx, event)
    if isinstance(event, InstallationChanged):
        return handle_installation(ctx, event)
    if isinstance(event, CommentCreated):
        from app.chat.router import handle_comment_event  # chat imports the pipeline

        return handle_comment_event(ctx, event)
    if isinstance(event, ThreadStatusChanged):
        return handle_thread_status(ctx, event)
    if isinstance(event, PipelineFailed):
        from app.finishing.ci import handle_pipeline_failed  # imports the chat stack

        return handle_pipeline_failed(ctx, event)
    return "ignored"


def process_delivery(ctx: WorkerContext, delivery_row_id: str, event_json: dict[str, Any]) -> str:
    """Handle one webhook delivery and record its outcome. Never raises for handler errors."""
    error: str | None = None
    try:
        status = _dispatch(ctx, event_json)
    except Exception as exc:
        log.exception("event_failed")
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
    finally:
        structlog.contextvars.unbind_contextvars("delivery_id", "review_id", "org_id")
    with ctx.session_factory() as s:
        row = s.get(WebhookDelivery, UUID(delivery_row_id))
        if row is not None:
            row.status, row.error = status, error
            s.commit()
    return status
