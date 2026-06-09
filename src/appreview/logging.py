"""Logging configuration for appreview-insight."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

# structlog processor type aliases
_StructlogLogger = object  # structlog uses Any internally for logger


def _mask_secrets(
    logger: _StructlogLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Mask API keys and JWTs in log records."""
    sensitive_keys = {"api_key", "token", "jwt", "authorization", "private_key", "secret"}
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in sensitive_keys):
            val = str(event_dict[key])
            if len(val) >= 8:
                event_dict[key] = f"****{val[-4:]}"
            else:
                event_dict[key] = "****"
    return event_dict


def configure_logging(
    level: str = "INFO",
    json_format: bool = False,
) -> None:
    """Configure structlog for the application.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        json_format: If True, output JSON Lines format for log aggregation.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _mask_secrets,
        structlog.processors.StackInfoRenderer(),
    ]

    if json_format:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance.

    Args:
        name: Logger name (usually __name__).

    Returns:
        A bound structlog logger.
    """
    return structlog.get_logger(name)  # type: ignore[return-value]
