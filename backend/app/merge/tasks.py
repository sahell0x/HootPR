"""Celery tasks of Phase 5 (registered via ``celery_app`` ``include``)."""

from typing import Any

from celery import shared_task

from app.worker.context import get_context


@shared_task(name="issues.enrich")  # type: ignore[untyped-decorator]
def issues_enrich(event: dict[str, Any]) -> str:
    from app.events.models import IssueOpened
    from app.merge.issues import enrich_issue

    return enrich_issue(get_context(), IssueOpened.model_validate(event))


@shared_task(name="merge.post_merge")  # type: ignore[untyped-decorator]
def merge_post_merge(provider: str, provider_repo_id: str, number: int) -> str:
    from app.merge.post_merge import run_post_merge

    return run_post_merge(get_context(), provider, provider_repo_id, int(number))
