from decimal import Decimal
from typing import Any

from app.llm.types import LLMResult, StructuredOutputError, Usage

from hootpr_evals.case import ExpectedIssue
from hootpr_evals.matching import (
    LLMMatcher,
    LocationMatcher,
    MatchVerdict,
    ReviewFinding,
    location_match,
    match_case,
)


def issue(iid: str, start: int, end: int, path: str = "a.py") -> ExpectedIssue:
    return ExpectedIssue(
        id=iid, path=path, line_range=(start, end), category="security", severity="major", description="d"
    )


def f(start: int | None, end: int, path: str = "a.py", conf: float = 0.9) -> ReviewFinding:
    return ReviewFinding(path, start, end, "security", "major", "t", "b", conf)


def test_location_slack() -> None:
    assert location_match(f(None, 13), issue("x", 9, 10))  # 13 is within 10 + 3
    assert not location_match(f(None, 14), issue("x", 9, 10))
    assert location_match(f(2, 6), issue("x", 9, 10))
    assert not location_match(f(1, 5), issue("x", 9, 10))
    assert not location_match(f(None, 9, path="b.py"), issue("x", 9, 10))


def test_greedy_one_to_one_and_duplicates_are_false_positives() -> None:
    m = match_case(
        [f(None, 9, conf=0.5), f(None, 10, conf=0.9), f(None, 40)],
        [issue("a", 9, 10), issue("b", 30, 30)],
        LocationMatcher(),
    )
    assert m.matched == [(1, "a")]  # the most confident finding wins the issue
    assert sorted(m.false_positives) == [0, 2] and m.missed == ["b"]


class Never:
    def same(self, finding: ReviewFinding, iss: ExpectedIssue) -> bool:
        return False


def test_matcher_veto() -> None:
    m = match_case([f(None, 9)], [issue("a", 9, 9)], Never())
    assert m.matched == [] and m.false_positives == [0] and m.missed == ["a"]


class ScriptedLLM:
    def __init__(self, answer: MatchVerdict | Exception) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def complete(self, role: str, messages: list[dict[str, Any]], **kw: Any) -> LLMResult:
        self.calls.append({"role": role, "messages": messages, **kw})
        if isinstance(self.answer, Exception):
            raise self.answer
        return LLMResult(None, self.answer, [], Usage(10, 0, 2), Decimal("0"), "fake", "json_schema", 1)


def test_llm_matcher_uses_cheap_role_and_strict_model() -> None:
    llm = ScriptedLLM(MatchVerdict(same_issue=True, reason="both describe SQLi"))
    assert LLMMatcher(llm).same(f(None, 9), issue("a", 9, 9))
    call = llm.calls[0]
    assert call["role"] == "cheap" and call["response_model"] is MatchVerdict
    assert "### ISSUE" in call["messages"][1]["content"] and "### FINDING" in call["messages"][1]["content"]
    assert not LLMMatcher(ScriptedLLM(MatchVerdict(same_issue=False, reason="no"))).same(f(None, 9), issue("a", 9, 9))


def test_llm_matcher_treats_unparseable_output_as_no_match() -> None:
    assert not LLMMatcher(ScriptedLLM(StructuredOutputError("bad json"))).same(f(None, 9), issue("a", 9, 9))


def test_llm_matcher_is_only_asked_for_location_candidates() -> None:
    llm = ScriptedLLM(MatchVerdict(same_issue=True, reason="r"))
    match_case([f(None, 50)], [issue("a", 9, 9)], LLMMatcher(llm))
    assert llm.calls == []


def test_location_match_prefers_the_issue_the_finding_actually_overlaps() -> None:
    from hootpr_evals.case import ExpectedIssue as EI
    from hootpr_evals.matching import LocationMatcher as LM
    from hootpr_evals.matching import ReviewFinding as RF
    from hootpr_evals.matching import match_case as mc

    near = EI(id="near", path="a.py", line_range=(8, 12), category="style", severity="nitpick", description="d")
    exact = EI(id="exact", path="a.py", line_range=(6, 7), category="bug", severity="major", description="d")
    finding = RF("a.py", 6, 7, "bug", "major", "t", "b", 0.9)
    m = mc([finding], [near, exact], LM())
    assert m.matched == [(0, "exact")] and m.missed == ["near"]
