import json

import pytest
import structlog

from app.logging import configure_logging, get_logger


def test_json_logs_include_bound_context(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.contextvars.bind_contextvars(review_id="r1")
    try:
        get_logger("t").info("hello", org_id="o1")
    finally:
        structlog.contextvars.clear_contextvars()
    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "hello"
    assert data["review_id"] == "r1"
    assert data["org_id"] == "o1"
    assert data["level"] == "info"
    assert "timestamp" in data


def test_level_filters_debug(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    get_logger("t").info("quiet")
    assert "quiet" not in capsys.readouterr().out


def test_unknown_level_falls_back_to_info(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("nonsense")
    get_logger("t").info("shown")
    assert "shown" in capsys.readouterr().out


def test_secret_looking_keys_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("t").info("auth", access_token="gho_x", api_key="sk-1", password="p", user="bob")
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert data["access_token"] == "[redacted]"
    assert data["api_key"] == "[redacted]"
    assert data["password"] == "[redacted]"
    assert data["user"] == "bob"
