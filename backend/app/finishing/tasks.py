"""Celery tasks of Phase 4 (registered via ``include`` in ``celery_app``)."""

from uuid import UUID

from celery import shared_task

from app.worker.context import get_context


@shared_task(name="finishing.run")  # type: ignore[untyped-decorator]
def finishing_run(job_id: str) -> None:
    from app.finishing.run import run_finishing

    run_finishing(get_context(), UUID(job_id))


@shared_task(name="maintenance.sweep_stuck_finishing")  # type: ignore[untyped-decorator]
def sweep_stuck_finishing_task() -> int:
    from app.finishing.run import sweep_stuck_finishing

    return sweep_stuck_finishing(get_context())
