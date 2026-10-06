"""LLM I/O models (plan contract C3). No numeric/length constraints: values are clamped in code so
strict json_schema works on every OpenAI-compatible provider."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.review.findings import Candidate, Category, Severity

Focus = Literal[
    "security",
    "correctness",
    "performance",
    "api-contract",
    "concurrency",
    "error-handling",
    "tests",
    "docs",
]
MAX_EVIDENCE = 10


class FileTriage(BaseModel):
    path: str
    decision: Literal["deep", "light", "skip"]
    summary: str


class TriageResult(BaseModel):
    files: list[FileTriage]


class PlanTask(BaseModel):
    title: str
    files: list[str]
    focus: list[Focus]
    rationale: str
    related_symbols: list[str]


class ReviewPlan(BaseModel):
    tasks: list[PlanTask]


class CandidateFinding(BaseModel):
    path: str
    start_line: int | None
    end_line: int
    severity: Severity
    category: Category
    title: str
    body: str
    suggestion: str | None
    evidence: list[str]
    confidence: float

    def to_candidate(self, task_id: UUID | None = None) -> Candidate:
        end = max(1, self.end_line)
        start = self.start_line if self.start_line and self.start_line > 0 else None
        if start is not None and start > end:
            start, end = end, start
        if start == end:
            start = None
        return Candidate(
            path=self.path.strip().removeprefix("./"),
            start_line=start,
            end_line=end,
            severity=self.severity,
            category=self.category,
            title=self.title.strip(),
            body=self.body.strip(),
            suggestion=self.suggestion if self.suggestion and self.suggestion.strip() else None,
            evidence=[str(e) for e in self.evidence][:MAX_EVIDENCE],
            confidence=min(1.0, max(0.0, float(self.confidence))),
            task_id=task_id,
        )


class SinglePassFindings(BaseModel):
    findings: list[CandidateFinding]


class JudgeVerdict(BaseModel):
    index: int
    verdict: Literal["keep", "drop"]
    reason: str
    adjusted_severity: Severity | None
    duplicate_of: int | None


class JudgeBatch(BaseModel):
    verdicts: list[JudgeVerdict]


class ChangeGroup(BaseModel):
    files: list[str]
    summary: str


class WalkthroughSummary(BaseModel):
    walkthrough: str
    changes: list[ChangeGroup]
    sequence_diagrams: list[str]
    effort: int
    effort_minutes: int
    pr_summary: str
    poem: str | None
    title: str | None = None
