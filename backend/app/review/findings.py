"""Review finding candidates flowing from agents through the judge to posting (spec §5, §7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

Severity = Literal["critical", "major", "minor", "nitpick"]
Category = Literal["bug", "security", "performance", "maintainability", "style", "docs", "test"]
Verdict = Literal["keep", "drop", "merge"]
Placement = Literal["inline", "additional", "unposted", "none"]
SEVERITY_RANK: dict[str, int] = {"critical": 0, "major": 1, "minor": 2, "nitpick": 3}


@dataclass
class Candidate:
    path: str
    start_line: int | None
    end_line: int
    severity: Severity
    category: Category
    title: str
    body: str
    suggestion: str | None = None
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = "llm"
    task_id: UUID | None = None
    verdict: Verdict | None = None
    reason: str | None = None
    fingerprint: str = ""
    anchor_note: str | None = None
    placement: Placement = "none"
    posted: bool = False
    provider_comment_id: str | None = None
    also_applies: list[tuple[int, int]] = field(default_factory=list)  # merged duplicates' lines

    def drop(self, reason: str) -> None:
        self.verdict, self.reason = "drop", reason

    @property
    def start(self) -> int:
        """First line of the range (``end_line`` for single-line findings)."""
        return self.start_line or self.end_line

    @property
    def alive(self) -> bool:
        return self.verdict not in ("drop", "merge")


def rank_key(c: Candidate) -> tuple[int, float]:
    """Sort key: severity first, then higher confidence first."""
    return (SEVERITY_RANK.get(c.severity, 9), -c.confidence)
