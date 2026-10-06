"""Application settings, read from environment / .env (spec §15 + plan decision P11)."""

from __future__ import annotations

import base64
import hashlib
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_WARNING = "using derived development secrets; never do this in production"


def _derive(label: str) -> str:
    """Deterministic 32-byte urlsafe-base64 key (valid Fernet key) for development only."""
    return base64.urlsafe_b64encode(hashlib.sha256(label.encode()).digest()).decode()


# The repo-root .env is the single config file for docker AND non-docker runs (``make dev-api`` runs
# from backend/). In the container this path does not exist and compose's env_file applies instead.
# A ``.env`` in the working directory, when present, overrides it (later files win).
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # --- core
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    app_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    # Ports from the root .env; when APP_BASE_URL / API_BASE_URL are unset they follow these.
    web_port: int = 3000
    api_port: int = 8000
    # The dashboard (APP_BASE_URL) and the API (API_BASE_URL) are separate origins. CORS allows
    # exactly APP_BASE_URL plus these comma-separated extra origins, with credentials.
    cors_extra_origins: str = ""
    # SameSite for the session / CSRF cookies (set by the API origin). ``lax`` works when the two
    # origins are same-site (localhost:3000 + localhost:8000, app.example.com + api.example.com);
    # ``none`` (forces Secure) is needed when they are cross-site (two *.trycloudflare.com hosts).
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # Optional Domain attribute for those cookies (e.g. ``.example.com``); empty = host-only.
    cookie_domain: str = ""
    secret_encryption_key: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    database_url: str = "postgresql+psycopg://hootpr:hootpr@postgres:5432/hootpr"
    redis_url: str = "redis://redis:6379/0"
    # Comma-separated ``provider:username`` (e.g. ``github:octocat``) who may see internal LLM
    # cost / token / model data. Everyone else only ever sees HootPR credits.
    platform_owners: str = ""

    # --- GitHub App
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    github_app_id: str = ""
    github_app_slug: str = "hootpr"
    github_app_private_key_path: str = "/run/secrets/github_app.pem"
    github_app_private_key: SecretStr = SecretStr("")
    github_webhook_secret: SecretStr = SecretStr("")
    github_oauth_client_id: str = ""
    github_oauth_client_secret: SecretStr = SecretStr("")
    smee_url: str = ""

    # --- GitLab
    gitlab_base_url: str = "https://gitlab.com"
    gitlab_oauth_client_id: str = ""
    gitlab_oauth_client_secret: SecretStr = SecretStr("")
    gitlab_webhook_url: str = ""

    # --- LLM roles
    llm_review_base_url: str = "https://api.openai.com/v1"
    llm_review_api_key: SecretStr = SecretStr("")
    llm_review_model: str = "gpt-6-luna"
    llm_review_price_input_per_1m: Decimal | None = Decimal("0.10")
    llm_review_price_cached_per_1m: Decimal | None = Decimal("0.01")
    llm_review_price_output_per_1m: Decimal | None = Decimal("0.50")
    llm_cheap_base_url: str = "https://api.openai.com/v1"
    llm_cheap_api_key: SecretStr = SecretStr("")
    llm_cheap_model: str = "gpt-5-nano"
    llm_cheap_price_input_per_1m: Decimal | None = Decimal("0.05")
    llm_cheap_price_cached_per_1m: Decimal | None = Decimal("0.005")
    llm_cheap_price_output_per_1m: Decimal | None = Decimal("0.40")
    llm_embed_base_url: str = "https://api.openai.com/v1"
    llm_embed_api_key: SecretStr = SecretStr("")
    llm_embed_model: str = "text-embedding-3-small"
    llm_embed_dimensions: int = 1536
    llm_log_full: bool = False
    llm_log_retention_days: int = 30

    # --- billing (Razorpay TEST MODE ONLY)
    razorpay_api_url: str = "https://api.razorpay.com/v1"
    razorpay_key_id: str = "rzp_test_unset"
    razorpay_key_secret: SecretStr = SecretStr("")
    razorpay_webhook_secret: SecretStr = SecretStr("")
    credits_signup_bonus: Decimal = Decimal("300")
    # Token-metered credits (docs/token-metered-billing.md): HootPR's own rate card, credits
    # per 1M tokens per gateway role (fresh input / cached input / output). Calibrated so an
    # average review (~8.5k in, 3.4k cached, 4.9k out) costs about 100 credits.
    credits_review_input_per_1m: Decimal = Decimal("6000")
    credits_review_cached_per_1m: Decimal = Decimal("600")
    credits_review_output_per_1m: Decimal = Decimal("12000")
    credits_cheap_input_per_1m: Decimal = Decimal("2000")
    credits_cheap_cached_per_1m: Decimal = Decimal("200")
    credits_cheap_output_per_1m: Decimal = Decimal("4000")
    credits_embed_input_per_1m: Decimal = Decimal("200")
    credits_embed_cached_per_1m: Decimal = Decimal("200")
    credits_embed_output_per_1m: Decimal = Decimal("0")
    # Holds (reserve → meter → budget → settle). A review's hold is sized from the PR:
    # base + lines * per_line + files * per_file, clamped to [review_min_charge, review_hold_max]
    # and to the balance; a job is refused only when the balance is below its minimum charge.
    review_hold_base: Decimal = Decimal("100")
    review_hold_per_line: Decimal = Decimal("0.4")
    review_hold_per_file: Decimal = Decimal("5")
    review_hold_max: Decimal = Decimal("1000")
    review_min_charge: Decimal = Decimal("10")
    chat_hold_max: Decimal = Decimal("100")
    chat_min_charge: Decimal = Decimal("5")
    finishing_hold_max: Decimal = Decimal("300")
    finishing_min_charge: Decimal = Decimal("10")
    security_hold_max: Decimal = Decimal("500")
    security_min_charge: Decimal = Decimal("50")
    # Display-only "typical" prices for the public pricing copy (/api/meta); never charged.
    credits_typical_review: Decimal = Decimal("100")
    credits_typical_chat_reply: Decimal = Decimal("50")
    credit_pack_credits: int = 500
    credit_pack_price_paise: int = 4900
    max_purchases_per_org: int = 2
    max_credit_balance: Decimal = Decimal("1000")
    rate_limit_reviews_per_hour: int = 2
    rate_limit_chat_per_hour: int = 10

    # --- review engine
    review_worker_concurrency: int = 1
    review_max_files: int = 150
    review_max_changed_lines: int = 5000
    review_max_tasks: int = 6
    review_max_comments: int = 25
    review_agent_parallelism: int = 1
    # Queued/running reviews older than this are failed and refunded by the beat sweep.
    review_stuck_timeout_minutes: int = 120
    agent_max_steps: int = 8
    agent_max_input_tokens: int = 60000
    graph_max_files: int = 3000
    repo_max_mb: int = 300
    sandbox_image: str = "hootpr/sandbox:latest"
    sandbox_mem_mb: int = 768
    sandbox_test_mem_mb: int = 1200
    sandbox_cpus: float = 1.0
    docker_host: str = "tcp://docker-proxy:2375"
    # --- review engine (Phase 2, spec §7 + plan contract C6)
    sandbox_backend: Literal["docker", "local"] = "docker"
    sandbox_network: str = "hootpr_sandbox_egress"
    sandbox_clone_depth: int = Field(default=50, ge=1)
    sandbox_tools_timeout_s: int = Field(default=600, ge=10)
    sandbox_graph_timeout_s: int = Field(default=300, ge=10)
    sandbox_orphan_max_age_minutes: int = Field(default=30, ge=5)
    sandbox_local_tools_dir: str = ""
    graph_max_symbols: int = Field(default=20000, ge=100)
    agent_shell_timeout_s: int = Field(default=20, ge=1)
    agent_shell_max_output_kb: int = Field(default=16, ge=1)
    # Cost bounds (spec §7.5): input tokens summed over one task's calls, findings recorded per
    # task, and input tokens over the whole review (remaining agent tasks are skipped past it).
    agent_max_task_input_tokens: int = Field(default=250_000, ge=1000)
    agent_max_findings: int = Field(default=15, ge=1)
    review_max_input_tokens: int = Field(default=1_500_000, ge=1000)
    judge_batch_size: int = Field(default=10, ge=1, le=10)
    judge_min_confidence_chill: float = Field(default=0.6, ge=0, le=1)
    judge_min_confidence_assertive: float = Field(default=0.45, ge=0, le=1)
    review_cache_ttl_days: int = Field(default=7, ge=1)
    # --- chat & knowledge (Phase 3, plan contract C5)
    chat_agent_max_steps: int = Field(default=6, ge=0)
    chat_max_input_tokens: int = Field(default=40000, ge=1000)
    chat_reply_max_chars: int = Field(default=4000, ge=200)
    chat_thread_max_messages: int = Field(default=10, ge=0)
    chat_stuck_timeout_minutes: int = Field(default=30, ge=1)
    learnings_top_k: int = Field(default=8, ge=1, le=50)
    learnings_min_similarity: float = Field(default=0.25, ge=0, le=1)
    learnings_max_per_chat: int = Field(default=3, ge=0)
    guidelines_max_files: int = Field(default=50, ge=0)
    guidelines_max_file_kb: int = Field(default=8, ge=1)
    guidelines_max_total_kb: int = Field(default=32, ge=1)
    ast_grep_timeout_s: int = Field(default=120, ge=5)
    # --- pre/post-merge & issues (Phase 5, spec §10.2)
    related_prs_min_similarity: float = Field(default=0.8, ge=0, le=1)
    issue_duplicate_min_similarity: float = Field(default=0.85, ge=0, le=1)
    # --- finishing touches (Phase 4, spec §10.1)
    finishing_agent_max_steps: int = Field(default=24, ge=1)
    finishing_max_input_tokens: int = Field(default=60000, ge=1000)
    finishing_max_total_input_tokens: int = Field(default=600_000, ge=1000)
    finishing_test_timeout_s: int = Field(default=600, ge=30)  # install and each test run
    finishing_max_test_iterations: int = Field(default=3, ge=1, le=5)
    finishing_clone_depth: int = Field(default=500, ge=1)
    finishing_max_files: int = Field(default=60, ge=1)
    finishing_max_file_kb: int = Field(default=512, ge=1)
    finishing_stuck_timeout_minutes: int = Field(default=60, ge=5)
    ci_log_max_jobs: int = Field(default=5, ge=1)
    ci_log_max_kb: int = Field(default=24, ge=1)

    # --- optional
    search_provider: str = ""
    smtp_url: SecretStr = SecretStr("")
    # --- analytics, reports, public API (Phase 8)
    reports_email_from: str = "HootPR <reports@hootpr.local>"
    reports_custom_per_day: int = Field(default=5, ge=0)
    reports_max_output_tokens: int = Field(default=1500, ge=100)
    public_api_rate_per_minute: int = Field(default=60, ge=1)
    export_max_rows: int = Field(default=10000, ge=1)
    # --- knowledge base (Phase 7, spec §10.4)
    search_api_url: str = ""
    search_api_key: SecretStr = SecretStr("")
    search_api_key_header: str = "Authorization"
    search_query_param: str = "q"
    search_results_path: str = "results"
    search_max_results: int = Field(default=5, ge=1, le=20)
    search_timeout_s: float = Field(default=10.0, gt=0)
    mcp_timeout_s: float = Field(default=20.0, gt=0)
    mcp_max_output_kb: int = Field(default=16, ge=1)
    mcp_max_servers_per_org: int = Field(default=10, ge=0)
    mcp_max_tools: int = Field(default=20, ge=0)
    mcp_max_calls_per_review: int = Field(default=20, ge=0)
    mcp_allow_http: bool = False  # dev/test only; refused in production
    mcp_allow_private_hosts: bool = False  # dev/test only; refused in production
    linked_repos_max: int = Field(default=5, ge=0)
    linked_repos_max_mb: int = Field(default=200, ge=1)

    _dev_secrets: bool = PrivateAttr(default=False)

    @field_validator("razorpay_key_id")
    @classmethod
    def _razorpay_test_only(cls, v: str) -> str:
        if not v.startswith("rzp_test_"):
            raise ValueError(
                "RAZORPAY_KEY_ID must start with rzp_test_ (HootPR only runs Razorpay in test mode)"
            )
        return v

    @model_validator(mode="after")
    def _secrets(self) -> Settings:
        if self.app_env == "production":
            if self.sandbox_backend == "local":
                raise ValueError(
                    "SANDBOX_BACKEND=local runs repository commands on the host; "
                    "it is refused in production"
                )
            if self.mcp_allow_http or self.mcp_allow_private_hosts:
                raise ValueError(
                    "MCP_ALLOW_HTTP / MCP_ALLOW_PRIVATE_HOSTS are refused in production"
                )
            if not self.secret_encryption_key.get_secret_value():
                raise ValueError("SECRET_ENCRYPTION_KEY is required in production")
            if not self.session_secret.get_secret_value():
                raise ValueError("SESSION_SECRET is required in production")
        derived = False
        if not self.secret_encryption_key.get_secret_value():
            self.secret_encryption_key = SecretStr(_derive("hootpr-dev-encryption-key"))
            derived = True
        if not self.session_secret.get_secret_value():
            self.session_secret = SecretStr(_derive("hootpr-dev-session-secret"))
            derived = True
        try:
            Fernet(self.secret_encryption_key.get_secret_value().encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("SECRET_ENCRYPTION_KEY is not a valid Fernet key") from exc
        self._dev_secrets = derived
        return self

    @model_validator(mode="after")
    def _urls_follow_ports(self) -> Settings:
        if "app_base_url" not in self.model_fields_set:
            self.app_base_url = f"http://localhost:{self.web_port}"
        if "api_base_url" not in self.model_fields_set:
            self.api_base_url = f"http://localhost:{self.api_port}"
        return self

    @property
    def using_dev_secrets(self) -> bool:
        """True when SECRET_ENCRYPTION_KEY or SESSION_SECRET was derived (dev fallback, P9)."""
        return self._dev_secrets

    @property
    def fernet_key(self) -> bytes:
        return self.secret_encryption_key.get_secret_value().encode()

    @property
    def session_key(self) -> bytes:
        return self.session_secret.get_secret_value().encode()

    @property
    def cookie_secure(self) -> bool:
        # Cookies are set by the API origin; SameSite=None is only accepted with Secure.
        return self.api_base_url.startswith("https://") or self.cookie_samesite == "none"

    @property
    def cors_origins(self) -> list[str]:
        out = [self.app_base_url.rstrip("/")]
        for o in self.cors_extra_origins.split(","):
            o = o.strip().rstrip("/")
            if o and o not in out:
                out.append(o)
        return out

    @property
    def gitlab_hook_url(self) -> str:
        return self.gitlab_webhook_url or f"{self.api_base_url.rstrip('/')}/api/webhooks/gitlab"

    @property
    def billing_configured(self) -> bool:
        return bool(self.razorpay_key_secret.get_secret_value()) and (
            self.razorpay_key_id != "rzp_test_unset"
        )

    def github_private_key(self) -> str:
        inline = self.github_app_private_key.get_secret_value()
        if inline:
            return inline.replace("\\n", "\n")
        path = Path(self.github_app_private_key_path)
        return path.read_text() if path.is_file() else ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
