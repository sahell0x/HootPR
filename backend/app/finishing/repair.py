"""Self-repair loops of a finishing job as LangGraph state machines (spec §10.1).

Both loops have the same shape: a deterministic check in the sandbox, then, while it fails and
rounds are left, the code-change agent gets the failure as feedback and edits again.

- ``test_repair_graph``: run tests → (passed | infra error | out of attempts | fix) → fix → run
  tests …; the fix round ends the loop early when the agent made no edits.
- ``marker_repair_graph``: conflict markers left → fix → check again, at most
  ``max_rounds`` fixes.

The cycle, its exit conditions and the iteration cap live in the graph edges; the nodes stay thin
wrappers over ``workspace`` and ``CodeChangeAgent`` (whose LLM calls are metered as before).
Dependencies (sandbox, agent, limits) are passed as the LangGraph runtime context, never as state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.finishing.agent import CodeChangeAgent
from app.finishing.prompts import markers_feedback, test_feedback
from app.finishing.workspace import Project, TestStatus, markers_left, run_tests
from app.logging import get_logger
from app.sandbox.base import Sandbox

log = get_logger(__name__)
Verification = Literal["verified", "failed", "couldnt_verify"]
_INFRA: dict[str, str] = {"oom": "ran out of memory", "timeout": "timed out", "error": "failed"}


# --- tests ↔ agent ----------------------------------------------------------------------------


@dataclass(frozen=True)
class TestRepairContext:
    sb: Sandbox
    agent: CodeChangeAgent
    project: Project
    timeout_s: int
    max_iterations: int


class TestRepairState(TypedDict, total=False):
    attempt: int
    status: TestStatus
    output: str
    edits: int
    summary: str
    verification: Verification
    detail: str


def _run_tests(state: TestRepairState, runtime: Runtime[TestRepairContext]) -> TestRepairState:
    c = runtime.context
    attempt = state.get("attempt", 0) + 1
    run = run_tests(c.sb, c.project, c.timeout_s)
    log.info("finishing_tests", attempt=attempt, status=run.status)
    return {"attempt": attempt, "status": run.status, "output": run.output}


def _after_tests(
    state: TestRepairState, runtime: Runtime[TestRepairContext]
) -> Literal["verified", "couldnt_verify", "failed", "fix"]:
    status = state["status"]
    if status == "passed":
        return "verified"
    if status in _INFRA:
        return "couldnt_verify"
    return "failed" if state["attempt"] >= runtime.context.max_iterations else "fix"


def _fix(state: TestRepairState, runtime: Runtime[TestRepairContext]) -> TestRepairState:
    c = runtime.context
    rnd = c.agent.feedback(test_feedback(state["output"], state["attempt"], c.max_iterations))
    return {"edits": rnd.edits, "summary": rnd.summary or state.get("summary", "")}


def _after_fix(state: TestRepairState) -> Literal["run_tests", "failed"]:
    return "failed" if state["edits"] == 0 else "run_tests"


def _verified(state: TestRepairState) -> TestRepairState:
    return {"verification": "verified", "detail": ""}


def _couldnt_verify(state: TestRepairState) -> TestRepairState:
    what = _INFRA.get(state["status"], "failed")
    return {"verification": "couldnt_verify", "detail": f"the test run {what}\n{state['output']}"}


def _failed(state: TestRepairState) -> TestRepairState:
    return {"verification": "failed", "detail": state["output"]}


def build_test_repair_graph() -> CompiledStateGraph[
    TestRepairState, TestRepairContext, TestRepairState, TestRepairState
]:
    g = StateGraph(TestRepairState, context_schema=TestRepairContext)
    g.add_node("run_tests", _run_tests)
    g.add_node("fix", _fix)
    g.add_node("verified", _verified)
    g.add_node("couldnt_verify", _couldnt_verify)
    g.add_node("failed", _failed)
    g.add_edge(START, "run_tests")
    g.add_conditional_edges("run_tests", _after_tests)
    g.add_conditional_edges("fix", _after_fix)
    for terminal in ("verified", "couldnt_verify", "failed"):
        g.add_edge(terminal, END)
    return g.compile(name="finishing-test-repair")


test_repair_graph = build_test_repair_graph()


def repair_until_tests_pass(ctx: TestRepairContext, summary: str) -> tuple[str, str, str]:
    """(verification, detail, summary) after at most ``ctx.max_iterations`` test runs."""
    out = test_repair_graph.invoke(
        {"summary": summary},
        context=ctx,
        config={"recursion_limit": 2 * ctx.max_iterations + 4},
    )
    return out["verification"], out["detail"], out.get("summary", summary)


# --- conflict markers ↔ agent -----------------------------------------------------------------


@dataclass(frozen=True)
class MarkerRepairContext:
    sb: Sandbox
    agent: CodeChangeAgent
    conflicted: tuple[str, ...]
    max_rounds: int


class MarkerRepairState(TypedDict, total=False):
    rounds: int
    left: list[str]
    summary: str


def _check_markers(
    state: MarkerRepairState, runtime: Runtime[MarkerRepairContext]
) -> MarkerRepairState:
    c = runtime.context
    return {"left": list(markers_left(c.sb, c.conflicted))}


def _after_check(
    state: MarkerRepairState, runtime: Runtime[MarkerRepairContext]
) -> Literal["fix_markers", "__end__"]:
    if not state["left"] or state.get("rounds", 0) >= runtime.context.max_rounds:
        return "__end__"
    return "fix_markers"


def _fix_markers(
    state: MarkerRepairState, runtime: Runtime[MarkerRepairContext]
) -> MarkerRepairState:
    rnd = runtime.context.agent.feedback(markers_feedback(state["left"]))
    return {
        "rounds": state.get("rounds", 0) + 1,
        "summary": rnd.summary or state.get("summary", ""),
    }


def build_marker_repair_graph() -> CompiledStateGraph[
    MarkerRepairState, MarkerRepairContext, MarkerRepairState, MarkerRepairState
]:
    g = StateGraph(MarkerRepairState, context_schema=MarkerRepairContext)
    g.add_node("check_markers", _check_markers)
    g.add_node("fix_markers", _fix_markers)
    g.add_edge(START, "check_markers")
    g.add_conditional_edges("check_markers", _after_check)
    g.add_edge("fix_markers", "check_markers")
    return g.compile(name="finishing-marker-repair")


marker_repair_graph = build_marker_repair_graph()


def repair_conflict_markers(ctx: MarkerRepairContext, summary: str) -> tuple[list[str], str]:
    """(files still holding markers, summary) after at most ``ctx.max_rounds`` fix rounds."""
    out = marker_repair_graph.invoke(
        {"summary": summary},
        context=ctx,
        config={"recursion_limit": 2 * ctx.max_rounds + 4},
    )
    return out["left"], out.get("summary", summary)
