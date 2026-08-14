"""
Memory Time Utilities

TTL parsing, expiry checks, and timestamp helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class TimeError(Exception):
    pass

_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_ttl(value: str | int | float | timedelta) -> timedelta:
    """
    Parse a TTL from a duration string ('5m', '2h'), a number of
    seconds, or a timedelta.
    """
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        if value < 0:
            raise TimeError("ttl must be non-negative.")
        return timedelta(seconds=float(value))
    text = str(value).strip().lower()
    if not text:
        raise TimeError("ttl cannot be empty.")
    unit = text[-1]
    if unit not in _UNIT_SECONDS:
        raise TimeError(f"unknown ttl unit '{unit}'.")
    try:
        amount = float(text[:-1])
    except ValueError as exc:
        raise TimeError(f"invalid ttl '{value}'.") from exc
    if amount < 0:
        raise TimeError("ttl must be non-negative.")
    return timedelta(seconds=amount * _UNIT_SECONDS[unit])


def ttl_seconds(value: str | int | float | timedelta) -> int:
    return int(parse_ttl(value).total_seconds())


def expires_at(
    ttl: str | int | float | timedelta,
    now: datetime | None = None,
) -> datetime:
    """
    Compute an expiry timestamp given a TTL.
    """
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + parse_ttl(ttl)


def is_expired(
    expiry: datetime | None,
    now: datetime | None = None,
) -> bool:
    """
    True when the expiry timestamp is in the past.
    """
    if expiry is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return current >= expiry


def iso_timestamp(now: datetime | None = None) -> str:
    """
    ISO-8601 UTC timestamp string.
    """
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.isoformat()
