"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.helpers

Purpose:
    Generic helpers used throughout the intelligence layer.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("a01.intelligence.utils")


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    """
    Constrain a value to the inclusive [lower, upper] range.
    """
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def now_utc() -> datetime:
    """
    Return the current UTC time.
    """
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """
    Generate a new prefixed UUID4 identifier.
    """
    return f"{prefix}-{uuid.uuid4().hex}"


async def retry_async(
    coro: Callable[[], Awaitable[object]],
    *,
    attempts: int = 3,
    delay_seconds: float = 1.0,
    backoff: float = 2.0,
    timeout_seconds: float | None = None,
) -> object:
    """
    Retry an async callable with exponential backoff.

    Re-encapsulates non-asyncio exceptions with the attempt number as
    context and never swallows the final failure silently.

    Parameters
    ----------
    coro
        Zero-argument async callable to invoke.
    attempts
        Maximum number of attempts.
    delay_seconds
        Base delay before the first retry.
    backoff
        Multiplier applied to the delay after each failure.
    timeout_seconds
        Optional per-attempt timeout; when exceeded the attempt is
        treated as a failure and retried.

    Returns
    -------
    object
        The successful return value of the callable.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    delay = delay_seconds
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            if timeout_seconds is None:
                return await coro()
            return await asyncio.wait_for(coro(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning(
                "attempt %d/%d timed out after %.1fs",
                attempt,
                attempts,
                timeout_seconds or 0.0,
            )
        except Exception as exc:  # noqa: BLE001 - retry wrapper boundary
            last_error = exc
            logger.warning(
                "attempt %d/%d failed: %s",
                attempt,
                attempts,
                exc,
            )

        if attempt < attempts:
            await asyncio.sleep(delay)
            delay *= backoff

    assert last_error is not None
    raise RuntimeError(f"operation failed after {attempts} attempts") from last_error


async def run_with_timeout(
    coro: Awaitable[object],
    timeout_seconds: float,
) -> object:
    """
    Run an awaitable under a hard timeout, raising on expiry.
    """
    return await asyncio.wait_for(coro, timeout=timeout_seconds)


def parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    """
    Parse an ISO-8601 string (or pass through a datetime) into a
    timezone-aware UTC datetime, returning None on failure.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def age_seconds(value: datetime | None, reference: datetime | None = None) -> float | None:
    """
    Return the age of a datetime in seconds relative to a reference
    (defaults to now). Returns None for a None input.
    """
    if value is None:
        return None
    base = reference or now_utc()
    return max(0.0, (base - value).total_seconds())


def is_within(
    value: datetime | None,
    window: timedelta,
    reference: datetime | None = None,
) -> bool:
    """
    Return True if ``value`` falls within ``window`` of the reference.
    """
    if value is None:
        return False
    base = reference or now_utc()
    return abs(base - value) <= window
