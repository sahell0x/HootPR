"""Tool-using review agent (spec §7.5, plan Q11). One run per planner task, sequential."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.config.schema import HootPRConfig
from app.kb.external import ExternalTools
from app.kb.linked import LinkedGraph
from app.llm.types import Message, ToolSpec, TraceContext
from app.review.findings import Candidate
from app.review.graph import CodeGraph, Symbol
from app.review.llm import LLMLike
from app.review.prompts import AGENT_SYSTEM, BUDGET_MSG, NUDGE, PROFILE_NOTES, system_prompt
from app.review.safety import untrusted
from app.review.schemas import CandidateFinding, PlanTask
from app.review.tool_results import ToolResults
from app.sandbox.base import Sandbox, UnsafePath, safe_relpath

READ_MAX_LINES = 400
CHARS_PER_TOKEN = 4  # rough prompt-size estimate used to stop before an oversized call
FINDING_BUDGET_MSG = (
    "error: finding budget exhausted for this task; nothing recorded. Call done now."
)
# Optional report_finding fields models commonly omit; everything else must be present.
FINDING_DEFAULTS: dict[str, Any] = {"start_line": None, "suggestion": None, "evidence": []}
StepHook = Callable[[str, str | None, dict[str, Any], str | None, int | None], None]


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> ToolSpec:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_S, _I = {"type": "string"}, {"type": "integer"}
TOOL_SPECS: list[ToolSpec] = [
    _fn(
        "shell",
        "Run a read-only investigation command with `bash -c` in the sealed sandbox "
        "(cwd = repo root, no network, 20 s timeout, 16 KB output). "
        "Use rg, cat, sed -n, git log/show/blame/diff, ast-grep.",
        {"cmd": _S},
        ["cmd"],
    ),
    _fn(
        "read_file",
        "Read a line-numbered excerpt of a repository file (max 400 lines).",
        {"path": _S, "start": _I, "end": _I},
        ["path", "start", "end"],
    ),
    _fn(
        "find_symbol",
        "Find definitions of a symbol by name in the code graph.",
        {"name": _S},
        ["name"],
    ),
    _fn("find_callers", "List functions that call the named symbol.", {"name": _S}, ["name"]),
    _fn("find_callees", "List functions called by the named symbol.", {"name": _S}, ["name"]),
    _fn(
        "get_tool_findings",
        "Static-analysis findings for a file (empty path = all files).",
        {"path": _S},
        ["path"],
    ),
    _fn(
        "report_finding",
        "Report one confirmed problem (anchored on new-side changed lines).",
        {
            "path": _S,
            "start_line": {"type": ["integer", "null"]},
            "end_line": _I,
            "severity": {"type": "string", "enum": ["critical", "major", "minor", "nitpick"]},
            "category": {
                "type": "string",
                "enum": [
                    "bug",
                    "security",
                    "performance",
                    "maintainability",
                    "style",
                    "docs",
                    "test",
                ],
            },
            "title": _S,
            "body": _S,
            "suggestion": {"type": ["string", "null"]},
            "evidence": {"type": "array", "items": _S},
            "confidence": {"type": "number"},
        },
        [
            "path",
            "start_line",
            "end_line",
            "severity",
            "category",
            "title",
            "body",
            "suggestion",
            "evidence",
            "confidence",
        ],
    ),
    _fn("done", "Finish this task.", {"summary": _S}, ["summary"]),
]
INVESTIGATION_TOOLS = frozenset(
    {"shell", "read_file", "find_symbol", "find_callers", "find_callees", "get_tool_findings"}
)
NO_SHELL_SPECS: list[ToolSpec] = [t for t in TOOL_SPECS if t["function"]["name"] != "shell"]


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int
    max_input_tokens: int  # one prompt (context size), plan Q11
    shell_timeout_s: int = 20
    shell_max_output_kb: int = 16
    # Sum of input tokens over all of a task's calls (every step resends the transcript).
    max_task_input_tokens: int | None = None
    max_findings: int = 15  # report_finding calls recorded per task
    allow_shell: bool = True  # False on the local (host) sandbox: no arbitrary commands

    def specs(self) -> list[ToolSpec]:
        return TOOL_SPECS if self.allow_shell else NO_SHELL_SPECS


@dataclass
class AgentOutcome:
    findings: list[Candidate] = field(default_factory=list)
    summary: str = ""
    steps: int = 0
    stop_reason: str = "turn_cap"


def _symbols(items: list[Symbol]) -> str:
    return "\n".join(s.ref() for s in items) or "no matches"


def _with_linked(local: str, linked: list[str]) -> str:
    if not linked:
        return local
    return f"{local}\n\nIn linked repositories:\n" + "\n".join(linked)


class Toolbox:
    def __init__(
        self,
        sandbox: Sandbox | None,
        graph: CodeGraph,
        tools: ToolResults,
        limits: AgentLimits,
        *,
        linked: Sequence[LinkedGraph] = (),
        external: ExternalTools | None = None,
    ) -> None:
        self._sb, self._graph, self._tools, self._lim = sandbox, graph, tools, limits
        # Phase 7: linked-repo graphs (find_symbol/find_callers span repos) + MCP/web tools.
        self._linked, self._external = list(linked), external

    def extra_specs(self) -> list[ToolSpec]:
        return self._external.specs() if self._external else []

    def handles(self, name: str) -> bool:
        return self._external is not None and self._external.handles(name)

    def call(self, name: str, args: dict[str, Any]) -> str:
        try:
            return self._dispatch(name, args)
        except UnsafePath:
            return "error: path must be relative to the repository root"
        except (KeyError, TypeError, ValueError) as exc:
            return f"error: bad arguments ({exc})"

    def _dispatch(self, name: str, args: dict[str, Any]) -> str:
        if name in ("shell", "read_file"):
            if self._sb is None:
                return "error: sandbox unavailable"
            if name == "shell" and not self._lim.allow_shell:
                return "error: the shell tool is disabled here; use read_file and the graph tools"
            try:
                return self._sandbox_call(self._sb, name, args)
            except (UnsafePath, KeyError, TypeError, ValueError):
                raise
            except Exception as exc:
                # A hung or broken sandbox exec (docker/requests errors) costs this step only,
                # never the whole review.
                return f"error: sandbox command failed ({type(exc).__name__})"
        if name == "find_symbol":
            sym = str(args["name"])
            extra = [g.ref(x) for g in self._linked for x in g.graph.find_symbol(sym, limit=5)]
            return untrusted("graph", _with_linked(_symbols(self._graph.find_symbol(sym)), extra))
        if name == "find_callers":
            sym = str(args["name"])
            extra = [g.ref(x) for g in self._linked for x in g.callers_of(sym)]
            return untrusted("graph", _with_linked(_symbols(self._graph.find_callers(sym)), extra))
        if self.handles(name) and self._external is not None:
            return self._external.call(name, args)
        if name == "find_callees":
            return untrusted("graph", _symbols(self._graph.find_callees(str(args["name"]))))
        if name == "get_tool_findings":
            path = str(args.get("path") or "")
            items = self._tools.for_path(path) if path else list(self._tools.findings)
            return untrusted(
                "tools", "\n".join(f.render() for f in items[:50]) or "no static findings"
            )
        return f"error: unknown tool {name}"

    def _sandbox_call(self, sb: Sandbox, name: str, args: dict[str, Any]) -> str:
        if name == "shell":
            r = sb.shell(
                str(args["cmd"])[:2000],
                timeout_s=self._lim.shell_timeout_s,
                max_output_kb=self._lim.shell_max_output_kb,
            )
            head = (
                f"exit={r.exit_code}"
                + (" (timed out)" if r.timed_out else "")
                + (" (output truncated)" if r.truncated else "")
            )
            tail = f"\n[stderr]\n{r.stderr[:2000]}" if r.stderr else ""
            return untrusted("shell", f"{head}\n{r.stdout}{tail}")
        path = safe_relpath(str(args["path"]))
        start = max(1, int(args.get("start") or 1))
        end = int(args.get("end") or start + 199)
        end = min(max(end, start), start + READ_MAX_LINES - 1)
        prog = f'NR>={start} && NR<={end} {{printf "%6d  %s\\n", NR, $0}}'
        where = sb.exec(["realpath", "-e", "--", ".", f"./{path}"], timeout_s=10, max_output_kb=4)
        root, _, real = where.stdout.strip().partition("\n")
        if where.ok and root and not real.startswith(root.rstrip("/") + "/"):
            raise UnsafePath(path)  # a symlink leaving the checkout
        r = sb.exec(
            ["awk", prog, f"./{path}"], timeout_s=10, max_output_kb=self._lim.shell_max_output_kb
        )
        body = r.stdout if r.ok else f"error: {r.stderr.strip()[:300] or 'cannot read file'}"
        if r.ok and r.truncated:
            body += "\n[output truncated: request fewer lines]"
        return untrusted(f"file:{path}", body)


def estimate_tokens(msgs: list[Message]) -> int:
    chars = 0
    for m in msgs:
        content = m.get("content")
        chars += len(content) if isinstance(content, str) else 0
        for c in m.get("tool_calls") or []:
            chars += len(str(c))
    return chars // CHARS_PER_TOKEN


def task_prompt(task: PlanTask, ordinal: int, pack: str) -> str:
    # Title, rationale and symbols come from the planner model, which read untrusted diffs.
    plan = (
        f"Title: {task.title}\n"
        f"Focus: {', '.join(task.focus) or 'correctness'}\n"
        f"Rationale: {task.rationale}\n"
        f"Related symbols: {', '.join(task.related_symbols) or '-'}"
    )
    return (
        f'<task ordinal="{ordinal}">\n{untrusted("plan", plan)}\n</task>\n\n'
        f"Files in this task (context pack):\n\n{pack}"
    )


def agent_system(cfg: HootPRConfig) -> str:
    return system_prompt(f"{AGENT_SYSTEM}\n\n{PROFILE_NOTES[cfg.reviews.profile]}", cfg)


def run_agent(
    llm: LLMLike,
    task: PlanTask,
    ordinal: int,
    pack: str,
    toolbox: Toolbox,
    limits: AgentLimits,
    cfg: HootPRConfig,
    *,
    trace: TraceContext,
    on_step: StepHook,
) -> AgentOutcome:
    msgs: list[Message] = [
        {"role": "system", "content": agent_system(cfg)},
        {"role": "user", "content": task_prompt(task, ordinal, pack)},
    ]
    out = AgentOutcome()
    nudged = warned = False
    task_input = 0
    specs = limits.specs() + toolbox.extra_specs()
    for _ in range(limits.max_steps + 4):
        if estimate_tokens(msgs) > limits.max_input_tokens:
            out.stop_reason = "token_cap"
            break
        res = llm.complete("review", msgs, tools=specs, max_output_tokens=4096, trace=trace)
        task_input += res.usage.input_tokens
        if not res.tool_calls:
            if nudged:
                out.stop_reason = "no_tool_calls"
                break
            nudged = True
            msgs += [
                {"role": "assistant", "content": res.content or ""},
                {"role": "user", "content": NUDGE},
            ]
            continue
        msgs.append(
            {
                "role": "assistant",
                "content": res.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in res.tool_calls
                ],
            }
        )
        finished = False
        for call in res.tool_calls:
            started = time.perf_counter()
            try:
                parsed = json.loads(call.arguments or "{}")
                args: dict[str, Any] | None = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                args = None
            on_step("tool_call", call.name, args or {}, None, None)
            if args is None:
                result = "error: arguments must be a JSON object"
            elif call.name == "report_finding" and len(out.findings) >= limits.max_findings:
                result = FINDING_BUDGET_MSG
            elif call.name == "report_finding":
                try:
                    out.findings.append(
                        CandidateFinding.model_validate({**FINDING_DEFAULTS, **args}).to_candidate()
                    )
                    result = "recorded"
                except ValidationError as exc:
                    result = (
                        f"error: invalid finding ({exc.error_count()} problems): {str(exc)[:400]}"
                    )
            elif call.name == "done":
                out.summary = str(args.get("summary") or "")[:1000]
                finished = True
                result = "ok"
            elif call.name in INVESTIGATION_TOOLS or toolbox.handles(call.name):
                if out.steps >= limits.max_steps:
                    result = BUDGET_MSG
                else:
                    out.steps += 1
                    result = toolbox.call(call.name, args)
            else:
                result = f"error: unknown tool {call.name}"
            msgs.append({"role": "tool", "tool_call_id": call.id, "content": result})
            on_step(
                "tool_result",
                call.name,
                {},
                result[:2000],
                int((time.perf_counter() - started) * 1000),
            )
        if finished:
            out.stop_reason = "done"
            break
        if res.usage.input_tokens > limits.max_input_tokens or (
            limits.max_task_input_tokens is not None and task_input > limits.max_task_input_tokens
        ):
            out.stop_reason = "token_cap"
            break
        if out.steps >= limits.max_steps:
            if warned:
                out.stop_reason = "step_cap"
                break
            warned = True
            msgs.append({"role": "user", "content": BUDGET_MSG})
    on_step(
        "final",
        None,
        {"stop_reason": out.stop_reason, "steps": out.steps},
        out.summary or None,
        None,
    )
    return out
