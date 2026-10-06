import pytest

from app.chat.commands import parse_comment
from app.chat.identity import BotIdentity
from app.config.schema import HootPRConfig
from app.finishing.commands import FinishingRequest, enabled, find_recipe, parse_finishing

IDENTITY = BotIdentity(frozenset({"hootpr[bot]"}), frozenset({"hootpr", "hootpr[bot]"}))


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("generate docstrings", FinishingRequest("docstrings", "stacked_pr")),
        ("generate docstrings commit", FinishingRequest("docstrings", "commit")),
        ("generate unit tests", FinishingRequest("unit_tests", "stacked_pr")),
        ("autofix", FinishingRequest("autofix", "commit")),
        ("autofix stacked pr", FinishingRequest("autofix", "stacked_pr")),
        ("auto-fix", FinishingRequest("autofix", "commit")),
        ("simplify", FinishingRequest("simplify", "stacked_pr")),
        ("fix-ci", FinishingRequest("fix_ci", "commit")),
        ("fix ci stacked mr", FinishingRequest("fix_ci", "stacked_pr")),
        ("resolve merge conflict", FinishingRequest("merge_conflict", "commit")),
        ("run changelog", FinishingRequest("custom", "stacked_pr", "changelog")),
        (
            "run add license headers commit",
            FinishingRequest("custom", "commit", "add license headers"),
        ),
        ("simplify this function please", None),
        ("run", None),
        ("review", None),
    ],
)
def test_parse_finishing(phrase: str, expected: FinishingRequest | None) -> None:
    assert parse_finishing(phrase) == expected


def test_parse_comment_routes_finishing_touches() -> None:
    p = parse_comment("@hootpr generate unit tests", IDENTITY)
    assert p.command == "finishing_touch" and p.phrase == "generate unit tests"
    assert parse_comment("@hootpr run changelog", IDENTITY).command == "finishing_touch"
    # still a chat question
    assert parse_comment("@hootpr simplify this please", IDENTITY).command is None
    # other unsupported commands keep their reply
    assert parse_comment("@hootpr generate configuration", IDENTITY).command == "unsupported"


def test_enabled_and_recipes() -> None:
    cfg = HootPRConfig.model_validate(
        {
            "reviews": {
                "finishing_touches": {
                    "unit_tests": {"enabled": False},
                    "custom": [{"name": "Changelog", "instructions": "Add a changelog entry."}],
                }
            }
        }
    )
    assert not enabled(cfg, "unit_tests") and enabled(cfg, "docstrings")
    recipe = find_recipe(cfg, "changelog")
    assert recipe is not None and recipe.name == "Changelog"
    assert find_recipe(cfg, "missing") is None
