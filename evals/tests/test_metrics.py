from decimal import Decimal

from hootpr_evals.case import ExpectedIssue
from hootpr_evals.matching import CaseMatch, ReviewFinding
from hootpr_evals.metrics import CaseResult, compute_metrics


def res(
    cid: str,
    kind: str,
    n_find: int,
    matched: list[tuple[int, str]],
    fps: list[int],
    missed: list[str],
    cats: list[str] | None = None,
    **kw: object,
) -> CaseResult:
    findings = [
        ReviewFinding("a.py", None, i + 1, (cats or ["security"] * n_find)[i], "major", "t", "b", 0.9)
        for i in range(n_find)
    ]
    expected = [
        ExpectedIssue(id=i, path="a.py", line_range=(1, 1), category="security", severity="major", description="d")
        for _, i in matched
    ] + [
        ExpectedIssue(id=i, path="a.py", line_range=(1, 1), category="bug", severity="major", description="d")
        for i in missed
    ]
    base: dict[str, object] = dict(
        case_id=cid,
        language="python",
        kind=kind,
        expected=expected,
        findings=findings,
        match=CaseMatch(matched, fps, missed),
        inline_count=n_find,
        input_tokens=1000,
        cached_tokens=0,
        output_tokens=100,
        cost_usd=Decimal("0.01"),
        latency_s=2.0,
        llm_calls=5,
    )
    base.update(kw)
    return CaseResult(**base)  # type: ignore[arg-type]


def test_metrics() -> None:
    results = [
        res("c1", "injected", 2, [(0, "i1")], [1], []),  # 1 TP, 1 FP
        res("c2", "injected", 1, [(0, "i2")], [], ["i3"]),  # 1 TP, 1 FN (bug)
        res("c3", "clean", 1, [], [0], [], cats=["style"]),  # clean PR with a FP
        res("c4", "clean", 0, [], [], [], latency_s=6.0),
    ]
    m = compute_metrics(results)
    assert (m.tp, m.fp, m.fn) == (2, 2, 1)
    assert m.precision == 0.5 and m.recall is not None and round(m.recall, 3) == 0.667
    assert m.f1 is not None and round(m.f1, 3) == 0.571
    assert m.per_category["security"].recall == 1.0 and m.per_category["bug"].recall == 0.0
    sec_p = m.per_category["security"].precision
    assert sec_p is not None and round(sec_p, 3) == 0.667
    assert m.per_category["style"].precision == 0.0 and m.per_category["style"].recall is None
    assert m.clean_fp_rate == 0.5 and m.clean_findings_mean == 0.5
    assert m.comments_per_pr == 1.0 and m.cost_per_pr == Decimal("0.01")
    assert m.latency_p50_s == 2.0 and m.latency_mean_s == 3.0 and m.cases == 4 and m.errors == 0


def test_errored_cases_count_all_issues_as_missed_and_no_findings_gives_none_precision() -> None:
    m = compute_metrics([res("c1", "injected", 0, [], [], ["i1"], error="ProviderUnavailable: down")])
    assert m.errors == 1 and m.precision is None and m.recall == 0.0 and m.f1 == 0.0


def test_empty_run() -> None:
    m = compute_metrics([])
    assert m.cases == 0 and m.precision is None and m.recall is None and m.f1 is None
    assert m.clean_fp_rate is None and m.cost_per_pr is None


def test_perfect_run_f1() -> None:
    m = compute_metrics([res("c1", "injected", 1, [(0, "i1")], [], [])])
    assert m.precision == 1.0 and m.recall == 1.0 and m.f1 == 1.0


def test_all_false_positives_gives_zero_f1() -> None:
    m = compute_metrics([res("c1", "injected", 1, [], [0], ["i1"])])
    assert m.precision == 0.0 and m.recall == 0.0 and m.f1 == 0.0
