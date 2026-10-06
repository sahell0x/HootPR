"""Non-agentic fallback when the provider has no tool calling (spec §4.2, §7.9)."""

from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import TraceContext
from app.review.agent import task_prompt
from app.review.findings import Candidate
from app.review.llm import LLMLike
from app.review.prompts import PROFILE_NOTES, SINGLE_PASS_SYSTEM, system_prompt
from app.review.schemas import PlanTask, SinglePassFindings


def single_pass(
    llm: LLMLike, task: PlanTask, ordinal: int, pack: str, cfg: HootPRConfig, *, trace: TraceContext
) -> list[Candidate]:
    system = system_prompt(f"{SINGLE_PASS_SYSTEM}\n\n{PROFILE_NOTES[cfg.reviews.profile]}", cfg)
    res = llm.complete(
        "review",
        [
            {"role": "system", "content": system},
            {"role": "user", "content": task_prompt(task, ordinal, pack)},
        ],
        response_model=SinglePassFindings,
        max_output_tokens=6000,
        trace=trace,
    )
    return [f.to_candidate() for f in cast(SinglePassFindings, res.parsed).findings]
