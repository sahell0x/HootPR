import pytest

from app.chat.commands import COMMANDS, has_mention, parse_comment, spec_for
from app.chat.identity import BotIdentity, bot_identity, is_bot_author, primary_mention
from app.settings import Settings

ID = BotIdentity(
    usernames=frozenset({"hootpr-test[bot]"}),
    mentions=frozenset({"hootpr-test", "hootpr-test[bot]"}),
)


@pytest.mark.parametrize(
    ("body", "cmd"),
    [
        ("@hootpr-test review", "review"),
        ("@HootPR-Test   Full   Review!", "full_review"),
        ("@hootpr-test pause", "pause"),
        ("@hootpr-test resume.", "resume"),
        ("@hootpr-test resolve", "resolve"),
        ("@hootpr-test approve", "approve"),
        ("@hootpr-test summary", "summary"),
        ("@hootpr-test generate sequence diagram", "sequence_diagram"),
        ("@hootpr-test configuration", "configuration"),
        ("@hootpr-test config", "configuration"),
        ("@hootpr-test help", "help"),
        ("@hootpr-test rate limit", "rate_limit"),
        ("@hootpr-test rate-limit", "rate_limit"),
        ("@hootpr-test limits", "rate_limit"),
        ("@hootpr-test quota", "rate_limit"),
        ("@hootpr-test ignore", "ignore"),
        ("@hootpr-test[bot] review", "review"),
        ("@hootpr-test review\nthanks!", "review"),
    ],
)
def test_commands(body: str, cmd: str) -> None:
    p = parse_comment(body, ID)
    assert p.mentioned and p.command == cmd


@pytest.mark.parametrize(
    "phrase",
    [
        "generate configuration",
    ],
)
def test_later_phase_commands_are_recognized(phrase: str) -> None:
    p = parse_comment(f"@hootpr-test {phrase}", ID)
    assert p.command == "unsupported" and p.phrase == phrase


def test_free_form_question() -> None:
    p = parse_comment("Hey @hootpr-test, why is this query slow?", ID)
    assert p.mentioned and p.command is None
    assert p.text == "Hey , why is this query slow?"


def test_free_form_question_that_starts_like_a_command() -> None:
    p = parse_comment("@hootpr-test review this function please, is it safe?", ID)
    assert p.mentioned and p.command is None


def test_offsets_survive_code_before_the_mention() -> None:
    p = parse_comment("`x = 1` and ```\ny\n``` then @hootpr-test help", ID)
    assert p.command == "help"
    assert p.text == "`x = 1` and ```\ny\n``` then  help"


@pytest.mark.parametrize(
    "body",
    [
        "`@hootpr-test review`",
        "```\n@hootpr-test review\n```",
        "> @hootpr-test review\n\nquoting the bot",
        "mail me@hootpr-test.com",
        "@hootpr-testing review",
        "no mention at all",
    ],
)
def test_not_a_mention(body: str) -> None:
    p = parse_comment(body, ID)
    assert not p.mentioned and p.command is None
    assert not has_mention(body, ID)


def test_no_identity_never_matches() -> None:
    p = parse_comment("@hootpr review", BotIdentity(frozenset(), frozenset()))
    assert not p.mentioned


def test_identity_per_provider(settings: Settings) -> None:
    gh = bot_identity(settings, "github", None)
    assert gh.mentions == {"hootpr-test", "hootpr-test[bot]"}
    assert gh.usernames == {"hootpr-test[bot]"}
    gl = bot_identity(settings, "gitlab", "HootPR-Bot")
    assert gl.mentions == gl.usernames == {"hootpr-bot"}
    assert primary_mention(gh) == "@hootpr-test" and primary_mention(gl) == "@hootpr-bot"
    assert primary_mention(bot_identity(settings, "gitlab", None)) == "@hootpr"


def test_bot_author_detection() -> None:
    assert is_bot_author(ID, "HootPR-Test[bot]")
    assert is_bot_author(ID, "dependabot[bot]")
    assert not is_bot_author(ID, "bob")


def test_every_command_has_help_and_cost() -> None:
    names = {c.name for c in COMMANDS}
    assert names == {
        "review",
        "full_review",
        "pause",
        "resume",
        "resolve",
        "approve",
        "summary",
        "sequence_diagram",
        "configuration",
        "help",
        "rate_limit",
        "security_review",
        "ignore",
        "finishing_touch",
        "ignore_pre_merge",
        "create_issue",
    }
    costs = {c.name: c.cost for c in COMMANDS}
    assert costs["review"] == costs["full_review"] == "review"
    assert costs["summary"] == costs["sequence_diagram"] == "chat"
    assert {n for n, c in costs.items() if c == "free"} == {
        "pause",
        "resume",
        "resolve",
        "approve",
        "configuration",
        "help",
        "rate_limit",
        "ignore",
        "ignore_pre_merge",
        "security_review",
    }
    assert {c.name for c in COMMANDS if c.top_level_only} == {"resolve", "approve"}
    assert all(c.help for c in COMMANDS)
    assert spec_for("help").phrases == ("help",)
