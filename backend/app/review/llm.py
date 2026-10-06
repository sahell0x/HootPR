"""The engine's view of the gateway, with per-job usage/cost/credit totals."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.billing.pricing import stage_key
from app.llm.types import EmbedResult, LLMResult, Message, Role, ToolSpec, TraceContext, Usage


class LLMLike(Protocol):
    def complete(
        self,
        role: Role,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        response_model: type[BaseModel] | None = None,
        max_output_tokens: int,
        trace: TraceContext,
    ) -> LLMResult: ...


@runtime_checkable
class MeteredEmbedder(Protocol):
    def embed_metered(self, texts: list[str], trace: TraceContext) -> EmbedResult: ...


class MeteredLLM:
    """``credits``/``credits_by_stage``: HootPR credits metered so far (key: the trace's stage).
    ``credit_budget``: the job's hold; callers check ``budget_used`` before scheduling more work
    (the wrapper itself never refuses a call)."""

    def __init__(self, inner: LLMLike, *, credit_budget: Decimal | None = None) -> None:
        self._inner = inner
        self.usage = Usage()
        self._cost = Decimal(0)
        self._priced = False
        self.models: list[str] = []
        self.credits = Decimal(0)
        self.credits_by_stage: dict[str, Decimal] = {}
        self.credit_budget = credit_budget

    def complete(
        self,
        role: Role,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        response_model: type[BaseModel] | None = None,
        max_output_tokens: int,
        trace: TraceContext,
    ) -> LLMResult:
        res = self._inner.complete(
            role,
            messages,
            tools=tools,
            response_model=response_model,
            max_output_tokens=max_output_tokens,
            trace=trace,
        )
        self._add(res.usage, res.cost_usd, res.model, res.credits, trace.stage)
        return res

    def embed(self, texts: list[str], trace: TraceContext) -> list[list[float]]:
        """Embeddings (team learnings) count toward the same totals as completions."""
        if not isinstance(self._inner, MeteredEmbedder):
            raise TypeError("the wrapped client cannot embed")
        res = self._inner.embed_metered(texts, trace)
        self._add(res.usage, res.cost_usd, res.model, res.credits, trace.stage)
        return res.vectors

    def _add(
        self,
        usage: Usage,
        cost: Decimal | None,
        model: str,
        credits: Decimal | None = None,
        stage: str | None = None,
    ) -> None:
        self.usage = self.usage + usage
        if cost is not None:
            self._cost += cost
            self._priced = True
        if model not in self.models:
            self.models.append(model)
        if credits:
            key = stage_key(stage)
            self.credits += credits
            self.credits_by_stage[key] = self.credits_by_stage.get(key, Decimal(0)) + credits

    def budget_used(self, fraction: Decimal = Decimal(1)) -> bool:
        """Whether ``credits`` reached ``fraction`` of the budget (never, without a budget)."""
        if self.credit_budget is None:
            return False
        return self.credits >= self.credit_budget * fraction

    @property
    def cost_usd(self) -> Decimal | None:
        return self._cost if self._priced else None
