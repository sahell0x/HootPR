"""Phase 8 API models (analytics, usage, reports, audit, API keys, public API, Change Stack)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# --- metrics ------------------------------------------------------------------------------


class Period(BaseModel):
    since: datetime
    until: datetime
    days: int


class CountItem(BaseModel):
    key: str
    count: int


class DayPoint(BaseModel):
    day: str  # YYYY-MM-DD (UTC)
    reviews: int = 0
    completed: int = 0
    blocked: int = 0
    findings: int = 0
    credits: Decimal = Decimal("0")
    cost_usd: Decimal | None = Decimal("0")  # internal: platform owners only


class DurationStats(BaseModel):
    count: int
    median_s: float | None
    p90_s: float | None
    mean_s: float | None


class AcceptanceStats(BaseModel):
    accepted: int  # thread resolved / suggestion committed
    dismissed: int
    open: int
    rate: float | None


class RepoBreakdown(BaseModel):
    repo_id: str
    repo_full_name: str
    reviews: int
    completed: int
    findings: int
    accepted: int
    dismissed: int
    acceptance_rate: float | None
    cost_usd: Decimal | None = None  # internal: platform owners only


class AuthorBreakdown(BaseModel):
    author: str
    pull_requests: int
    reviews: int
    findings: int
    critical_major: int


class Metrics(BaseModel):
    period: Period
    reviews_total: int
    reviews_by_status: list[CountItem]
    pull_requests: int
    findings_total: int
    findings_by_severity: list[CountItem]
    findings_by_category: list[CountItem]
    acceptance: AcceptanceStats
    time_to_first_review: DurationStats
    per_repo: list[RepoBreakdown]
    per_author: list[AuthorBreakdown]
    daily: list[DayPoint]


class UsageLedgerEntry(BaseModel):
    id: str
    delta: Decimal
    reason: str
    ref_type: str | None
    ref_id: str | None
    balance_after: Decimal
    created_at: datetime


class UsageReview(BaseModel):
    id: str
    repo_full_name: str
    pr_number: int
    status: str
    credits_charged: Decimal
    # Internal (platform owners only; null for everyone else).
    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    created_at: datetime


class Usage(BaseModel):
    period: Period
    balance: Decimal
    review_events: int
    completed: int
    rate_limited: int
    no_credits: int
    failed: int
    skipped: int
    credits_spent: Decimal
    credits_refunded: Decimal
    chat_replies: int
    chat_credits: Decimal
    # Internal (platform owners only; null for everyone else).
    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    avg_tokens_per_review: float | None = None
    avg_cost_per_review: Decimal | None = None
    daily: list[DayPoint]
    ledger: list[UsageLedgerEntry]
    reviews: list[UsageReview]


# --- reports ------------------------------------------------------------------------------

ReportSchedule = Literal["daily", "weekly", "monthly"]
ReportRunStatus = Literal["queued", "running", "completed", "failed"]


class ReportDef(BaseModel):
    id: str
    name: str
    prompt: str
    schedule: ReportSchedule
    hour_utc: int
    weekday: int
    repo_ids: list[str]
    email_to: list[str]
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime


class ReportDefList(BaseModel):
    reports: list[ReportDef]
    email_enabled: bool


class ReportDefIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    prompt: str = Field(default="", max_length=4000)
    schedule: ReportSchedule = "weekly"
    hour_utc: int = Field(default=9, ge=0, le=23)
    weekday: int = Field(default=0, ge=0, le=6)
    repo_ids: list[str] = Field(default_factory=list, max_length=50)
    email_to: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True


class ReportRunSummary(BaseModel):
    id: str
    report_id: str | None
    title: str
    trigger: str
    status: ReportRunStatus
    period_start: datetime
    period_end: datetime
    degraded: bool
    created_at: datetime
    finished_at: datetime | None


class ReportRunDetail(ReportRunSummary):
    prompt: str
    content: str | None
    error: str | None
    emailed_to: list[str]
    # Internal (platform owners only; null for everyone else).
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None


class ReportRunList(BaseModel):
    runs: list[ReportRunSummary]
    next_before: datetime | None


class CustomReportIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    days: int = Field(default=7, ge=1, le=365)
    repo_ids: list[str] = Field(default_factory=list, max_length=50)
    title: str | None = Field(default=None, max_length=255)


# --- audit & api keys ---------------------------------------------------------------------


class AuditEntry(BaseModel):
    id: str
    actor_label: str
    actor_user_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, object]
    created_at: datetime


class AuditList(BaseModel):
    entries: list[AuditEntry]
    next_before: datetime | None


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyList(BaseModel):
    keys: list[ApiKeyOut]


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyCreated(ApiKeyOut):
    secret: str  # shown exactly once


# --- change stack -------------------------------------------------------------------------


class CsPull(BaseModel):
    id: str
    repo_id: str
    repo_full_name: str
    provider: str
    number: int
    title: str
    url: str
    author_username: str
    state: str
    is_draft: bool
    base_ref: str
    head_ref: str
    head_sha: str
    last_reviewed_sha: str | None
    updated_at: datetime


class CsPullList(BaseModel):
    pulls: list[CsPull]


class CsSnapshot(BaseModel):
    review_id: str
    head_sha: str
    base_sha: str | None
    status: str
    trigger: str
    findings: int
    created_at: datetime
    stale: bool


class CsFile(BaseModel):
    path: str
    old_path: str | None
    status: str
    additions: int
    deletions: int
    findings: int


class CsGroup(BaseModel):
    title: str
    rationale: str
    files: list[CsFile]


class CsFinding(BaseModel):
    id: str
    path: str
    start_line: int | None
    end_line: int
    side: str
    severity: str
    category: str
    title: str
    body: str
    suggestion: str | None
    status: str
    posted: bool


class CsViewer(BaseModel):
    username: str | None
    has_token: bool
    can_submit: bool
    can_merge: bool
    reason: str | None


class CsWorkspace(BaseModel):
    pull: CsPull
    snapshots: list[CsSnapshot]
    snapshot: CsSnapshot | None
    stale: bool
    groups: list[CsGroup]
    findings: list[CsFinding]
    viewer: CsViewer
    diff_error: str | None


class CsFileContents(BaseModel):
    path: str
    original: str
    modified: str
    language: str
    truncated: bool


class CsMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    body: str
    author: str | None
    path: str | None
    line: int | None
    head_sha: str | None
    status: str
    credits_charged: Decimal
    created_at: datetime


class CsMessageList(BaseModel):
    messages: list[CsMessage]


class CsMessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    path: str | None = Field(default=None, max_length=1024)
    line: int | None = Field(default=None, ge=1)
    head_sha: str | None = Field(default=None, max_length=64)


class CsReviewComment(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    line: int = Field(ge=1)
    start_line: int | None = Field(default=None, ge=1)
    side: Literal["LEFT", "RIGHT"] = "RIGHT"
    body: str = Field(min_length=1, max_length=20000)


class CsReviewIn(BaseModel):
    event: Literal["COMMENT", "APPROVE", "REQUEST_CHANGES"]
    body: str = Field(default="", max_length=60000)
    head_sha: str = Field(min_length=7, max_length=64)
    comments: list[CsReviewComment] = Field(default_factory=list, max_length=100)


class CsReviewOut(BaseModel):
    review_ref: str
    event: str


class CsMergeIn(BaseModel):
    method: Literal["merge", "squash", "rebase"] = "merge"
    head_sha: str = Field(min_length=7, max_length=64)
    commit_title: str | None = Field(default=None, max_length=500)


class CsMergeOut(BaseModel):
    merged: bool
    sha: str | None
    message: str


# --- public API ---------------------------------------------------------------------------


class PublicOrg(BaseModel):
    id: str
    slug: str
    name: str
    provider: str
    credits_balance: Decimal
