from app.config.schema import HootPRConfig
from app.review.tool_results import TOOL_NAMES, enabled_tools, parse_tool_output

OUT = {
    "version": 1,
    "runs": [
        {
            "tool": "ruff",
            "status": "ok",
            "duration_ms": 10,
            "findings_count": 2,
            "stderr_excerpt": "",
        },
        {
            "tool": "semgrep",
            "status": "timeout",
            "duration_ms": 60000,
            "findings_count": 0,
            "stderr_excerpt": "killed",
        },
    ],
    "findings": [
        {
            "tool": "ruff",
            "rule_id": "F401",
            "path": "a.py",
            "line": 1,
            "end_line": 1,
            "severity": "warning",
            "message": "unused import",
        },
        {
            "tool": "ruff",
            "rule_id": "S608",
            "path": "a.py",
            "line": 5,
            "end_line": 5,
            "severity": "error",
            "message": "SQL injection",
        },
        {"tool": "ruff", "path": "broken"},
    ],
}


def test_parse_and_query() -> None:
    r = parse_tool_output(OUT)
    assert [x.tool for x in r.runs] == ["ruff", "semgrep"]
    assert r.runs[1].status == "timeout"
    assert len(r.findings) == 2
    assert r.counts_by_path() == {"a.py": 2}
    assert r.for_path("a.py")[1].render() == "a.py:5 [ruff:S608] error: SQL injection"


def test_unknown_severity_is_normalized_to_warning() -> None:
    r = parse_tool_output(
        {
            "version": 1,
            "findings": [{"tool": "x", "path": "a", "line": 2, "severity": "HIGH", "message": "m"}],
        }
    )
    assert r.findings[0].severity == "warning" and r.findings[0].end_line == 2


def test_garbage_yields_empty_results() -> None:
    assert parse_tool_output({"version": 9}).findings == ()
    assert parse_tool_output(None).runs == ()
    assert parse_tool_output({"version": 1, "runs": ["x"], "findings": "y"}).runs == ()


def test_enabled_tools_follow_config() -> None:
    assert enabled_tools(HootPRConfig()) == list(TOOL_NAMES)
    cfg = HootPRConfig.model_validate({"reviews": {"tools": {"eslint": {"enabled": False}}}})
    assert "eslint" not in enabled_tools(cfg) and len(TOOL_NAMES) == 15
