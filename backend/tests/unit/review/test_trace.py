import pytest

from app.review.schemas import PlanTask
from app.review.trace import InMemoryTraceSink, timed_stage


def test_timed_stage_records_ok_and_failed() -> None:
    sink = InMemoryTraceSink()
    with timed_stage(sink, "diff") as st:
        st.detail = "3 files"
    with pytest.raises(RuntimeError), timed_stage(sink, "sandbox"):
        raise RuntimeError("boom")
    assert [(r.name, r.status, r.detail) for r in sink.stages] == [
        ("diff", "ok", "3 files"),
        ("sandbox", "failed", "RuntimeError: boom"),
    ]
    assert sink.stages[0].as_json()["name"] == "diff"


def test_in_memory_tasks_and_steps() -> None:
    sink = InMemoryTraceSink()
    tid = sink.task_created(
        0, PlanTask(title="t", files=["a"], focus=[], rationale="r", related_symbols=[])
    )
    sink.agent_step(tid, "tool_call", "shell", {"cmd": "ls"}, None, None)
    sink.task_status(tid, "done", "ok")
    assert sink.tasks[tid]["status"] == "done" and sink.steps[0]["step_no"] == 1
