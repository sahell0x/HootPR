from dataclasses import replace

import pytest

from app.config.schema import HootPRConfig
from app.review.rules import PrFacts, should_review

PR = PrFacts(
    title="Add feature",
    body="",
    author_username="alice",
    is_draft=False,
    base_ref="main",
    labels=(),
    paused=False,
    reviewed_commits_count=0,
)


def cfg(**auto: object) -> HootPRConfig:
    return HootPRConfig.model_validate({"reviews": {"auto_review": auto}})


def test_default_reviews() -> None:
    assert should_review(HootPRConfig(), PR, "auto", "main") is None


@pytest.mark.parametrize(
    ("pr", "config", "trigger", "reason"),
    [
        (
            replace(PR, body="please @hootpr ignore"),
            HootPRConfig(),
            "auto",
            "ignored_by_description",
        ),
        (
            replace(PR, body="Please @HootPR Ignore"),
            HootPRConfig(),
            "auto",
            "ignored_by_description",
        ),
        (replace(PR, paused=True), HootPRConfig(), "incremental", "paused"),
        (PR, cfg(enabled=False), "auto", "auto_review_disabled"),
        (PR, cfg(auto_incremental_review=False), "incremental", "incremental_disabled"),
        (replace(PR, is_draft=True), HootPRConfig(), "auto", "draft"),
        (replace(PR, title="WIP: stuff"), HootPRConfig(), "auto", "title_keyword"),
        (replace(PR, title="do not merge yet"), HootPRConfig(), "auto", "title_keyword"),
        (
            replace(PR, author_username="dependabot[bot]"),
            cfg(ignore_usernames=["dependabot[bot]"]),
            "auto",
            "ignored_user",
        ),
        (replace(PR, base_ref="release/1"), HootPRConfig(), "auto", "base_branch"),
        (
            replace(PR, labels=("skip-review",)),
            cfg(labels=["!skip-review"]),
            "auto",
            "label_excluded",
        ),
        (PR, cfg(labels=["review-me"]), "auto", "label_missing"),
        (PR, cfg(description_keyword="@review"), "auto", "description_keyword_missing"),
        (replace(PR, reviewed_commits_count=5), HootPRConfig(), "incremental", "auto_paused"),
    ],
)
def test_skip_reasons(pr: PrFacts, config: HootPRConfig, trigger: str, reason: str) -> None:
    assert should_review(config, pr, trigger, "main") == reason  # type: ignore[arg-type]


def test_allowed_variants() -> None:
    assert should_review(cfg(drafts=True), replace(PR, is_draft=True), "auto", "main") is None
    assert (
        should_review(
            cfg(base_branches=["release/.*"]), replace(PR, base_ref="release/1"), "auto", "main"
        )
        is None
    )
    assert (
        should_review(cfg(labels=["review-me"]), replace(PR, labels=("review-me",)), "auto", "main")
        is None
    )
    assert (
        should_review(
            cfg(auto_pause_after_reviewed_commits=0),
            replace(PR, reviewed_commits_count=50),
            "incremental",
            "main",
        )
        is None
    )
    assert (
        should_review(HootPRConfig(), replace(PR, reviewed_commits_count=5), "auto", "main") is None
    )


def test_invalid_base_branch_regex_falls_back_to_equality() -> None:
    assert (
        should_review(
            cfg(base_branches=["rel[ease"]), replace(PR, base_ref="rel[ease"), "auto", "main"
        )
        is None
    )


def test_commands_bypass_auto_rules_but_not_ignore() -> None:
    assert (
        should_review(cfg(enabled=False), replace(PR, is_draft=True), "command_review", "main")
        is None
    )
    assert (
        should_review(HootPRConfig(), replace(PR, body="@hootpr ignore"), "command_review", "main")
        == "ignored_by_description"
    )
