from app.llm.structured import strict_json_schema
from app.review.schemas import (
    CandidateFinding,
    JudgeBatch,
    ReviewPlan,
    SinglePassFindings,
    TriageResult,
    WalkthroughSummary,
)


def test_all_llm_models_produce_strict_schemas_without_numeric_constraints() -> None:
    for model in (TriageResult, ReviewPlan, SinglePassFindings, JudgeBatch, WalkthroughSummary):
        schema = strict_json_schema(model)
        text = str(schema)
        assert "minimum" not in text and "maxLength" not in text
        assert schema["additionalProperties"] is False


def test_candidate_conversion_clamps_and_normalizes() -> None:
    f = CandidateFinding(
        path="./src/a.py",
        start_line=0,
        end_line=0,
        severity="major",
        category="bug",
        title=" t ",
        body="b",
        suggestion=None,
        evidence=[str(i) for i in range(20)],
        confidence=3.0,
    )
    c = f.to_candidate()
    assert c.path == "src/a.py" and c.start_line is None and c.end_line == 1
    assert c.confidence == 1.0 and len(c.evidence) == 10 and c.title == "t"


def test_candidate_conversion_orders_inverted_range() -> None:
    f = CandidateFinding(
        path="a.py",
        start_line=9,
        end_line=4,
        severity="minor",
        category="bug",
        title="t",
        body="b",
        suggestion="",
        evidence=[],
        confidence=-1,
    )
    c = f.to_candidate()
    assert (c.start_line, c.end_line) == (4, 9)
    assert c.confidence == 0.0 and c.suggestion is None
