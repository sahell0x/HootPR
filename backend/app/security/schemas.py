"""Structured output of the security architecture review (spec §10.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["critical", "high", "medium", "low"]


class SecurityRisk(BaseModel):
    title: str = Field(description="At most 100 characters.")
    severity: RiskLevel
    category: str = Field(
        description="e.g. authentication, authorization, injection, secrets, crypto, "
        "data-exposure, infrastructure, supply-chain, ssrf, configuration"
    )
    description: str = Field(description="What is wrong and why it matters (≤ 800 characters).")
    affected: list[str] = Field(description="Endpoints, files or resources affected (≤ 8).")
    recommendation: str = Field(description="Concrete fix (≤ 600 characters).")


class SecurityReport(BaseModel):
    summary: str = Field(description="Executive summary of the security posture (≤ 1200 chars).")
    overall_risk: RiskLevel
    risks: list[SecurityRisk] = Field(description="Prioritized, most severe first (≤ 12).")
    strengths: list[str] = Field(description="Good security practices observed (≤ 6).")
