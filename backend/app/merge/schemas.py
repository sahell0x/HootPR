"""LLM I/O models for Phase 5. No numeric/length constraints (strict json_schema on every
provider); values are clamped and hardened in code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["passed", "failed", "inconclusive"]
Assessment = Literal["addressed", "partially", "not_addressed", "unclear"]


class CheckVerdict(BaseModel):
    name: str
    status: CheckStatus
    explanation: str


class PreMergeVerdicts(BaseModel):
    checks: list[CheckVerdict]


class ObjectiveAssessment(BaseModel):
    objective: str
    status: Assessment
    explanation: str


class IssueAssessment(BaseModel):
    issue: str
    overall: Assessment
    objectives: list[ObjectiveAssessment]


class LinkedIssuesAssessment(BaseModel):
    issues: list[IssueAssessment]


class SlopVerdict(BaseModel):
    is_slop: bool
    confidence: float
    reasons: list[str]


class IssueDraft(BaseModel):
    title: str
    body: str


class LabelSuggestion(BaseModel):
    labels: list[str]
    reason: str


class MarkdownOutput(BaseModel):
    markdown: str
