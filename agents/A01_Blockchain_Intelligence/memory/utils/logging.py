"""
Memory Logging Utilities

Structured logger factory for memory subsystems.
"""

from __future__ import annotations

import logging
from typing import Any

_PREFIX = "memory"


def get_logger(
    name: str,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Get a namespaced memory logger.
    """
    logger = logging.getLogger(f"{_PREFIX}.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s"
            )
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def log_error(
    logger: logging.Logger,
    message: str,
    exc: BaseException | None = None,
    **details: Any,
) -> None:
    suffix = ""
    if details:
        suffix = " " + " ".join(
            f"{key}={value}" for key, value in details.items()
        )
    if exc is not None:
        logger.error("%s%s (error=%s)", message, suffix, exc)
    else:
        logger.error("%s%s", message, suffix)


def log_op(
    logger: logging.Logger,
    operation: str,
    **details: Any,
) -> None:
    suffix = " ".join(
        f"{key}={value}" for key, value in details.items()
    )
    logger.info("op=%s %s", operation, suffix)
