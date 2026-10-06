"""``@hootpr`` finishing-touch commands (spec §8 table, §10.1).

The chat parser recognises the phrase; this module turns it into a :class:`FinishingRequest`:
which finishing touch, which recipe, and how the result is delivered. An optional trailing
word picks the delivery (CodeRabbit parity): ``commit`` commits on the PR branch, ``stacked pr``
/ ``pr`` / ``mr`` opens a stacked PR/MR that targets the PR branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config.schema import CustomRecipe, HootPRConfig

Kind = Literal[
    "docstrings",
    "unit_tests",
    "autofix",
    "simplify",
    "fix_ci",
    "ci_analysis",
    "merge_conflict",
    "custom",
]
Delivery = Literal["commit", "stacked_pr", "comment"]

PHRASES: tuple[tuple[str, Kind], ...] = (
    ("generate docstrings", "docstrings"),
    ("generate docstring", "docstrings"),
    ("add docstrings", "docstrings"),
    ("generate unit tests", "unit_tests"),
    ("generate unit test", "unit_tests"),
    ("generate tests", "unit_tests"),
    ("autofix", "autofix"),
    ("auto-fix", "autofix"),
    ("auto fix", "autofix"),
    ("simplify", "simplify"),
    ("fix ci", "fix_ci"),
    ("fix-ci", "fix_ci"),
    ("fixci", "fix_ci"),
    ("resolve merge conflicts", "merge_conflict"),
    ("resolve merge conflict", "merge_conflict"),
    ("resolve conflicts", "merge_conflict"),
)
_BY_LENGTH = sorted(PHRASES, key=lambda p: len(p[0]), reverse=True)
RUN_PREFIX = "run "
DEFAULT_DELIVERY: dict[Kind, Delivery] = {
    "docstrings": "stacked_pr",
    "unit_tests": "stacked_pr",
    "simplify": "stacked_pr",
    "custom": "stacked_pr",
    "autofix": "commit",
    "fix_ci": "commit",
    "merge_conflict": "commit",
    "ci_analysis": "comment",
}
_DELIVERY_WORDS: dict[str, Delivery] = {
    "commit": "commit",
    "in branch": "commit",
    "on branch": "commit",
    "commit to branch": "commit",
    "stacked pr": "stacked_pr",
    "stacked mr": "stacked_pr",
    "stacked": "stacked_pr",
    "pr": "stacked_pr",
    "mr": "stacked_pr",
}
LABELS: dict[Kind, str] = {
    "docstrings": "Generate docstrings",
    "unit_tests": "Generate unit tests",
    "autofix": "Autofix",
    "simplify": "Simplify",
    "fix_ci": "Fix CI",
    "ci_analysis": "CI failure analysis",
    "merge_conflict": "Resolve merge conflict",
    "custom": "Custom recipe",
}


@dataclass(frozen=True)
class FinishingRequest:
    kind: Kind
    delivery: Delivery
    recipe: str | None = None


def _split_delivery(rest: str) -> tuple[str, Delivery | None]:
    """``rest`` minus a trailing delivery word, and that word's delivery."""
    for word in sorted(_DELIVERY_WORDS, key=len, reverse=True):
        if rest == word:
            return "", _DELIVERY_WORDS[word]
        if rest.endswith(" " + word):
            return rest[: -len(word) - 1].strip(), _DELIVERY_WORDS[word]
    return rest, None


def parse_finishing(phrase: str) -> FinishingRequest | None:
    """``phrase``: the normalized command text after the mention (lowercase, single spaces)."""
    phrase = " ".join(phrase.lower().split()).rstrip(".!?").strip(" ,:")
    if phrase.startswith(RUN_PREFIX):
        name, delivery = _split_delivery(phrase[len(RUN_PREFIX) :].strip())
        name = name.strip("`'\" ")
        if not name:
            return None
        return FinishingRequest("custom", delivery or DEFAULT_DELIVERY["custom"], name)
    for text, kind in _BY_LENGTH:
        if phrase == text or phrase.startswith(text + " "):
            rest, delivery = _split_delivery(phrase[len(text) :].strip())
            if rest:
                return None  # "simplify this function please" is a chat question
            return FinishingRequest(kind, delivery or DEFAULT_DELIVERY[kind])
    return None


def find_recipe(cfg: HootPRConfig, name: str) -> CustomRecipe | None:
    want = " ".join(name.lower().split())
    for recipe in cfg.reviews.finishing_touches.custom:
        if " ".join(recipe.name.lower().split()) == want:
            return recipe
    return None


def enabled(cfg: HootPRConfig, kind: Kind) -> bool:
    ft = cfg.reviews.finishing_touches
    return {
        "docstrings": ft.docstrings.enabled,
        "unit_tests": ft.unit_tests.enabled,
        "autofix": ft.autofix.enabled,
        "simplify": ft.simplify.enabled,
        "fix_ci": ft.fix_ci.enabled,
        "ci_analysis": ft.ci_analysis.enabled,
        "merge_conflict": ft.merge_conflicts.enabled,
        "custom": True,
    }[kind]


CONFIG_KEYS: dict[Kind, str] = {
    "docstrings": "reviews.finishing_touches.docstrings.enabled",
    "unit_tests": "reviews.finishing_touches.unit_tests.enabled",
    "autofix": "reviews.finishing_touches.autofix.enabled",
    "simplify": "reviews.finishing_touches.simplify.enabled",
    "fix_ci": "reviews.finishing_touches.fix_ci.enabled",
    "ci_analysis": "reviews.finishing_touches.ci_analysis.enabled",
    "merge_conflict": "reviews.finishing_touches.merge_conflicts.enabled",
    "custom": "reviews.finishing_touches.custom",
}
