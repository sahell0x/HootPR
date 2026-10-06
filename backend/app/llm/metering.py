"""Per-call metering into llm_calls (spec §4.2 Metering)."""

from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.llm.types import LLMCallRecord
from app.models import LlmCall


class CallRecorder(Protocol):
    def record(self, rec: LLMCallRecord) -> None: ...


class InMemoryRecorder:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    def record(self, rec: LLMCallRecord) -> None:
        self.records.append(rec)


class SqlCallRecorder:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def record(self, rec: LLMCallRecord) -> None:
        with self._sf() as s:
            s.add(
                LlmCall(
                    org_id=rec.trace.org_id,
                    review_id=rec.trace.review_id,
                    chat_id=rec.trace.chat_id,
                    task_id=rec.trace.task_id,
                    role=rec.role,
                    model=rec.model,
                    provider_host=rec.provider_host,
                    input_tokens=rec.usage.input_tokens,
                    cached_tokens=rec.usage.cached_tokens,
                    output_tokens=rec.usage.output_tokens,
                    cost_usd=rec.cost_usd,
                    latency_ms=rec.latency_ms,
                    status=rec.status,
                    error=rec.error,
                    structured_mode=rec.structured_mode,
                    request_excerpt=rec.request_excerpt,
                    response_excerpt=rec.response_excerpt,
                    stage=rec.trace.stage,
                    credits=rec.credits,
                )
            )
            s.commit()
