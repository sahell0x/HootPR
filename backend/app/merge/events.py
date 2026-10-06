"""Queue Phase 5 jobs from ``events.process`` (LLM work never runs inline)."""

from __future__ import annotations

from app.events.models import IssueOpened, PrEvent
from app.logging import get_logger
from app.worker.context import WorkerContext

log = get_logger(__name__)
ISSUE_TASK = "issues.enrich"
POST_MERGE_TASK = "merge.post_merge"


def queue_issue_enrichment(ctx: WorkerContext, ev: IssueOpened) -> str:
    try:
        ctx.queue.enqueue(ISSUE_TASK, ev.model_dump(mode="json"))
    except Exception:
        log.exception("issue_enrich_enqueue_failed")
        return "failed"
    return "processed"


def queue_post_merge(ctx: WorkerContext, ev: PrEvent) -> None:
    try:
        ctx.queue.enqueue(POST_MERGE_TASK, ev.provider, ev.repo.provider_repo_id, ev.pr.number)
    except Exception:
        log.exception("post_merge_enqueue_failed")
