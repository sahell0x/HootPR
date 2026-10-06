"""The code-change agent (spec §10.1): a bounded tool loop that edits files in the sandbox.

Tools: ``read_file``/``shell`` (the review agent's implementations, shell only on the docker
backend), ``write_file``, ``apply_patch``, ``delete_file`` and ``done``. The transcript is kept
between rounds so test failures can be fed back (``feedback``) without starting over.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any

from app.config.schema import HootPRConfig
from app.finishing.prompts import code_agent_system
from app.finishing.workspace import work_dir, write_bytes
from app.llm.types import Message, ToolSpec, TraceContext
from app.review.agent import AgentLimits, Toolbox, estimate_tokens
from app.review.graph import CodeGraph
from app.review.llm import LLMLike
from app.review.tool_results import ToolResults
from app.sandbox.base import Sandbox, SandboxError, UnsafePath, safe_relpath

SHELL_TIMEOUT_S = 60
MAX_WRITE_CHARS = 200_000
MAX_PATCH_CHARS = 120_000  # one argv element (Linux: 128 KiB)
KEEP_RECENT_TOOL_RESULTS = 8
NUDGE = "Use the tools to make the change, then call done(summary). Do not answer in plain text."
BUDGET = "Your tool budget is exhausted. Call done(summary) now."


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
SHELL_SPEC = _fn(
    "shell",
    "Run a command with `bash -c` in the repository root (no network, 60 s, 16 KB output).",
    {"cmd": _S},
    ["cmd"],
)
TOOL_SPECS: list[ToolSpec] = [
    _fn(
        "read_file",
        "Read a line-numbered excerpt of a repository file (max 400 lines).",
        {"path": _S, "start": _I, "end": _I},
        ["path", "start", "end"],
    ),
    _fn(
        "write_file",
        "Create or replace a repository file with the complete new content.",
        {"path": _S, "content": _S},
        ["path", "content"],
    ),
    _fn(
        "apply_patch",
        "Apply a unified diff (with ---/+++ headers and context lines) to the repository.",
        {"patch": _S},
        ["patch"],
    ),
    _fn("delete_file", "Delete a repository file.", {"path": _S}, ["path"]),
    _fn(
        "done",
        "Finish. summary: 1-6 markdown bullet points describing the change for the developer.",
        {"summary": _S},
        ["summary"],
    ),
]
EDIT_TOOLS = frozenset({"write_file", "apply_patch", "delete_file"})


@dataclass(frozen=True)
class CodeAgentLimits:
    max_steps: int
    max_input_tokens: int
    max_total_input_tokens: int
    allow_shell: bool


@dataclass
class RoundResult:
    summary: str
    steps: int
    edits: int
    stop_reason: str


def _blocked(rel: str) -> bool:
    return rel == ".git" or rel.startswith(".git/")


class CodeChangeAgent:
    def __init__(
        self,
        llm: LLMLike,
        sb: Sandbox,
        cfg: HootPRConfig,
        limits: CodeAgentLimits,
        trace: TraceContext,
    ) -> None:
        self._llm, self._sb, self._lim, self._trace = llm, sb, limits, trace
        self._toolbox = Toolbox(
            sb,
            CodeGraph.empty(),
            ToolResults(),
            AgentLimits(
                limits.max_steps,
                limits.max_input_tokens,
                shell_timeout_s=SHELL_TIMEOUT_S,
                shell_max_output_kb=16,
                allow_shell=limits.allow_shell,
            ),
        )
        self._specs = ([SHELL_SPEC] if limits.allow_shell else []) + TOOL_SPECS
        self._msgs: list[Message] = [{"role": "system", "content": code_agent_system(cfg)}]
        self.total_input = 0
        self.total_edits = 0
        self._patches = 0

    # --- public ----------------------------------------------------------------------------
    def start(self, task: str) -> RoundResult:
        self._msgs.append({"role": "user", "content": task})
        return self._round(self._lim.max_steps)

    def feedback(self, text: str) -> RoundResult:
        self._msgs.append({"role": "user", "content": text})
        return self._round(max(4, self._lim.max_steps // 2))

    # --- loop ------------------------------------------------------------------------------
    def _round(self, max_steps: int) -> RoundResult:
        out = RoundResult("", 0, 0, "turn_cap")
        nudged = warned = False
        for _ in range(max_steps + 4):
            if self.total_input > self._lim.max_total_input_tokens:
                out.stop_reason = "token_cap"
                break
            if estimate_tokens(self._msgs) > self._lim.max_input_tokens and not self._compact():
                out.stop_reason = "token_cap"
                break
            res = self._llm.complete(
                "review", self._msgs, tools=self._specs, max_output_tokens=8192, trace=self._trace
            )
            self.total_input += res.usage.input_tokens
            if not res.tool_calls:
                if nudged:
                    out.summary = out.summary or (res.content or "")[:2000]
                    out.stop_reason = "no_tool_calls"
                    break
                nudged = True
                self._msgs += [
                    {"role": "assistant", "content": res.content or ""},
                    {"role": "user", "content": NUDGE},
                ]
                continue
            self._msgs.append(
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
                try:
                    parsed = json.loads(call.arguments or "{}")
                    args: dict[str, Any] | None = parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    args = None
                if args is None:
                    result = "error: arguments must be a JSON object"
                elif call.name == "done":
                    out.summary = str(args.get("summary") or "")[:3000]
                    finished = True
                    result = "ok"
                elif out.steps >= max_steps:
                    result = BUDGET
                else:
                    out.steps += 1
                    result = self._call(call.name, args)
                    if call.name in EDIT_TOOLS and result.startswith("ok"):
                        out.edits += 1
                        self.total_edits += 1
                self._msgs.append({"role": "tool", "tool_call_id": call.id, "content": result})
            if finished:
                out.stop_reason = "done"
                break
            if out.steps >= max_steps:
                if warned:
                    out.stop_reason = "step_cap"
                    break
                warned = True
                self._msgs.append({"role": "user", "content": BUDGET})
        return out

    def _compact(self) -> bool:
        """Trim old tool outputs (keeps the call/response structure). False: nothing to trim."""
        tool_idx = [i for i, m in enumerate(self._msgs) if m.get("role") == "tool"]
        trimmed = False
        for i in tool_idx[:-KEEP_RECENT_TOOL_RESULTS]:
            if self._msgs[i].get("content") != "[output trimmed]":
                self._msgs[i]["content"] = "[output trimmed]"
                trimmed = True
        return trimmed and estimate_tokens(self._msgs) <= self._lim.max_input_tokens

    # --- tools -----------------------------------------------------------------------------
    def _call(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name in ("shell", "read_file"):
                return self._toolbox.call(name, args)
            if name == "write_file":
                return self._write(str(args["path"]), str(args["content"]))
            if name == "apply_patch":
                return self._apply_patch(str(args["patch"]))
            if name == "delete_file":
                return self._delete(str(args["path"]))
        except UnsafePath:
            return "error: path must be a regular file inside the repository"
        except (KeyError, TypeError, ValueError) as exc:
            return f"error: bad arguments ({exc})"
        except SandboxError as exc:
            return f"error: {exc}"[:500]
        except Exception as exc:  # a broken sandbox exec costs this step only
            return f"error: sandbox command failed ({type(exc).__name__})"
        return f"error: unknown tool {name}"

    def _write(self, path: str, content: str) -> str:
        rel = safe_relpath(path)
        if _blocked(rel):
            raise UnsafePath(rel)
        if len(content) > MAX_WRITE_CHARS:
            return f"error: content larger than {MAX_WRITE_CHARS} characters"
        write_bytes(self._sb, rel, content.encode())
        return f"ok: wrote {rel} ({content.count(chr(10)) + 1} lines)"

    def _delete(self, path: str) -> str:
        rel = safe_relpath(path)
        if _blocked(rel):
            raise UnsafePath(rel)
        r = self._sb.exec(["rm", "-f", "--", f"./{rel}"], timeout_s=10, max_output_kb=4)
        return f"ok: deleted {rel}" if r.ok else f"error: {r.stderr.strip()[:300]}"

    def _apply_patch(self, patch: str) -> str:
        if len(patch) > MAX_PATCH_CHARS:
            return f"error: patch larger than {MAX_PATCH_CHARS} characters"
        if not patch.endswith("\n"):
            patch += "\n"
        self._patches += 1
        target = f"{work_dir(self._sb)}/.hootpr/patch-{self._patches}.diff"
        wrote = self._sb.exec(
            [
                "bash",
                "-c",
                'mkdir -p -- "$(dirname -- "$2")" && printf %s "$1" > "$2"',
                "hootpr-patch",
                patch,
                target,
            ],
            timeout_s=10,
            max_output_kb=4,
        )
        if not wrote.ok:
            return "error: could not stage the patch"
        base = ["git", "apply", "--recount", "--whitespace=nowarn"]
        check = self._sb.exec([*base, "--check", target], timeout_s=30, max_output_kb=8)
        if not check.ok:
            return (
                "error: patch does not apply (fix the context lines or use write_file):\n"
                + check.stderr.strip()[:1500]
            )
        r = self._sb.exec([*base, target], timeout_s=30, max_output_kb=8)
        if not r.ok:
            return f"error: {r.stderr.strip()[:1500]}"
        stat = self._sb.exec(
            ["bash", "-c", f"git apply --numstat {shlex.quote(target)}"],
            timeout_s=10,
            max_output_kb=8,
        )
        return "ok: patch applied\n" + stat.stdout.strip()[:1000]
