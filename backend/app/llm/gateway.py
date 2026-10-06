"""The only way code talks to a model (spec §4.2).

* Structured output ladder: ``json_schema`` (strict) -> ``json_object`` (+ schema in a system
  message) -> plain ``text`` (+ schema, first JSON object extracted). The rung that works is
  cached per (base_url, model) for 24 h so later calls skip rungs the provider rejected.
* Pydantic validation; one retry with the validation error appended, then
  ``StructuredOutputError``.
* A 400 that mentions tools caches "no tools" and raises ``ToolsUnsupported``; later calls
  raise without a request.
* Retries: 429 / 5xx / timeouts / connection errors, honoring ``Retry-After`` (capped at 30 s),
  else exponential backoff with jitter; exhausted -> ``ProviderUnavailable``.
* A 400 about ``max_completion_tokens`` switches that model to ``max_tokens`` (cached).
* A 400 saying tools need ``reasoning_effort='none'`` (e.g. OpenAI reasoning models on
  /chat/completions) resends tool calls with ``reasoning_effort="none"`` (cached per model).
* Every HTTP exchange (success or failure, after retries) writes exactly one metering record.
* ``LLMResult.usage``/``cost_usd``/``credits`` cover every successful call made by one
  ``complete()`` (incl. the validation retry); rejected 400 rungs carry no usage.
* Credits (HootPR's rate card, ``app.billing.pricing``) are computed next to ``compute_cost``
  and stored per call with the trace's ``stage``.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Literal

import openai
from pydantic import BaseModel, ValidationError

from app.billing.pricing import RateCard, credits_for
from app.kv import KV
from app.llm.metering import CallRecorder
from app.llm.structured import extract_json_object, schema_instruction, strict_json_schema
from app.llm.types import (
    EmbedResult,
    LLMCallRecord,
    LLMError,
    LLMResult,
    Message,
    ProviderUnavailable,
    Role,
    RoleConfig,
    StructuredMode,
    StructuredOutputError,
    ToolCall,
    ToolSpec,
    ToolsUnsupported,
    TraceContext,
    Usage,
    compute_cost,
    excerpt,
)

if TYPE_CHECKING:
    from app.settings import Settings

CAP_TTL_S = 86400
MAX_RETRY_AFTER_S = 30.0
LADDER: tuple[StructuredMode, ...] = ("json_schema", "json_object", "text")
RETRYABLE = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)


def _mentions_tools(exc: openai.BadRequestError) -> bool:
    text = str(exc).lower()
    return "tool" in text or "function" in text


class LLMGateway:
    def __init__(
        self,
        roles: Mapping[Role, RoleConfig],
        recorder: CallRecorder,
        kv: KV,
        *,
        client_factory: Callable[[RoleConfig], openai.OpenAI] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        log_full: bool = False,
        max_attempts: int = 3,
        rng: random.Random | None = None,
        rate_card: RateCard | None = None,
    ) -> None:
        self._roles = dict(roles)
        self._card = rate_card or RateCard()
        self._recorder = recorder
        self._kv = kv
        self._factory = client_factory or _default_client
        self._clients: dict[Role, openai.OpenAI] = {}
        self._sleep = sleep
        self._log_full = log_full
        self._max_attempts = max(1, max_attempts)
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not crypto

    # --- helpers ---------------------------------------------------------------------------
    def _client(self, cfg: RoleConfig) -> openai.OpenAI:
        if cfg.role not in self._clients:
            self._clients[cfg.role] = self._factory(cfg)
        return self._clients[cfg.role]

    @staticmethod
    def _cap(cfg: RoleConfig, what: str) -> str:
        digest = hashlib.sha256(f"{cfg.base_url}|{cfg.model}".encode()).hexdigest()[:16]
        return f"llm:cap:{what}:{digest}"

    def _backoff(self, attempt: int, exc: Exception) -> float:
        response = getattr(exc, "response", None)
        header = response.headers.get("retry-after") if response is not None else None
        if header is not None:
            try:
                return min(MAX_RETRY_AFTER_S, max(0.0, float(header)))
            except ValueError:
                pass
        return float(0.5 * 2**attempt + self._rng.uniform(0, 0.25))

    def _with_retries[T](self, fn: Callable[[], T]) -> T:
        for attempt in range(self._max_attempts):
            try:
                return fn()
            except RETRYABLE as exc:
                if attempt == self._max_attempts - 1:
                    raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
                self._sleep(self._backoff(attempt, exc))
        raise AssertionError("unreachable")

    def _record(
        self,
        cfg: RoleConfig,
        trace: TraceContext,
        usage: Usage,
        started: float,
        status: Literal["ok", "error"],
        error: str | None,
        mode: StructuredMode | None,
        request: Any,
        response: str,
    ) -> int:
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._recorder.record(
            LLMCallRecord(
                trace=trace,
                role=cfg.role,
                model=cfg.model,
                provider_host=cfg.provider_host,
                usage=usage,
                cost_usd=compute_cost(cfg, usage) if status == "ok" else None,
                credits=credits_for(cfg.role, usage, self._card) if status == "ok" else None,
                latency_ms=latency_ms,
                status=status,
                error=error[:2000] if error else None,
                structured_mode=mode,
                request_excerpt=excerpt(json.dumps(request, default=str), self._log_full),
                response_excerpt=excerpt(response, self._log_full),
            )
        )
        return latency_ms

    @staticmethod
    def _usage(resp: Any) -> Usage:
        u = getattr(resp, "usage", None)
        if u is None:
            return Usage()
        details = getattr(u, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) or 0
        return Usage(
            int(u.prompt_tokens or 0),
            int(cached),
            int(getattr(u, "completion_tokens", 0) or 0),
        )

    @staticmethod
    def _prepare(
        messages: list[Message], mode: StructuredMode | None, model: type[BaseModel] | None
    ) -> tuple[list[Message], dict[str, Any]]:
        extra: dict[str, Any] = {}
        msgs = list(messages)
        if model is None or mode is None:
            return msgs, extra
        if mode == "json_schema":
            extra["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": model.__name__[:64],
                    "schema": strict_json_schema(model),
                    "strict": True,
                },
            }
        else:
            msgs = [*msgs, {"role": "system", "content": schema_instruction(model)}]
            if mode == "json_object":
                extra["response_format"] = {"type": "json_object"}
        return msgs, extra

    def _request(
        self,
        cfg: RoleConfig,
        msgs: list[Message],
        extra: dict[str, Any],
        tools: list[ToolSpec] | None,
        max_tokens: int,
        trace: TraceContext,
        mode: StructuredMode | None,
    ) -> tuple[Any, int]:
        """One logical request (with transport retries). Raises ``BadRequestError`` for 400s so
        callers can step down the ladder; other failures become ``LLMError`` subclasses."""
        use_max_tokens = bool(self._kv.get(self._cap(cfg, "maxtok")))
        token_param = "max_tokens" if use_max_tokens else "max_completion_tokens"
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "messages": msgs,
            token_param: max_tokens,
            **extra,
        }
        tools_no_effort = bool(tools) and bool(self._kv.get(self._cap(cfg, "tools_effort_none")))
        if tools:
            kwargs["tools"] = tools
            if tools_no_effort:
                kwargs["reasoning_effort"] = "none"
        started = time.perf_counter()
        try:
            resp = self._with_retries(lambda: self._client(cfg).chat.completions.create(**kwargs))
        except openai.BadRequestError as exc:
            self._record(cfg, trace, Usage(), started, "error", str(exc), mode, kwargs, "")
            if not use_max_tokens and "max_completion_tokens" in str(exc):
                self._kv.set(self._cap(cfg, "maxtok"), "1", ex=CAP_TTL_S)
                return self._request(cfg, msgs, extra, tools, max_tokens, trace, mode)
            if tools and not tools_no_effort and "reasoning_effort" in str(exc):
                self._kv.set(self._cap(cfg, "tools_effort_none"), "1", ex=CAP_TTL_S)
                return self._request(cfg, msgs, extra, tools, max_tokens, trace, mode)
            raise
        except ProviderUnavailable as exc:
            self._record(cfg, trace, Usage(), started, "error", str(exc), mode, kwargs, "")
            raise
        except openai.OpenAIError as exc:  # 401/403/404/422, bad JSON from the provider, ...
            msg = f"{type(exc).__name__}: {exc}"
            self._record(cfg, trace, Usage(), started, "error", msg, mode, kwargs, "")
            raise LLMError(msg) from exc
        latency = self._record(
            cfg, trace, self._usage(resp), started, "ok", None, mode, kwargs, resp.model_dump_json()
        )
        return resp, latency

    @staticmethod
    def _parse(
        content: str, mode: StructuredMode, model: type[BaseModel]
    ) -> tuple[BaseModel | None, str]:
        raw = extract_json_object(content) if mode == "text" else content.strip()
        if not raw:
            return None, "no JSON object found in the reply"
        try:
            return model.model_validate_json(raw), ""
        except ValidationError as exc:
            return None, str(exc)[:1500]

    def _result(
        self,
        cfg: RoleConfig,
        resp: Any,
        parsed: BaseModel | None,
        mode: StructuredMode | None,
        latency_ms: int,
        earlier: Usage | None = None,
    ) -> LLMResult:
        """``earlier``: usage of prior successful calls of the same ``complete()`` (validation
        retry), so the result's usage/cost cover every billed call."""
        msg = resp.choices[0].message
        usage = self._usage(resp) + (earlier or Usage())
        calls = [
            ToolCall(c.id, c.function.name, c.function.arguments) for c in (msg.tool_calls or [])
        ]
        return LLMResult(
            content=msg.content,
            parsed=parsed,
            tool_calls=calls,
            usage=usage,
            cost_usd=compute_cost(cfg, usage),
            model=cfg.model,
            structured_mode=mode,
            latency_ms=latency_ms,
            credits=credits_for(cfg.role, usage, self._card),
        )

    # --- public API ------------------------------------------------------------------------
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
        cfg = self._roles[role]
        if tools and self._kv.get(self._cap(cfg, "notools")):
            raise ToolsUnsupported(f"{cfg.model} does not support tool calling")

        def call(
            msgs: list[Message], extra: dict[str, Any], mode: StructuredMode | None
        ) -> tuple[Any, int]:
            try:
                return self._request(cfg, msgs, extra, tools, max_output_tokens, trace, mode)
            except openai.BadRequestError as exc:
                if tools and _mentions_tools(exc):
                    self._kv.set(self._cap(cfg, "notools"), "1", ex=CAP_TTL_S)
                    raise ToolsUnsupported(str(exc)) from exc
                raise

        if response_model is None:
            msgs, extra = self._prepare(messages, None, None)
            try:
                resp, latency = call(msgs, extra, None)
            except openai.BadRequestError as exc:
                raise LLMError(f"BadRequestError: {exc}") from exc
            return self._result(cfg, resp, None, None, latency)

        cached = self._kv.get(self._cap(cfg, "mode"))
        ladder = LADDER[LADDER.index(cached) :] if cached in LADDER else LADDER
        last_error: Exception | None = None
        for mode in ladder:
            msgs, extra = self._prepare(messages, mode, response_model)
            try:
                resp, latency = call(msgs, extra, mode)
            except openai.BadRequestError as exc:
                last_error = exc
                continue
            content = resp.choices[0].message.content or ""
            parsed, err = self._parse(content, mode, response_model)
            earlier: Usage | None = None
            if parsed is None:
                earlier, first_latency = self._usage(resp), latency
                retry = [
                    *msgs,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"Your previous reply was invalid: {err}. "
                        "Reply again with only a valid JSON object.",
                    },
                ]
                try:
                    resp, latency = call(retry, extra, mode)
                except openai.BadRequestError as exc:
                    raise StructuredOutputError(f"retry rejected: {exc}") from exc
                latency += first_latency
                content = resp.choices[0].message.content or ""
                parsed, err = self._parse(content, mode, response_model)
                if parsed is None:
                    raise StructuredOutputError(err)
            self._kv.set(self._cap(cfg, "mode"), mode, ex=CAP_TTL_S)
            return self._result(cfg, resp, parsed, mode, latency, earlier)
        raise StructuredOutputError(f"provider rejected every structured-output mode: {last_error}")

    def embed(self, texts: list[str], trace: TraceContext) -> list[list[float]]:
        return self.embed_metered(texts, trace).vectors

    def embed_metered(self, texts: list[str], trace: TraceContext) -> EmbedResult:
        """``embed`` plus the call's usage/cost, for per-review/per-chat totals."""
        cfg = self._roles["embed"]
        kwargs: dict[str, Any] = {"model": cfg.model, "input": texts}
        if cfg.dimensions:
            kwargs["dimensions"] = cfg.dimensions
        summary = {"model": cfg.model, "n": len(texts)}
        started = time.perf_counter()
        try:
            resp = self._with_retries(lambda: self._client(cfg).embeddings.create(**kwargs))
        except ProviderUnavailable as exc:
            self._record(cfg, trace, Usage(), started, "error", str(exc), None, summary, "")
            raise
        except openai.OpenAIError as exc:
            msg = f"{type(exc).__name__}: {exc}"
            self._record(cfg, trace, Usage(), started, "error", msg, None, summary, "")
            raise LLMError(msg) from exc
        usage = Usage(input_tokens=int(resp.usage.prompt_tokens or 0))
        self._record(cfg, trace, usage, started, "ok", None, None, summary, "")
        return EmbedResult(
            [list(d.embedding) for d in sorted(resp.data, key=lambda d: d.index)],
            usage,
            compute_cost(cfg, usage),
            cfg.model,
            credits_for(cfg.role, usage, self._card),
        )


def _default_client(cfg: RoleConfig) -> openai.OpenAI:
    # The gateway owns retries; the SDK's own retries are disabled.
    return openai.OpenAI(
        base_url=cfg.base_url, api_key=cfg.api_key or "unset", max_retries=0, timeout=120.0
    )


def build_gateway(settings: Settings) -> LLMGateway:
    import redis

    from app.billing.pricing import rate_card
    from app.db import make_sync_engine, sync_session_factory
    from app.kv import RedisKV
    from app.llm.metering import SqlCallRecorder
    from app.llm.types import role_configs

    return LLMGateway(
        role_configs(settings),
        SqlCallRecorder(sync_session_factory(make_sync_engine(settings.database_url))),
        RedisKV(redis.Redis.from_url(settings.redis_url, decode_responses=True)),
        log_full=settings.llm_log_full,
        rate_card=rate_card(settings),
    )
