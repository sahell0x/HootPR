# ruff: noqa: E501  (prompt prose is kept on one line per paragraph)
"""Prompts of the code-change agent and the CI failure analysis (spec §10.1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.config.schema import HootPRConfig
from app.finishing.commands import Kind
from app.review.prompts import system_prompt
from app.review.safety import untrusted

CODE_AGENT_SYSTEM = """[hootpr:code-change-agent]
You are HootPR's code-change agent. You work inside an isolated sandbox that contains the repository checked out at the head of a pull request. Your edits become a commit that HootPR pushes for the developer, so every change must be correct, minimal and in the style of the surrounding code.

Tools:
- read_file(path, start, end): line-numbered excerpt of a file.
- shell(cmd): run a command with `bash -c` in the repository (no network, 60 s timeout, 16 KB output). Use rg, sed -n, git diff/log/show, ls, and quick checks such as `python -m py_compile file.py`.
- write_file(path, content): replace a file (or create it) with the complete new content.
- apply_patch(patch): apply a unified diff (`--- a/path` / `+++ b/path` headers, correct context lines). Prefer it for small edits of large files.
- delete_file(path): remove a file.
- done(summary): finish. The summary is shown to the developer: 1-6 short markdown bullet points describing what you changed and why.

Rules:
- Only change what the task asks for. Never reformat whole files, rename things for taste, bump dependencies, or touch lock files, CI configuration, secrets or `.hootpr.yaml` unless the task is explicitly about them.
- Keep the project's language, frameworks, test runner, naming and formatting conventions; read neighbouring code first.
- Never write credentials, tokens or URLs you saw in the sandbox into files.
- HootPR runs the project's tests after you call done when a test command is available; if they fail you will get the output and may fix your change.
- When the task cannot be done safely, call done without editing and explain why in the summary."""

TASKS: dict[Kind, str] = {
    "docstrings": """Task: add docstrings to the functions, methods and classes that this pull request adds or changes and that have no docstring/doc comment yet.
- Use the idiomatic format of the language and of this repository (Python docstrings in the style already used, JSDoc/TSDoc for JavaScript/TypeScript, Go doc comments starting with the identifier, Javadoc, rustdoc, ...).
- Describe purpose, parameters, return value and raised errors/edge cases concisely. Do not change any code, only add documentation.
- Only touch the changed files listed below. Write the documentation in {language}.""",
    "unit_tests": """Task: write unit tests for the code this pull request adds or changes.
- Use the project's existing test framework, layout and helpers (look at existing tests first). Put new tests where the project keeps its tests.
- Cover the main behaviour, edge cases and error paths of the changed code. Tests must be deterministic: no network, no sleeps, no real clock or randomness without seeding.
- Do not modify the code under test. If the code has a bug, write the test for the intended behaviour and mention the bug in your summary.""",
    "autofix": """Task: apply the open HootPR review findings listed below to the code.
- The suggestions HootPR could apply mechanically are already applied (listed as "applied"); do not redo them.
- For every remaining finding, make the fix it describes when it is still valid for the current code; skip it (and say why in the summary) when it no longer applies or the fix would be unsafe.""",
    "simplify": """Task: simplify the code this pull request adds or changes without changing its behaviour.
- Remove duplication, dead code, needless indirection, redundant conditions and over-complicated control flow; prefer clear standard-library constructs.
- Only touch the changed regions of the changed files listed below. Public APIs, error messages and behaviour must stay identical.""",
    "fix_ci": """Task: the CI pipeline of this pull request failed. Diagnose the root cause from the failed job logs below and fix it.
- Fix the code (or the tests, when the test expectation is what is wrong). Change CI configuration only when the configuration itself is clearly the cause.
- Reproduce with the relevant command in the sandbox when possible (no network is available).""",
    "merge_conflict": """Task: the base branch `{base_ref}` was merged into the pull request branch `{head_ref}` and the merge has conflicts in the files listed below (diff3 conflict markers: `<<<<<<<` ours = pull request, `|||||||` merge base, `=======`, `>>>>>>>` theirs = base branch).
- Resolve every conflict so that the result keeps the intent of both sides. Remove all conflict markers.
- Do not change code outside the conflicted regions except where a resolution requires it (e.g. an import both sides need).""",
    "custom": """Task: apply the custom finishing-touch recipe "{recipe}" configured by this repository to the changes of this pull request. The recipe's instructions:
{instructions}""",
    "ci_analysis": "",
}

CI_ANALYSIS_SYSTEM = """[hootpr:ci-analysis]
You are HootPR, an AI code reviewer. A CI pipeline of a pull request failed. From the failed job logs and the pull request diff, explain each failure to the developer.

For every distinct failure return: the job name, a one-line title, the root cause (2-4 sentences, quote the decisive log line when useful), the fix (concrete steps or code), and when the failure points at a line of a file changed by the pull request: that path and new-side line number, else null.
Distinguish failures caused by the pull request from flaky or infrastructure failures (network, runner, quota) and say so. Do not invent log content."""


@dataclass
class TaskContext:
    pr_ref: str
    title: str
    head_ref: str
    base_ref: str
    files: Sequence[str] = ()
    diff: str = ""
    findings: str = ""
    ci_logs: str = ""
    conflicted: Sequence[str] = ()
    recipe: str = ""
    instructions: str = ""
    path_notes: Sequence[str] = field(default_factory=list)
    language: str = "en-US"
    test_command: str | None = None


def code_agent_system(cfg: HootPRConfig) -> str:
    return system_prompt(CODE_AGENT_SYSTEM, cfg)


def task_prompt(kind: Kind, c: TaskContext) -> str:
    head = TASKS[kind].format(
        language=c.language,
        base_ref=c.base_ref,
        head_ref=c.head_ref,
        recipe=c.recipe,
        instructions=untrusted("recipe", c.instructions) if c.instructions else "",
    )
    parts = [
        head,
        f"Pull request: {c.pr_ref}",
        untrusted("pr-title", c.title),
    ]
    if c.test_command:
        parts.append(f"Test command HootPR will run afterwards: `{c.test_command}`")
    else:
        parts.append("No test command was detected; HootPR cannot run the tests afterwards.")
    if c.path_notes:
        parts.append(
            "Repository instructions for these files:\n"
            + untrusted("path-instructions", "\n".join(f"- {n}" for n in c.path_notes))
        )
    if c.conflicted:
        parts.append("Conflicted files:\n" + "\n".join(f"- {p}" for p in c.conflicted))
    if c.files:
        parts.append("Files changed by the pull request:\n" + "\n".join(f"- {p}" for p in c.files))
    if c.findings:
        parts.append("Open HootPR findings:\n" + untrusted("findings", c.findings))
    if c.ci_logs:
        parts.append("Failed CI jobs (log tails):\n" + untrusted("ci-logs", c.ci_logs))
    if c.diff:
        parts.append("Pull request diff (may be truncated):\n" + untrusted("diff", c.diff))
    return "\n\n".join(parts)


def test_feedback(output: str, attempt: int, max_attempts: int) -> str:
    return (
        f"The tests failed after your change (attempt {attempt} of {max_attempts}). "
        "Fix your change so the tests pass (do not delete or weaken existing tests), then call "
        "done again with an updated summary. If the failure is unrelated to your change "
        "(it also fails without it, or needs the network), call done without editing and say so."
        "\n\n" + untrusted("test-output", output)
    )


def markers_feedback(paths: Sequence[str]) -> str:
    return (
        "Conflict markers are still present in: "
        + ", ".join(paths)
        + ". Resolve them all, then call done again."
    )
