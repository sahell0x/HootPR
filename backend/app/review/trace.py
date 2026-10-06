"""Review trace (spec §11.2): stage timeline, planner tasks, agent steps, tool runs."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import literal, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, sessionmaker
from uuid_utils.compat import uuid7

from app.models import AgentStep, Review, ReviewTask, ToolRun
from app.review.schemas import PlanTask
from app.review.tool_results import ToolRunRecord

EXCERPT_MAX = 2000
DETAIL_MAX = 500


@dataclass(frozen=True)
class StageRecord:
    name: str
    status: str
    started_at: datetime
    duration_ms: int
    detail: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "duration_ms": self.duration_ms,
            "detail": self.detail,
        }


class TraceSink(Protocol):
    def stage(self, rec: StageRecord) -> None: ...
    def task_created(self, ordinal: int, task: PlanTask) -> UUID: ...
    def task_status(self, task_id: UUID, status: str, summary: str | None = None) -> None: ...
    def agent_step(
        self,
        task_id: UUID | None,
        kind: str,
        tool_name: str | None,
        args: dict[str, Any],
        output_excerpt: str | None,
        duration_ms: int | None,
    ) -> None: ...
    def tool_runs(self, runs: Sequence[ToolRunRecord]) -> None: ...


@dataclass
class InMemoryTraceSink:
    stages: list[StageRecord] = field(default_factory=list)
    tasks: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    runs: list[ToolRunRecord] = field(default_factory=list)

    def stage(self, rec: StageRecord) -> None:
        self.stages.append(rec)

    def task_created(self, ordinal: int, task: PlanTask) -> UUID:
        tid: UUID = uuid7()
        self.tasks[tid] = {"ordinal": ordinal, "task": task, "status": "running", "summary": None}
        return tid

    def task_status(self, task_id: UUID, status: str, summary: str | None = None) -> None:
        self.tasks[task_id].update(status=status, summary=summary)

    def agent_step(
        self,
        task_id: UUID | None,
        kind: str,
        tool_name: str | None,
        args: dict[str, Any],
        output_excerpt: str | None,
        duration_ms: int | None,
    ) -> None:
        self.steps.append(
            {
                "step_no": len(self.steps) + 1,
                "task_id": task_id,
                "kind": kind,
                "tool_name": tool_name,
                "args": args,
                "output_excerpt": output_excerpt,
                "duration_ms": duration_ms,
            }
        )

    def tool_runs(self, runs: Sequence[ToolRunRecord]) -> None:
        self.runs.extend(runs)


class SqlTraceSink:
    """Each call is its own short transaction so the trace is visible live and survives failures."""

    def __init__(self, session_factory: sessionmaker[Session], review_id: UUID) -> None:
        self._sf, self._rid, self._step = session_factory, review_id, 0

    def stage(self, rec: StageRecord) -> None:
        with self._sf() as s:
            s.execute(
                update(Review)
                .where(Review.id == self._rid)
                .values(stages=Review.stages.op("||")(literal([rec.as_json()], type_=JSONB)))
            )
            s.commit()

    def task_created(self, ordinal: int, task: PlanTask) -> UUID:
        with self._sf() as s:
            row = ReviewTask(
                id=uuid7(),
                review_id=self._rid,
                ordinal=ordinal,
                title=task.title[:500],
                rationale=task.rationale[:2000],
                files=list(task.files),
                focus=[f[:32] for f in task.focus],
                related_symbols=list(task.related_symbols),
                status="running",
            )
            s.add(row)
            s.commit()
            tid: UUID = row.id
            return tid

    def task_status(self, task_id: UUID, status: str, summary: str | None = None) -> None:
        with self._sf() as s:
            s.execute(
                update(ReviewTask)
                .where(ReviewTask.id == task_id)
                .values(status=status, summary=summary[:2000] if summary else None)
            )
            s.commit()

    def agent_step(
        self,
        task_id: UUID | None,
        kind: str,
        tool_name: str | None,
        args: dict[str, Any],
        output_excerpt: str | None,
        duration_ms: int | None,
    ) -> None:
        self._step += 1
        with self._sf() as s:
            s.add(
                AgentStep(
                    review_id=self._rid,
                    task_id=task_id,
                    step_no=self._step,
                    kind=kind[:16],
                    tool_name=tool_name[:64] if tool_name else None,
                    args=args,
                    output_excerpt=output_excerpt[:EXCERPT_MAX] if output_excerpt else None,
                    duration_ms=duration_ms,
                )
            )
            s.commit()

    def tool_runs(self, runs: Sequence[ToolRunRecord]) -> None:
        if not runs:
            return
        with self._sf() as s:
            for r in runs:
                s.add(
                    ToolRun(
                        review_id=self._rid,
                        tool=r.tool[:32],
                        status=r.status[:16],
                        duration_ms=r.duration_ms,
                        findings_count=r.findings_count,
                        stderr_excerpt=r.stderr_excerpt or None,
                    )
                )
            s.commit()


@dataclass
class StageHandle:
    status: str = "ok"
    detail: str | None = None


@contextmanager
def timed_stage(sink: TraceSink, name: str) -> Iterator[StageHandle]:
    """Record one timeline entry; an exception marks it ``failed`` and propagates."""
    handle = StageHandle()
    started, t0 = datetime.now(UTC), time.perf_counter()
    try:
        yield handle
    except Exception as exc:
        handle.status, handle.detail = "failed", f"{type(exc).__name__}: {exc}"[:DETAIL_MAX]
        raise
    finally:
        detail = handle.detail[:DETAIL_MAX] if handle.detail else handle.detail
        sink.stage(
            StageRecord(
                name, handle.status, started, int((time.perf_counter() - t0) * 1000), detail
            )
        )
