"""`make llm-smoke`: one metered call through the gateway (spec §16 Phase 1)."""

import argparse
import json
from typing import Any, cast

from pydantic import BaseModel

from app.llm.gateway import LLMGateway, build_gateway
from app.llm.types import LLMError, Role, TraceContext
from app.settings import get_settings


class SmokeReply(BaseModel):
    ok: bool
    message: str


def run_smoke(gateway: LLMGateway, role: Role = "cheap") -> dict[str, Any]:
    if role == "embed":
        vecs = gateway.embed(["hello from HootPR"], TraceContext())
        return {"role": role, "dimensions": len(vecs[0])}
    res = gateway.complete(
        role,
        [
            {"role": "system", "content": "You are the HootPR health check."},
            {
                "role": "user",
                "content": "Reply with ok=true and a friendly message of at most 12 words.",
            },
        ],
        response_model=SmokeReply,
        max_output_tokens=200,
        trace=TraceContext(),
    )
    parsed = cast(SmokeReply, res.parsed)
    return {
        "role": role,
        "model": res.model,
        "structured_mode": res.structured_mode,
        "input_tokens": res.usage.input_tokens,
        "cached_tokens": res.usage.cached_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": str(res.cost_usd) if res.cost_usd is not None else None,
        "latency_ms": res.latency_ms,
        "reply": parsed.model_dump(),
    }


def main(argv: list[str] | None = None, *, gateway: LLMGateway | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send one metered request through the LLM gateway")
    parser.add_argument("--role", choices=["review", "cheap", "embed"], default="cheap")
    args = parser.parse_args(argv)
    gw = gateway or build_gateway(get_settings())
    try:
        print(json.dumps(run_smoke(gw, args.role), indent=2))
    except LLMError as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
