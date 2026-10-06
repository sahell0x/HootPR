"""Planner (spec §7.4): up to REVIEW_MAX_TASKS tasks + one light pass."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.platforms.base import FileDiff
from app.review.graph import CodeGraph
from app.review.llm import LLMLike
from app.review.prompts import PLANNER_SYSTEM, system_prompt
from app.review.safety import untrusted
from app.review.schemas import PlanTask, ReviewPlan
from app.review.stages.triage import TriageOutcome
from app.review.tool_results import ToolResults

LIGHT_PASS_TITLE = "Light pass"


def _cap(tasks: list[PlanTask], max_tasks: int) -> list[PlanTask]:
    tasks = list(tasks)
    while len(tasks) > max(1, max_tasks):
        last = tasks.pop()
        tasks[-1] = tasks[-1].model_copy(update={"files": [*tasks[-1].files, *last.files]})
    return tasks


def heuristic_plan(paths: Sequence[str], max_tasks: int) -> list[PlanTask]:
    groups: dict[str, list[str]] = {}
    for p in paths:
        parts = p.split("/")
        key = "/".join(parts[:-1][:2]) or "."
        groups.setdefault(key, []).append(p)
    tasks = [
        PlanTask(
            title=f"Review {key}",
            files=files,
            focus=["correctness", "security"],
            rationale="Files grouped by directory.",
            related_symbols=[],
        )
        for key, files in groups.items()
    ]
    return _cap(tasks, max_tasks)


def _normalize(raw: Sequence[PlanTask], deep: list[str], budget: int) -> list[PlanTask]:
    allowed, seen = set(deep), set[str]()
    tasks: list[PlanTask] = []
    for t in raw:
        files = [p for p in dict.fromkeys(t.files) if p in allowed and p not in seen]
        if not files:
            continue
        seen.update(files)
        tasks.append(
            t.model_copy(
                update={
                    "files": files,
                    "title": (t.title.strip() or "Review")[:120],
                    "focus": t.focus or ["correctness"],
                    "related_symbols": t.related_symbols[:10],
                }
            )
        )
    missing = [p for p in deep if p not in seen]
    if missing:
        tasks += heuristic_plan(missing, budget)
    return _cap(tasks, budget)


def _render(
    files: Sequence[FileDiff], tri: TriageOutcome, graph: CodeGraph, tools: ToolResults
) -> str:
    counts = tools.counts_by_path()
    lines: list[str] = []
    for f in files:
        d = tri.decisions.get(f.path, "deep")
        if d == "skip":
            continue
        lines.append(f"### FILE {f.path} [{d}]")
        lines.append(f"size: +{f.additions} -{f.deletions}")
        # The triage summary is cheap-model output derived from the untrusted diff.
        lines.append(untrusted(f"triage:{f.path}", tri.summaries.get(f.path, "")))
        if counts.get(f.path):
            lines.append(f"static findings: {counts[f.path]}")
    lines.append(untrusted("graph:neighborhood", graph.neighborhood(tri.paths("deep"))))
    return "\n".join(lines)


def plan_review(
    llm: LLMLike,
    files: Sequence[FileDiff],
    tri: TriageOutcome,
    graph: CodeGraph,
    tools: ToolResults,
    cfg: HootPRConfig,
    *,
    max_tasks: int,
    trace: TraceContext,
) -> tuple[list[PlanTask], bool]:
    order = [f.path for f in files]
    deep = [p for p in order if tri.decisions.get(p) == "deep"]
    light = [p for p in order if tri.decisions.get(p) == "light"]
    budget = max(1, max_tasks - (1 if light else 0))
    tasks: list[PlanTask] = []
    degraded = False
    if deep:
        msgs = [
            {
                "role": "system",
                "content": system_prompt(PLANNER_SYSTEM.format(max_tasks=budget), cfg),
            },
            {"role": "user", "content": _render(files, tri, graph, tools)},
        ]
        try:
            res = llm.complete(
                "review", msgs, response_model=ReviewPlan, max_output_tokens=3000, trace=trace
            )
            raw = cast(ReviewPlan, res.parsed).tasks
        except StructuredOutputError:
            raw, degraded = heuristic_plan(deep, budget), True
        tasks = _normalize(raw, deep, budget)
    if light:
        tasks.append(
            PlanTask(
                title=LIGHT_PASS_TITLE,
                files=light,
                focus=["correctness", "docs"],
                rationale="Low-risk files reviewed together in one pass.",
                related_symbols=[],
            )
        )
    return tasks, degraded
