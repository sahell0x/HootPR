from app.chat.commands import parse_comment
from app.chat.identity import BotIdentity
from app.config.schema import HootPRConfig
from app.llm.types import TraceContext
from app.merge.create_issue import request_text
from app.merge.schemas import SlopVerdict
from app.merge.slop import detect_slop, render_slop_note, slop_signals
from app.platforms.diff import build_file_diff
from app.platforms.github.webhooks import parse_event as gh_parse
from app.platforms.gitlab.webhooks import parse_event as gl_parse
from tests.unit.merge.test_checks import StubLLM

ID = BotIdentity(frozenset({"hootpr[bot]"}), frozenset({"hootpr", "hootpr[bot]"}))


def _ws_file(path: str):  # type: ignore[no-untyped-def]
    patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x  =  1\n".replace("x  =  1", "  x = 1")
    return build_file_diff(path, patch, "modified", None)


def test_slop_signals() -> None:
    assert slop_signals("Fixes the parser crash on empty input.", []) == []
    sig = slop_signals("This pull request introduces several improvements.", [])
    assert len(sig) == 1 and "boilerplate" in sig[0]
    churn = slop_signals("", [_ws_file(f"f{i}.py") for i in range(6)])
    assert any("formatting" in s for s in churn)


def test_detect_slop_only_asks_model_with_signals() -> None:
    cfg = HootPRConfig()
    llm = StubLLM(SlopVerdict(is_slop=True, confidence=0.9, reasons=["generic text"]))
    clean = detect_slop(llm, cfg, "t", "Real description.", [], trace=TraceContext(), host=None)
    assert not clean.flagged and llm.calls == []
    res = detect_slop(
        llm, cfg, "t", "As an AI, I improved things.", [], trace=TraceContext(), host=None
    )
    assert res.flagged and "generic text" in render_slop_note(res)
    low = StubLLM(SlopVerdict(is_slop=True, confidence=0.3, reasons=[]))
    assert not detect_slop(low, cfg, "t", "As an AI", [], trace=TraceContext(), host=None).flagged


def test_new_commands_parse() -> None:
    p = parse_comment("@hootpr ignore pre-merge checks", ID)
    assert p.command == "ignore_pre_merge"
    p = parse_comment("@hootpr create issue: flaky test in CI\nmore details", ID)
    assert p.command == "create_issue"
    assert request_text(p.text).startswith("flaky test in CI")
    assert parse_comment("@hootpr ignore", ID).command == "ignore"


def test_issue_opened_webhooks() -> None:
    repo = {"id": 1, "full_name": "o/r", "private": False}
    gh = gh_parse(
        "issues",
        {
            "action": "opened",
            "repository": repo,
            "issue": {"number": 5, "title": "Bug", "body": "b", "user": {"login": "u"}},
            "installation": {"id": 9},
        },
        "d1",
    )
    assert gh is not None and gh.kind == "issue_opened" and gh.number == 5
    project = {"id": 2, "path_with_namespace": "g/p", "visibility_level": 20}
    base = {"object_kind": "issue", "project": project, "user": {"username": "u"}}
    gl = gl_parse(
        "Issue Hook",
        {**base, "object_attributes": {"action": "open", "iid": 3, "title": "T"}},
        "d2",
    )
    assert gl is not None and gl.kind == "issue_opened" and gl.number == 3
    conf = {"action": "open", "iid": 3, "title": "T", "confidential": True}
    assert gl_parse("Issue Hook", {**base, "object_attributes": conf}, "d3") is None
