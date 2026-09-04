"""Structured logging setup.

Every log line is a dict, so production issues can be filtered by `case_id`,
`claim_line_id`, or `request_id` rather than grepped out of prose (NFR-5).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, level: str = "INFO", json_logs: bool = False) -> None:
    """Configure structlog and the stdlib root logger. Safe to call once at startup."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for `name`."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
