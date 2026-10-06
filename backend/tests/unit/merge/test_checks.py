from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.config.schema import HootPRConfig
from app.llm.types import LLMResult, StructuredOutputError, TraceContext, Usage
from app.merge.checks import (
    END,
    START,
    CheckResult,
    any_blocking,
    docstring_check,
    heuristic_description,
    heuristic_title,
    issue_check,
    llm_checks,
    mark_ignored,
    render_pre_merge,
    replace_section,
)
from app.merge.docstrings import DocstringCoverage
from app.merge.issue_refs import IssueRef
from app.merge.linked_issues import LinkedIssue, render_linked_issues
from app.merge.schemas import CheckVerdict, PreMergeVerdicts
from app.platforms.issues import Issue

TRACE = TraceContext()


class StubLLM:
    def __init__(self, parsed: BaseModel | None = None, fail: bool = False) -> None:
        self.parsed, self.fail = parsed, fail
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, role: str, messages: list[dict[str, Any]], **kw: Any) -> LLMResult:
        self.calls.append(messages)
        if self.fail:
            raise StructuredOutputError("bad json")
        return LLMResult(None, self.parsed, [], Usage(1, 0, 1), Decimal(0), "m", None, 1)


def cfg(**pm: Any) -> HootPRConfig:
    return HootPRConfig.model_validate({"reviews": {"pre_merge_checks": pm}})


def test_heuristics() -> None:
    assert heuristic_title("WIP")[0] == "failed"
    assert heuristic_title("feature/login-page")[0] == "failed"
    assert heuristic_title("Add rate limiting to the login endpoint")[0] == "passed"
    assert heuristic_description("## Summary\n- [ ] tests\n<!-- fill me -->")[0] == "failed"
    assert heuristic_description("Adds a per-IP limiter because brute force attempts spiked.")[
        0
    ] == ("passed")


def test_llm_checks_uses_verdicts_and_custom() -> None:
    c = cfg(
        title={"mode": "error"},
        custom_checks=[{"name": "No TODOs", "mode": "error", "instructions": "No TODO added."}],
    )
    llm = StubLLM(
        PreMergeVerdicts(
            checks=[
                CheckVerdict(name="Title check", status="passed", explanation="Clear."),
                CheckVerdict(name="no todos", status="failed", explanation="TODO in a.py."),
            ]
        )
    )
    out = llm_checks(llm, c, "Add x", "body", None, [], trace=TRACE, host=None)
    by = {r.name: r for r in out}
    assert by["Title check"].status == "passed"
    assert by["Description check"].mode == "warning"  # default mode, missing verdict -> heuristic
    assert by["No TODOs"].status == "failed" and by["No TODOs"].blocking
    assert any_blocking(out)


def test_llm_checks_fallback_and_off() -> None:
    c = cfg(title={"mode": "off"}, custom_checks=[{"name": "X", "instructions": "y"}])
    out = llm_checks(StubLLM(fail=True), c, "t", "", None, [], trace=TRACE, host=None)
    assert [(r.name, r.status) for r in out] == [
        ("Description check", "failed"),
        ("X", "inconclusive"),
    ]
    none = cfg(title={"mode": "off"}, description={"mode": "off"})
    llm = StubLLM()
    assert llm_checks(llm, none, "t", "", None, [], trace=TRACE, host=None) == []
    assert llm.calls == []


def test_docstring_check_threshold() -> None:
    c = cfg(docstrings={"mode": "error", "threshold": 80})
    failed = docstring_check(c, DocstringCoverage(4, 1, ("a.py: f",)))
    assert failed is not None and failed.status == "failed" and "25.00%" in failed.explanation
    ok = docstring_check(c, DocstringCoverage(5, 4))
    assert ok is not None and ok.status == "passed"
    assert docstring_check(cfg(), DocstringCoverage(1, 0)) is None  # default mode off
    unknown = docstring_check(c, None)
    assert unknown is not None and unknown.status == "inconclusive"


def _issue(n: int) -> Issue:
    return Issue(n, f"Issue {n}", "do it", "open", "u", (), f"https://x/{n}", "o/r")


def test_issue_check() -> None:
    c = cfg()
    none = issue_check(c, [])
    assert none is not None and none.status == "inconclusive"
    a = LinkedIssue(IssueRef(None, 1), "#1", "o/r", _issue(1), overall="addressed")
    b = LinkedIssue(IssueRef(None, 2), "#2", "o/r", _issue(2), overall="partially")
    res = issue_check(c, [a])
    assert res is not None and res.status == "passed"
    res = issue_check(c, [a, b])
    assert res is not None and res.status == "failed" and "#2" in res.explanation
    assert "## Assessment against linked issues" in render_linked_issues([a, b])


def test_render_ignore_and_replace() -> None:
    results = [
        CheckResult("title", "Title check", "error", "failed", "Too vague | short"),
        CheckResult("description", "Description check", "warning", "passed", "Good."),
    ]
    section = render_pre_merge(results, "@hootpr")
    assert section.startswith(START) and section.endswith(END)
    assert "❌ Error" in section and "Too vague \\| short" in section
    assert "@hootpr ignore pre-merge checks" in section
    ignored = mark_ignored(results, "alice")
    assert not any_blocking(ignored)
    new = render_pre_merge(ignored, "@hootpr")
    assert "Ignored by @alice" in new and "CAUTION" not in new
    walkthrough = f"head\n{section}\ntail"
    assert replace_section(walkthrough, new) == f"head\n{new}\ntail"
    assert replace_section("no section", new) is None
    assert render_pre_merge([]) == ""
