"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.schemas.base

Purpose:
    Shared foundation for planning schema objects.

Provides the schema error hierarchy, the canonical schema version,
and timestamp helpers used by every planning schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = 1


class SchemaError(Exception):
    """
    Base class for all planning schema failures.
    """


class SchemaValidationError(SchemaError):
    """
    Raised when a schema object fails validation.
    """


class SchemaSerializationError(SchemaError):
    """
    Raised when a schema object cannot be (de)serialized.
    """


def _now() -> datetime:
    """Return the current UTC-aware timestamp."""
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any, field_name: str) -> datetime:
    """
    Coerce an ISO-8601 string or datetime into an aware UTC datetime.

    Raises
    ------
    SchemaValidationError
        When the value cannot be parsed.
    """

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SchemaValidationError(
                f"{field_name}: invalid ISO-8601 timestamp {value!r}"
            ) from exc

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    raise SchemaValidationError(
        f"{field_name}: expected datetime or ISO-8601 string, got {type(value).__name__}"
    )


def _to_iso(value: datetime | None) -> str | None:
    """Serialize a datetime to ISO-8601, or None."""
    if value is None:
        return None
    return value.isoformat()


def schema_to_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of a mapping as a plain dict."""
    return dict(payload)
