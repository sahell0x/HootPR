"""Free-form chat agent (spec §8, phase-3 R10).

A bounded tool loop: at most ``CHAT_AGENT_MAX_STEPS`` investigative calls (``read_file``, and
``shell`` on the docker sandbox), at most ``LEARNINGS_MAX_PER_CHAT`` ``add_learning`` calls, and
a forced final answer without tools when a cap is hit. All PR/comment text is wrapped with
``untrusted``; the caller hardens the answer before posting it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.chat.prompts import BUDGET_NOTE, CHAT_SYSTEM, TOKEN_CAP_NOTE
from app.config.schema import HootPRConfig
from app.knowledge.base import LearningHit, render_learnings_block
from app.knowledge.learnings import AddedLearning
from app.knowledge.text import InvalidLearning
from app.llm.types import Message, ToolSpec, ToolsUnsupported, TraceContext
from app.review.agent import TOOL_SPECS, Toolbox, estimate_tokens
from app.review.llm import LLMLike
from app.review.prompts import system_prompt
from app.review.safety import untrusted
from app.settings import Settings

THREAD_MAX_CHARS = 6000
WALKTHROUGH_MAX_CHARS = 4000
PR_BODY_MAX_CHARS = 2000
QUESTION_MAX_CHARS = 8000
MAX_OUTPUT_TOKENS = 2000
FALLBACK_ANSWER = "I could not find an answer to that — could you add more detail?"
INVESTIGATIVE = frozenset({"shell", "read_file"})
AddLearningFn = Callable[[str, Literal["repo", "org"], str | None], AddedLearning]
ADD_LEARNING_SPEC: ToolSpec = {
    "type": "function",
    "function": {
        "name": "add_learning",
        "description": "Record a lasting team preference so future HootPR reviews follow it.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Self-contained preference, at most 1000 characters.",
                },
                "scope": {"type": "string", "enum": ["repo", "org"]},
                "path_glob": {
                    "type": ["string", "null"],
                    "description": "Glob of the files it applies to, or null.",
                },
            },
            "required": ["text", "scope", "path_glob"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class ChatContext:
    author: str
    question: str
    pr_ref: str
    pr_title: str
    pr_body: str
    thread: tuple[tuple[str, str], ...]
    path: str | None
    line: int | None
    diff_hunk: str | None
    finding: str | None
    walkthrough: str
    learnings: tuple[LearningHit, ...]
    request: str | None = None


@dataclass
class ChatOutcome:
    answer: str
    added: list[AddedLearning] = field(default_factory=list)
    steps: int = 0
    stop_reason: str = "answered"  # answered | step_cap | token_cap


def _thread_text(thread: tuple[tuple[str, str], ...]) -> str:
    """The most recent thread messages that fit in ``THREAD_MAX_CHARS``, oldest first."""
    lines: list[str] = []
    used = 0
    for author, body in reversed(thread):
        item = f"@{author}: {body.strip()}"
        if used + len(item) > THREAD_MAX_CHARS:
            break
        lines.append(item)
        used += len(item)
    return "\n\n".join(reversed(lines))


def chat_user_prompt(c: ChatContext) -> str:
    parts = [
        f'<chat pr="{untrusted_attr(c.pr_ref)}">',
        f"Asked by @{untrusted_attr(c.author)}.",
        untrusted("pr", f"{c.pr_title}\n\n{c.pr_body[:PR_BODY_MAX_CHARS]}"),
    ]
    thread = _thread_text(c.thread)
    if thread:
        parts.append("Earlier messages in this thread:\n" + untrusted("thread", thread))
    if c.path:
        # The path comes from the PR author (git paths may hold newlines / tag-like text).
        loc = untrusted_attr(" ".join(c.path.split()))
        parts.append(f"Code location: {loc}" + (f" line {c.line}" if c.line else ""))
    if c.diff_hunk:
        parts.append(untrusted("diff_hunk", c.diff_hunk))
    if c.finding:
        parts.append("HootPR's review comment in this thread:\n" + untrusted("finding", c.finding))
    if c.walkthrough:
        parts.append(
            "HootPR's walkthrough of this pull request:\n"
            + untrusted("walkthrough", c.walkthrough[:WALKTHROUGH_MAX_CHARS])
        )
    block = render_learnings_block(c.learnings)
    if block:
        parts.append(block)
    question = c.question[:QUESTION_MAX_CHARS]
    if c.request:
        parts.append(f"Task: {c.request}")
        if question.strip():
            parts.append("Developer's comment:\n" + untrusted("comment", question))
    else:
        parts.append("Question:\n" + untrusted("comment", question))
    parts.append("</chat>")
    return "\n\n".join(parts)


def untrusted_attr(text: str) -> str:
    """A PR ref / username inside the prompt frame: no quotes, tags or newlines."""
    return "".join(ch for ch in text if ch not in '"<>\n\r')[:200]


def _specs(allow_shell: bool, toolbox: Toolbox | None, learning: bool) -> list[ToolSpec]:
    names = ({"shell", "read_file"} if allow_shell else {"read_file"}) if toolbox else set()
    specs = [s for s in TOOL_SPECS if s["function"]["name"] in names]
    extra = toolbox.extra_specs() if toolbox else []  # phase 7: MCP tools + web_search
    return specs + extra + ([ADD_LEARNING_SPEC] if learning else [])


def _investigative(name: str, toolbox: Toolbox | None) -> bool:
    return name in INVESTIGATIVE or (toolbox is not None and toolbox.handles(name))


def _names(specs: list[ToolSpec]) -> set[str]:
    return {s["function"]["name"] for s in specs}


def _run_tool(
    name: str,
    raw: str,
    offered: set[str],
    toolbox: Toolbox | None,
    add: AddLearningFn | None,
    out: ChatOutcome,
    settings: Settings,
) -> str:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return "error: arguments are not valid JSON"
    if not isinstance(parsed, dict):
        return "error: arguments must be a JSON object"
    args: dict[str, Any] = parsed
    if name == "add_learning":
        if add is None or name not in offered:
            return "rejected: learnings are disabled for this repository"
        if len(out.added) >= settings.learnings_max_per_chat:
            return "rejected: learning limit for one reply reached"
        scope: Literal["repo", "org"] = "org" if args.get("scope") == "org" else "repo"
        glob = args.get("path_glob")
        try:
            added = add(str(args.get("text") or ""), scope, str(glob) if glob else None)
        except InvalidLearning as exc:
            return f"rejected: {exc}"
        out.added.append(added)
        return f"stored learning {added.id}"
    if _investigative(name, toolbox) and toolbox is not None and name in offered:
        if out.steps >= settings.chat_agent_max_steps:
            return BUDGET_NOTE
        out.steps += 1
        return toolbox.call(name, args)
    return f"error: unknown tool {name}"


def _final(llm: LLMLike, msgs: list[Message], trace: TraceContext) -> str:
    res = llm.complete("review", msgs, tools=None, max_output_tokens=MAX_OUTPUT_TOKENS, trace=trace)
    return (res.content or "").strip() or FALLBACK_ANSWER


def run_chat_agent(
    llm: LLMLike,
    c: ChatContext,
    cfg: HootPRConfig,
    settings: Settings,
    *,
    toolbox: Toolbox | None,
    allow_shell: bool,
    add_learning: AddLearningFn | None,
    trace: TraceContext,
) -> ChatOutcome:
    base: list[Message] = [
        {"role": "system", "content": system_prompt(CHAT_SYSTEM, cfg)},
        {"role": "user", "content": chat_user_prompt(c)},
    ]
    msgs = list(base)
    out = ChatOutcome(answer="")
    specs = _specs(allow_shell, toolbox, add_learning is not None)
    if settings.chat_agent_max_steps <= 0:
        specs = [s for s in specs if not _investigative(s["function"]["name"], toolbox)]
    rounds = settings.chat_agent_max_steps + settings.learnings_max_per_chat + 2
    for _ in range(rounds):
        if estimate_tokens(msgs) > settings.chat_max_input_tokens:
            out.stop_reason = "token_cap"
            msgs = [*base, {"role": "user", "content": TOKEN_CAP_NOTE}]
            break
        if out.steps >= settings.chat_agent_max_steps and any(
            _investigative(n, toolbox) for n in _names(specs)
        ):
            out.stop_reason = "step_cap"
            specs = [s for s in specs if not _investigative(s["function"]["name"], toolbox)]
            if not specs:
                break
        if add_learning is not None and len(out.added) >= settings.learnings_max_per_chat:
            specs = [s for s in specs if s["function"]["name"] != "add_learning"]
        try:
            res = llm.complete(
                "review",
                msgs,
                tools=specs or None,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                trace=trace,
            )
        except ToolsUnsupported:
            if not specs:
                raise
            specs = []
            continue
        if not res.tool_calls:
            out.answer = (res.content or "").strip() or FALLBACK_ANSWER
            return out
        offered = _names(specs)
        msgs.append(
            {
                "role": "assistant",
                "content": res.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in res.tool_calls
                ],
            }
        )
        for tc in res.tool_calls:
            result = _run_tool(tc.name, tc.arguments, offered, toolbox, add_learning, out, settings)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    out.answer = _final(llm, msgs, trace)
    return out
