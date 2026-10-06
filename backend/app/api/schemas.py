"""Response/request models of the API contract (plan: 'API contract'). Names are the contract."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthChecks(BaseModel):
    db: str
    redis: str
    docker_proxy: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    checks: HealthChecks


# --- identity -------------------------------------------------------------------------------

Provider = Literal["github", "gitlab"]
Role = Literal["admin", "member", "billing_admin"]
OrgKind = Literal["org", "group", "personal"]


class Identity(BaseModel):
    provider: Provider
    provider_user_id: str
    username: str


class CsrfToken(BaseModel):
    csrf_token: str


class Me(BaseModel):
    id: str
    email: str | None
    display_name: str
    avatar_url: str | None
    identities: list[Identity]
    csrf_token: str


# --- organizations --------------------------------------------------------------------------


class OrgCandidate(BaseModel):
    provider: Provider
    provider_org_id: str
    kind: OrgKind
    name: str
    avatar_url: str | None
    slug: str | None
    joined: bool
    installed: bool
    role: Role | None
    install_url: str | None


class OrgCandidateList(BaseModel):
    orgs: list[OrgCandidate]


class SelectOrgRequest(BaseModel):
    provider: Provider
    provider_org_id: str


class Org(BaseModel):
    id: str
    slug: str
    provider: Provider
    kind: OrgKind
    name: str
    avatar_url: str | None
    role: Role
    credits_balance: Decimal
    installed: bool
    knowledge_base_opt_out: bool


class OrgList(BaseModel):
    orgs: list[Org]


# --- meta -----------------------------------------------------------------------------------


class CreditPack(BaseModel):
    credits: int
    price_paise: int
    currency: Literal["INR"] = "INR"


class ProvidersEnabled(BaseModel):
    github: bool
    gitlab: bool


class CreditPrices(BaseModel):
    """Typical (display-only) credit prices so the UI never hard-codes them. Jobs are metered by
    AI usage (``CREDITS_TYPICAL_*`` in .env); ``signup_bonus`` is the real grant."""

    per_review: Decimal
    per_chat_reply: Decimal
    signup_bonus: Decimal


class Meta(BaseModel):
    github_app_slug: str
    github_install_url: str
    gitlab_base_url: str
    razorpay_key_id: str
    billing_test_mode: Literal[True] = True
    disclaimer: str
    credit_pack: CreditPack
    credit_prices: CreditPrices
    providers_enabled: ProvidersEnabled


# --- configuration (.hootpr.yaml) -------------------------------------------------------------


class ConfigError(BaseModel):
    line: int | None
    path: str
    message: str


class ValidateConfigRequest(BaseModel):
    yaml: str


class ConfigValidation(BaseModel):
    valid: bool
    errors: list[ConfigError]
    effective: dict[str, Any] | None


# --- org settings & members -----------------------------------------------------------------


class OrgSettings(BaseModel):
    settings: dict[str, Any]
    knowledge_base_opt_out: bool


class SettingsUpdate(BaseModel):
    settings: dict[str, Any]
    knowledge_base_opt_out: bool | None = None


class Member(BaseModel):
    user_id: str
    display_name: str
    username: str | None
    avatar_url: str | None
    role: Role


class MemberList(BaseModel):
    members: list[Member]


class RoleUpdate(BaseModel):
    role: Role


# --- repositories & GitLab bot --------------------------------------------------------------


class Repo(BaseModel):
    id: str
    provider: Provider
    full_name: str
    private: bool
    enabled: bool
    default_branch: str
    last_review_at: datetime | None


class RepoList(BaseModel):
    repos: list[Repo]
    can_install: bool
    install_url: str | None


class UpdateRepoRequest(BaseModel):
    enabled: bool


class RepoSettings(BaseModel):
    repo: Repo
    settings: dict[str, Any]


class GitlabBot(BaseModel):
    connected: bool
    bot_username: str | None
    bot_user_id: int | None


class GitlabBotRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class GitlabProject(BaseModel):
    id: int
    path_with_namespace: str
    selected: bool


class GitlabProjectList(BaseModel):
    projects: list[GitlabProject]
    whole_group: bool


class GitlabProjectsRequest(BaseModel):
    project_ids: list[int]
    whole_group: bool = False


# --- billing --------------------------------------------------------------------------------

LedgerReason = Literal[
    "signup_bonus",
    "purchase",
    "review_hold",
    "review",
    "chat",
    "refund",
    "manual",
    "security_review",
    "finishing",
    "security",
]


class LedgerEntry(BaseModel):
    id: str
    delta: Decimal
    reason: LedgerReason
    ref_type: str | None
    ref_id: str | None
    balance_after: Decimal
    created_at: datetime
    # Settle rows (review/chat/finishing/security closing a hold): the final charge
    # (hold - returned); None for every other row.
    charged: Decimal | None = None
    # What the movement was for ("owner/repo #12 · Fix login"), None for signup / manual rows.
    description: str | None = None
    # Dashboard-relative link for the thing that was billed (e.g. ``/o/acme/reviews/<id>``).
    href: str | None = None
    # A credit receipt exists: ``GET /api/orgs/{org}/billing/receipts/{ref_type}/{ref_id}``.
    has_receipt: bool = False


class Metering(BaseModel):
    """Token-metered pricing facts for the billing page (docs/token-metered-billing.md §6)."""

    review_min_charge: Decimal
    review_hold_max: Decimal
    chat_min_charge: Decimal
    avg_review_credits_30d: Decimal | None
    reviews_30d: int


class UsageSource(BaseModel):
    """Unbilled LLM work of one kind (learnings, reports, post-merge, ...)."""

    source: str
    credits: Decimal
    cost_usd: Decimal | None


class OwnerUsage(BaseModel):
    """Platform-owner only: metered credits over the last 30 days, billed (tied to a paying job)
    vs unbilled (background work nobody is charged for), and the provider cost."""

    billed_credits: Decimal
    unbilled_credits: Decimal
    # Credits actually charged to the org in the window (settled holds), for the margin.
    charged_credits: Decimal
    cost_usd: Decimal
    by_source: list[UsageSource]


class Billing(BaseModel):
    balance: Decimal
    purchases_count: int
    max_purchases: int
    max_balance: Decimal
    pack: CreditPack
    can_purchase: bool
    purchase_blocked_reason: str | None
    ledger: list[LedgerEntry]
    disclaimer: str
    metering: Metering
    # Platform owners only (``INTERNAL_FIELDS``); None for everyone else.
    usage_30d: OwnerUsage | None = None
    test_mode: Literal[True] = True


class OrderPrefill(BaseModel):
    email: str | None
    name: str | None


class Order(BaseModel):
    order_id: str
    key_id: str
    amount_paise: int
    currency: Literal["INR"] = "INR"
    credits: int
    name: str
    description: str
    prefill: OrderPrefill


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class VerifyResult(BaseModel):
    status: Literal["paid"]
    credits_added: Decimal
    balance: Decimal


# --- reviews --------------------------------------------------------------------------------

ReviewStatus = Literal[
    "queued", "running", "completed", "failed", "skipped", "rate_limited", "no_credits"
]
ReviewTriggerT = Literal["auto", "incremental", "command_review", "command_full", "manual"]


class ReviewSummary(BaseModel):
    id: str
    repo_full_name: str
    pr_number: int
    pr_title: str
    pr_url: str
    trigger: ReviewTriggerT
    status: ReviewStatus
    skip_reason: str | None
    credits_charged: Decimal
    findings_posted: int
    files_considered: int
    # Internal (platform owners only; null for everyone else).
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    created_at: datetime
    finished_at: datetime | None


class ReviewList(BaseModel):
    reviews: list[ReviewSummary]
    next_before: datetime | None


StageName = Literal[
    "config",
    "diff",
    "sandbox",
    "graph",
    "tools",
    "context",
    "triage",
    "plan",
    "agents",
    "judge",
    "summarize",
    "post",
    "close",
]
StageStatus = Literal["ok", "failed", "skipped", "degraded"]
TaskStatus = Literal["pending", "running", "done", "skipped", "failed"]
JudgeVerdictT = Literal["keep", "drop", "merge"]


class Finding(BaseModel):
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
    posted: bool
    status: str
    source: str
    confidence: float | None
    task_id: str | None
    judge_verdict: JudgeVerdictT | None
    judge_reason: str | None
    fingerprint: str
    evidence: list[str]


class LlmCall(BaseModel):
    id: str
    task_id: str | None
    role: str
    model: str
    provider_host: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    latency_ms: int
    status: str
    error: str | None
    structured_mode: str | None
    created_at: datetime
    stage: str | None = None
    credits: Decimal | None = None


class LlmCallDetail(LlmCall):
    request_excerpt: str | None
    response_excerpt: str | None


class AgentStep(BaseModel):
    id: str
    task_id: str | None
    step_no: int
    kind: str
    tool_name: str | None
    args: dict[str, Any]
    output_excerpt: str | None
    duration_ms: int | None
    created_at: datetime


class ToolRun(BaseModel):
    id: str
    tool: str
    status: str
    duration_ms: int | None
    findings_count: int
    stderr_excerpt: str | None


class ReviewStage(BaseModel):
    name: StageName
    status: StageStatus
    started_at: datetime
    duration_ms: int
    detail: str | None


class ReviewTask(BaseModel):
    id: str
    ordinal: int
    title: str
    rationale: str
    files: list[str]
    focus: list[str]
    status: TaskStatus
    summary: str | None


class Trace(BaseModel):
    stages: list[ReviewStage]
    tasks: list[ReviewTask]
    # Internal (platform owners only; empty for everyone else).
    llm_calls: list[LlmCall]
    agent_steps: list[AgentStep]
    tool_runs: list[ToolRun]


class ReceiptLine(BaseModel):
    """Credits one pipeline stage used, in whole credits (the lines add up to ``charged``).
    Token / $ fields are owner-only (``INTERNAL_FIELDS``)."""

    stage: str
    label: str
    credits: Decimal
    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None


class Receipt(BaseModel):
    """A job's credit receipt (review, chat, finishing touch, security review): hold, final
    charge, returned part and per-stage lines. All amounts are whole credits (decimal strings
    without a fractional part, e.g. ``"285"``)."""

    reserved: Decimal
    charged: Decimal
    refunded: Decimal
    minimum_applied: bool
    budget_reached: bool
    # Billed before usage metering (no metered calls): one flat-rate line carries the charge.
    legacy: bool = False
    lines: list[ReceiptLine]


class ReviewDetail(ReviewSummary):
    base_sha: str | None
    head_sha: str
    error: str | None
    degraded: dict[str, Any]
    files_reviewed: int
    findings: list[Finding]
    trace: Trace
    # None when the review never held credits (skipped / rate limited / no credits).
    receipt: Receipt | None = None


LearningScope = Literal["repo", "org"]


class Learning(BaseModel):
    id: str
    text: str
    scope: LearningScope
    repo_id: str | None
    repo_full_name: str | None
    path_glob: str | None
    source_url: str | None
    pr_number: int | None
    created_by_username: str
    embedded: bool
    created_at: datetime
    updated_at: datetime


class LearningList(BaseModel):
    learnings: list[Learning]
    # ISO created_at of the last row when more rows exist (pass back as ``before``).
    next_before: str | None


class LearningCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    scope: LearningScope = "repo"
    repo_id: str | None = None
    path_glob: str | None = Field(default=None, max_length=512)


class LearningUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    scope: LearningScope | None = None
    path_glob: str | None = Field(default=None, max_length=512)


class EffectiveConfig(BaseModel):
    config: dict[str, Any]
    provenance: dict[str, Literal["repo", "org"]]
    yaml: str
    # Layers that contributed, highest precedence first; "default" fills everything else.
    sources: list[Literal["repo", "org", "default"]]
    yaml_file_note: str
