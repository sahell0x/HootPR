from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.chat.replies import (
    RateLimitInfo,
    chat_marker,
    humanize_seconds,
    render_actions,
    render_chat_error,
    render_chat_out_of_credits,
    render_chat_rate_limited,
    render_chat_reply,
    render_configuration_reply,
    render_help,
    render_hint,
    render_rate_limit,
    render_unsupported,
    with_author,
)
from app.knowledge.base import LearningHit
from app.knowledge.learnings import AddedLearning


def test_actions_performed_block() -> None:
    body = render_actions("bob", ["Review triggered."], note="Incremental.")
    assert body == (
        "@bob\n\n<details>\n<summary>✅ Actions performed</summary>\n\n"
        "Review triggered.\n\n> Incremental.\n\n</details>"
    )
    assert render_actions("bob", ["Reviews paused."]) == (
        "@bob\n\n<details>\n<summary>✅ Actions performed</summary>\n\n"
        "Reviews paused.\n\n</details>"
    )


def test_help_lists_every_command_with_the_mention() -> None:
    body = render_help("@hootpr-test", "http://localhost:3000/schema/hootpr.v1.json")
    assert body.startswith("## HootPR commands")
    for phrase in (
        "review",
        "full review",
        "pause",
        "resume",
        "resolve",
        "approve",
        "summary",
        "generate sequence diagram",
        "configuration",
        "help",
        "rate limit",
    ):
        assert f"`@hootpr-test {phrase}`" in body
    assert "`@hootpr-test ignore`" in body and "PR description" in body
    assert "hootpr.v1.json" in body and "metered by AI usage" in body


def test_configuration_reply() -> None:
    body = render_configuration_reply(
        "bob", "# Effective\nlanguage: en-US\n", ["yaml invalid (line 2)"]
    )
    assert body.startswith("@bob ")
    assert "```yaml\n# Effective\nlanguage: en-US\n```" in body
    assert "- yaml invalid (line 2)" in body
    assert "Warnings" not in render_configuration_reply("bob", "a: 1\n", [])


def test_rate_limit_reply() -> None:
    info = RateLimitInfo(
        2,
        0,
        754,
        10,
        9,
        0,
        Decimal("1250.00"),
        Decimal("100"),
        Decimal("50"),
        "http://localhost:3000/o/acme/billing",
    )
    body = render_rate_limit("bob", info)
    assert body.startswith("@bob")
    assert "| Reviews | 0 of 2 | in 13m |" in body
    assert "| Chat replies | 9 of 10 | now |" in body
    assert "1,250 credits" in body and "about 100," in body and "/o/acme/billing" in body


def test_chat_limits_and_credits() -> None:
    body = render_chat_rate_limited("bob", 10, 120)
    assert body.startswith("@bob Chat rate limited") and "in 2m" in body
    assert "No credit was charged" in body
    oc = render_chat_out_of_credits("bob", Decimal("2"), Decimal("5"), "http://x/o/a/billing")
    assert oc.startswith("@bob") and "Out of credits" in oc
    assert "has 2 credits" in oc and "least 5 " in oc
    assert "hootpr:walkthrough" not in oc  # must never look like the walkthrough comment


def test_misc() -> None:
    assert humanize_seconds(0) == "now" and humanize_seconds(59) == "in 1m"
    assert humanize_seconds(3600) == "in 60m"
    assert chat_marker(UUID(int=1)) == "<!-- hootpr:chat:00000000-0000-0000-0000-000000000001 -->"
    assert "`autofix` is not available in HootPR yet" in render_unsupported("bob", "autofix")
    assert render_hint("bob", "Hi.") == "@bob Hi." == with_author("bob", "Hi.")


def test_render_chat_reply_sections() -> None:
    body = render_chat_reply(
        "bob",
        "Fair point.",
        [AddedLearning("1", "We use print() for CLI output.", "repo", None)],
        [LearningHit("2", "Prefer small functions", "repo", None, 0.8)],
        pr_ref="acme/web#7",
        location="src/login.py:2",
        now=datetime(2026, 9, 29, 10, tzinfo=UTC),
    )
    assert body.startswith("@bob Fair point.\n\n<details>\n<summary>✏️ Learnings added</summary>")
    assert (
        "Learnt from: bob\nPR: acme/web#7\nFile: src/login.py:2\nTimestamp: 2026-09-29T10:00:00Z"
        "\n\nLearning: We use print() for CLI output." in body
    )
    assert (
        "<summary>🧠 Learnings used</summary>" in body
        and "Learning: Prefer small functions" in body
    )
    assert (
        render_chat_reply("bob", "Hi", [], [], pr_ref="x#1", location=None, now=datetime.now(UTC))
        == "@bob Hi"
    )


def test_render_chat_reply_fences_cannot_be_broken_by_learning_text() -> None:
    body = render_chat_reply(
        "bob",
        "ok",
        [AddedLearning("1", "Use ``` fences\n</details> carefully", "repo", "src/**")],
        [],
        pr_ref="acme/web#7",
        location=None,
        now=datetime(2026, 9, 29, 10, tzinfo=UTC),
    )
    section = body.split("<summary>✏️ Learnings added</summary>", 1)[1]
    assert section.count("```") == 2 and "File:" not in section


def test_render_chat_error() -> None:
    assert render_chat_error("bob") == (
        "@bob HootPR hit an error while answering this. No credit was charged — please try "
        "again later."
    )


def test_configuration_reply_hardens_warnings() -> None:
    body = render_configuration_reply("bob", "a: 1\n", ["bad\n/merge\n@everyone <img src=x>"])
    assert "\n/merge" not in body and "@everyone" not in body and "<img" not in body


def test_with_author_puts_block_markdown_on_its_own_line() -> None:
    from app.chat.replies import with_author

    assert with_author("u", "```python\nx = 1\n```") == "@u\n\n```python\nx = 1\n```"
    assert with_author("u", "- a\n- b").startswith("@u\n\n- a")
    assert with_author("u", "Use `items[-1]`.") == "@u Use `items[-1]`."
