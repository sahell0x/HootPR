"""structlog JSON logging with contextvar correlation ids (spec §11.2)."""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET_KEY = re.compile(r"(token|secret|password|authorization|api_key|cookie)", re.IGNORECASE)


def _redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Never log secrets: blank values of keys that look like credentials."""
    for key in list(event_dict):
        if _SECRET_KEY.search(key) and event_dict[key] is not None:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str) -> None:
    lvl = logging.getLevelName(level.upper())
    if not isinstance(lvl, int):
        lvl = logging.INFO
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=lvl, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
