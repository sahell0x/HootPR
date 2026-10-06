class RecordingQueue:
    """In-memory TaskQueue: records enqueued task names and args instead of sending them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def enqueue(self, task_name: str, *args: object) -> None:
        self.calls.append((task_name, args))
