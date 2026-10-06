from app.platforms.diff import build_file_diff
from app.review.anchoring import DiffIndex, fingerprint
from app.review.findings import Candidate, rank_key
from app.review.judge_rules import deterministic_judge, suggestion_applies

PATCH = (
    "@@ -1,3 +1,4 @@\n a = 1\n-b = 2\n+b = 3\n+c = 4\n d = 5\n"
    "@@ -20,2 +21,3 @@\n x = 1\n+y = 2\n z = 3\n"
)
DIFF = DiffIndex([build_file_diff("m.py", PATCH, "modified")])


def cand(**kw: object) -> Candidate:
    base: dict[str, object] = dict(
        path="m.py",
        start_line=None,
        end_line=2,
        severity="major",
        category="bug",
        title="t",
        body="b",
        confidence=0.9,
    )
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


def test_candidate_helpers() -> None:
    c = cand(start_line=None, end_line=7)
    assert c.start == 7 and c.alive
    c.drop("x")
    assert (c.verdict, c.reason, c.alive) == ("drop", "x", False)
    assert rank_key(cand(severity="critical", confidence=0.5)) < rank_key(cand(severity="major"))


def test_finding_outside_changed_hunk_is_dropped() -> None:
    far = cand(end_line=12)
    other = cand(path="nope.py")
    assert deterministic_judge([far, other], DIFF, frozenset()) == []
    assert (far.verdict, far.reason) == ("drop", "outside_changed_hunk")
    assert (other.verdict, other.reason) == ("drop", "path_not_in_diff")


def test_security_finding_near_a_hunk_is_reanchored() -> None:
    sec = cand(category="security", end_line=12, suggestion="x")
    assert deterministic_judge([sec], DIFF, frozenset()) == [sec]
    assert sec.end_line == 3 and sec.start_line is None and sec.suggestion is None
    assert sec.anchor_note == "re-anchored from line 12"


def test_range_across_hunks_is_dropped() -> None:
    c = cand(start_line=2, end_line=22)
    deterministic_judge([c], DIFF, frozenset())
    assert c.reason == "outside_changed_hunk"


def test_single_line_range_is_normalized() -> None:
    c = cand(start_line=3, end_line=3)
    assert deterministic_judge([c], DIFF, frozenset()) == [c]
    assert c.start_line is None and c.fingerprint == fingerprint("m.py", "c = 4", "bug")


def test_suggestion_must_apply_cleanly() -> None:
    ok = cand(start_line=2, end_line=3, suggestion="b = 3\nc = 5")
    noop = cand(end_line=22, suggestion="y = 2", category="style")
    assert deterministic_judge([ok, noop], DIFF, frozenset()) == [ok]
    assert noop.reason == "suggestion_does_not_apply"
    assert not suggestion_applies(DIFF, "m.py", 2, 3, "x" * 6000)


def test_previously_posted_fingerprint_is_dropped() -> None:
    seen = fingerprint("m.py", "b = 3", "bug")
    c = cand()
    assert deterministic_judge([c], DIFF, frozenset({seen})) == []
    assert c.reason == "already_posted"


def test_overlapping_same_category_findings_merge_into_the_strongest() -> None:
    weak = cand(start_line=2, end_line=3, severity="minor", title="weak", evidence=["e1"])
    strong = cand(end_line=3, severity="critical", title="strong", evidence=["e2"])
    other_cat = cand(end_line=3, category="performance", title="perf")
    out = deterministic_judge([weak, strong, other_cat], DIFF, frozenset())
    assert out == [strong, other_cat]
    assert weak.verdict == "merge" and weak.reason == "merged into: strong"
    assert strong.evidence == ["e2", "e1"]
