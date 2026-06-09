"""Configure structlog with stable JSON output."""

from __future__ import annotations

import logging

import structlog

_STANDARD_LOG_FIELDS = ("timestamp", "level", "logger", "event")


def _order_log_fields(
    logger: object, method_name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    """Keep high-signal fields first and custom fields deterministic."""
    ordered = {}

    for key in _STANDARD_LOG_FIELDS:
        if key in event_dict:
            ordered[key] = event_dict.pop(key)

    for key in sorted(event_dict):
        ordered[key] = event_dict[key]

    return ordered


def configure_logging(verbose: bool = False) -> None:
    """Configure stdlib logging and structlog JSON output.

    Args:
        verbose: Whether to emit debug-level log events.
    """
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(format="%(message)s", level=level, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            _order_log_fields,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
