"""Normalized static-analysis results (contract C1 `run_tools.py`, spec §7.3)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.config.schema import HootPRConfig, Toggle

TOOL_NAMES: tuple[str, ...] = (
    "semgrep",
    "gitleaks",
    "trivy",
    "checkov",
    "ruff",
    "eslint",
    "shellcheck",
    "hadolint",
    "actionlint",
    "yamllint",
    "markdownlint",
    "golangci_lint",
    "rubocop",
    "phpstan",
    "swiftlint",
)
_SEVERITIES = ("error", "warning", "info")
STDERR_MAX = 2000
MESSAGE_MAX = 500


@dataclass(frozen=True)
class StaticFinding:
    tool: str
    rule_id: str
    path: str
    line: int
    end_line: int
    severity: str
    message: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}"
        return f"{where} [{self.tool}:{self.rule_id}] {self.severity}: {self.message}"


@dataclass(frozen=True)
class ToolRunRecord:
    tool: str
    status: str
    duration_ms: int | None
    findings_count: int
    stderr_excerpt: str


@dataclass(frozen=True)
class ToolResults:
    runs: tuple[ToolRunRecord, ...] = ()
    findings: tuple[StaticFinding, ...] = ()

    def for_path(self, path: str) -> list[StaticFinding]:
        return [f for f in self.findings if f.path == path]

    def counts_by_path(self) -> dict[str, int]:
        return dict(Counter(f.path for f in self.findings))


def _dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def parse_tool_output(data: object) -> ToolResults:
    """Parse a ``run_tools.py`` document; bad entries are skipped, unknown versions ignored."""
    if not isinstance(data, dict) or data.get("version") != 1:
        return ToolResults()
    runs: list[ToolRunRecord] = []
    for r in _dicts(data.get("runs")):
        try:
            runs.append(
                ToolRunRecord(
                    str(r["tool"]),
                    str(r["status"]),
                    int(r["duration_ms"]) if r.get("duration_ms") is not None else None,
                    int(r.get("findings_count") or 0),
                    str(r.get("stderr_excerpt") or "")[:STDERR_MAX],
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    findings: list[StaticFinding] = []
    for f in _dicts(data.get("findings")):
        try:
            line = int(f["line"])
            sev = str(f.get("severity") or "warning").lower()
            findings.append(
                StaticFinding(
                    str(f["tool"]),
                    str(f.get("rule_id") or ""),
                    str(f["path"]),
                    line,
                    int(f.get("end_line") or line),
                    sev if sev in _SEVERITIES else "warning",
                    str(f.get("message") or "")[:MESSAGE_MAX],
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return ToolResults(tuple(runs), tuple(findings))


def enabled_tools(cfg: HootPRConfig) -> list[str]:
    """Tool names (config spelling) enabled by ``reviews.tools.<name>.enabled``."""
    return [name for name in TOOL_NAMES if _toggle(cfg, name).enabled]


def _toggle(cfg: HootPRConfig, name: str) -> Toggle:
    toggle = getattr(cfg.reviews.tools, name)
    if not isinstance(toggle, Toggle):  # pragma: no cover - schema guarantees it
        raise TypeError(f"reviews.tools.{name} is not a toggle")
    return toggle
