"""Phase 8 Celery tasks (registered via the Celery ``include`` list)."""

from uuid import UUID

from celery import shared_task

from app.worker.context import get_context


@shared_task(name="reports.run")  # type: ignore[untyped-decorator]
def reports_run(run_id: str) -> str:
    from app.analytics.reports import run_report

    ctx = get_context()
    return run_report(ctx.session_factory, ctx.llm, ctx.settings, UUID(run_id))


@shared_task(name="reports.dispatch_due")  # type: ignore[untyped-decorator]
def reports_dispatch_due() -> int:
    from app.analytics.reports import dispatch_due

    ctx = get_context()
    return dispatch_due(ctx.session_factory, lambda rid: ctx.queue.enqueue("reports.run", rid))


@shared_task(name="change_stack.chat")  # type: ignore[untyped-decorator]
def change_stack_chat(answer_id: str) -> str:
    from app.change_stack.chat import run_change_stack_chat

    return run_change_stack_chat(get_context(), UUID(answer_id))


@shared_task(name="maintenance.sweep_stuck_change_stack_chats")  # type: ignore[untyped-decorator]
def sweep_stuck_change_stack_chats() -> int:
    from app.change_stack.chat import sweep_stuck

    return sweep_stuck(get_context())
