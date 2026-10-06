"""Celery app (spec §3.1 `worker`). Run: celery -A app.worker.celery_app:celery_app worker -B"""

from celery import Celery

from app.settings import Settings, get_settings


def make_celery(settings: Settings) -> Celery:
    app = Celery(
        "hootpr",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "app.worker.tasks",
            "app.analytics.tasks",
            "app.finishing.tasks",
            "app.merge.tasks",
        ],
    )
    app.conf.update(
        # Reviews are slow and must survive worker restarts: ack after completion,
        # redeliver when the worker dies, never prefetch more than one job.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_transport_options={"visibility_timeout": 3600},
        result_expires=3600,
        task_default_queue="hootpr",
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            "gitlab-sync-hooks": {"task": "gitlab.sync_hooks", "schedule": 3600.0},
            "cleanup-llm-logs": {"task": "maintenance.cleanup_llm_logs", "schedule": 86400.0},
            "sweep-stuck-reviews": {"task": "maintenance.sweep_stuck_reviews", "schedule": 600.0},
            "sweep-stuck-chats": {"task": "maintenance.sweep_stuck_chats", "schedule": 600.0},
            "docker-heartbeat": {"task": "maintenance.docker_heartbeat", "schedule": 30.0},
            "gc-sandboxes": {"task": "maintenance.gc_sandboxes", "schedule": 600.0},
            "purge-review-cache": {"task": "maintenance.purge_review_cache", "schedule": 86400.0},
            "sweep-stuck-finishing": {
                "task": "maintenance.sweep_stuck_finishing",
                "schedule": 600.0,
            },
            "reports-dispatch-due": {"task": "reports.dispatch_due", "schedule": 900.0},
            "sweep-stuck-change-stack-chats": {
                "task": "maintenance.sweep_stuck_change_stack_chats",
                "schedule": 600.0,
            },
            "embed-missing-learnings": {
                "task": "maintenance.embed_missing_learnings",
                "schedule": 3600.0,
            },
        },
    )
    return app


celery_app = make_celery(get_settings())
