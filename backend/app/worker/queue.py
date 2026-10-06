"""Task queue abstraction: the API enqueues by task name; tests swap in RecordingQueue."""

from typing import Protocol


class TaskQueue(Protocol):
    def enqueue(self, task_name: str, *args: object) -> None: ...


class CeleryTaskQueue:
    def enqueue(self, task_name: str, *args: object) -> None:
        from app.worker.celery_app import celery_app

        celery_app.send_task(task_name, args=list(args))
