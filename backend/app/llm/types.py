"""LLM gateway types (spec §4.2)."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel

from app.settings import Settings

Role = Literal["review", "cheap", "embed"]
StructuredMode = Literal["json_schema", "json_object", "text"]
Message = dict[str, Any]
ToolSpec = dict[str, Any]
EXCERPT_BYTES = 8192
_M = Decimal(1_000_000)


class LLMError(Exception):
    pass


class StructuredOutputError(LLMError):
    pass


class ToolsUnsupported(LLMError):
    pass


class ProviderUnavailable(LLMError):
    pass


@dataclass(frozen=True)
class RoleConfig:
    role: Role
    base_url: str
    api_key: str = field(repr=False)
    model: str
    price_input_per_1m: Decimal | None = None
    price_cached_per_1m: Decimal | None = None
    price_output_per_1m: Decimal | None = None
    dimensions: int | None = None

    @property
    def provider_host(self) -> str:
        return urlparse(self.base_url).hostname or self.base_url


@dataclass(frozen=True)
class TraceContext:
    org_id: UUID | None = None
    review_id: UUID | None = None
    chat_id: UUID | None = None
    task_id: UUID | None = None
    # Credit attribution key (``STAGE_LABELS`` in ``app.billing.pricing``); None counts as other.
    stage: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cached_tokens + other.cached_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMResult:
    content: str | None
    parsed: BaseModel | None
    tool_calls: list[ToolCall]
    usage: Usage
    cost_usd: Decimal | None
    model: str
    structured_mode: StructuredMode | None
    latency_ms: int
    # HootPR credits for ``usage`` at the rate card (6 dp); 0 for clients without a rate card.
    credits: Decimal = Decimal(0)


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    usage: Usage
    cost_usd: Decimal | None
    model: str
    credits: Decimal = Decimal(0)


@dataclass(frozen=True)
class LLMCallRecord:
    trace: TraceContext
    role: Role
    model: str
    provider_host: str
    usage: Usage
    cost_usd: Decimal | None
    latency_ms: int
    status: Literal["ok", "error"]
    error: str | None
    structured_mode: StructuredMode | None
    request_excerpt: str
    response_excerpt: str
    credits: Decimal | None = None


def role_configs(settings: Settings) -> dict[Role, RoleConfig]:
    s = settings
    return {
        "review": RoleConfig(
            "review",
            s.llm_review_base_url,
            s.llm_review_api_key.get_secret_value(),
            s.llm_review_model,
            s.llm_review_price_input_per_1m,
            s.llm_review_price_cached_per_1m,
            s.llm_review_price_output_per_1m,
        ),
        "cheap": RoleConfig(
            "cheap",
            s.llm_cheap_base_url,
            s.llm_cheap_api_key.get_secret_value(),
            s.llm_cheap_model,
            s.llm_cheap_price_input_per_1m,
            s.llm_cheap_price_cached_per_1m,
            s.llm_cheap_price_output_per_1m,
        ),
        "embed": RoleConfig(
            "embed",
            s.llm_embed_base_url,
            s.llm_embed_api_key.get_secret_value(),
            s.llm_embed_model,
            dimensions=s.llm_embed_dimensions,
        ),
    }


def compute_cost(cfg: RoleConfig, usage: Usage) -> Decimal | None:
    if cfg.price_input_per_1m is None or cfg.price_output_per_1m is None:
        return None
    cached_price = (
        cfg.price_cached_per_1m if cfg.price_cached_per_1m is not None else cfg.price_input_per_1m
    )
    fresh = max(0, usage.input_tokens - usage.cached_tokens)
    total = (
        fresh * cfg.price_input_per_1m
        + usage.cached_tokens * cached_price
        + usage.output_tokens * cfg.price_output_per_1m
    ) / _M
    return total.normalize()


def excerpt(text: str, full: bool) -> str:
    if full:
        return text
    raw = text.encode()
    return text if len(raw) <= EXCERPT_BYTES else raw[:EXCERPT_BYTES].decode(errors="ignore")
