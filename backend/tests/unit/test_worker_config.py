from unittest.mock import patch

from app.settings import Settings
from app.worker.celery_app import make_celery
from app.worker.queue import CeleryTaskQueue, TaskQueue
from tests.fakes.queue import RecordingQueue


def test_celery_is_configured_for_single_slow_jobs(settings: Settings) -> None:
    app = make_celery(settings)
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.broker_transport_options["visibility_timeout"] == 3600
    assert app.conf.broker_url == settings.redis_url
    app.loader.import_default_modules()
    assert "hootpr.ping" in app.tasks


def test_ping_task_runs_eagerly(settings: Settings) -> None:
    from app.worker.tasks import ping

    assert ping.apply().get() == "pong"


def test_recording_queue_records() -> None:
    q: TaskQueue = RecordingQueue()
    q.enqueue("review.run", "abc")
    assert isinstance(q, RecordingQueue)
    assert q.calls == [("review.run", ("abc",))]


def test_celery_task_queue_sends_by_name() -> None:
    with patch("app.worker.celery_app.celery_app.send_task") as send:
        CeleryTaskQueue().enqueue("events.process", "d1", 2)
    send.assert_called_once_with("events.process", args=["d1", 2])


def test_stuck_review_sweep_is_scheduled(settings: Settings) -> None:
    app = make_celery(settings)
    app.loader.import_default_modules()
    entry = app.conf.beat_schedule["sweep-stuck-reviews"]
    assert entry["task"] == "maintenance.sweep_stuck_reviews"
    assert entry["task"] in app.tasks


def test_stuck_chat_sweep_is_scheduled(settings: Settings) -> None:
    app = make_celery(settings)
    app.loader.import_default_modules()
    entry = app.conf.beat_schedule["sweep-stuck-chats"]
    assert entry["task"] == "maintenance.sweep_stuck_chats"
    assert entry["task"] in app.tasks


def test_beat_schedules_sandbox_gc(settings: Settings) -> None:
    sched = make_celery(settings).conf.beat_schedule
    assert sched["gc-sandboxes"] == {"task": "maintenance.gc_sandboxes", "schedule": 600.0}


def test_gc_sandboxes_task_is_noop_for_local_backend(settings: Settings) -> None:
    from app.worker import tasks

    ctx = type("Ctx", (), {"settings": settings.model_copy(update={"sandbox_backend": "local"})})
    with patch.object(tasks, "get_context", return_value=ctx):
        assert tasks.gc_sandboxes.apply().get() == 0


def test_beat_purges_review_cache_daily(settings: Settings) -> None:
    app = make_celery(settings)
    app.loader.import_default_modules()
    sched = app.conf.beat_schedule
    assert sched["purge-review-cache"] == {
        "task": "maintenance.purge_review_cache",
        "schedule": 86400.0,
    }
    assert "maintenance.purge_review_cache" in app.tasks


def test_phase3_tasks_and_beat_registered(settings: Settings) -> None:
    app = make_celery(settings)
    app.loader.import_default_modules()
    assert {"chat.run", "learnings.embed", "maintenance.embed_missing_learnings"} <= set(app.tasks)
    beat = {v["task"]: v["schedule"] for v in app.conf.beat_schedule.values()}
    assert beat["maintenance.embed_missing_learnings"] == 3600.0
