"""
Tools :: Utils :: Serialization
===============================

Safe, stdlib-only serialization routines used by adapters, caches and logs.

The design goal is that no layer should raise on unexpected values while
round-tripping data: every produce function normalizes via ``default=str``
and every parse function is defensive.  A complementary ``compact`` helper
keeps payload sizes small for telemetry and cache keys.
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Any, Optional

__all__ = [
    "to_json",
    "to_json_bytes",
    "from_json",
    "to_json_str",
    "from_json_bytes",
    "to_json_compact",
    "json_default",
    "to_base64",
    "from_base64",
    "is_serializable",
]


def json_default(value: Any) -> Any:
    """JSON fallback for non-serializable objects (datetimes, bytes)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)


def to_json(value: Any, *, indent: Optional[int] = None, **kwargs: Any) -> str:
    """Serialize any value to JSON without raising on exotic nodes."""
    return json.dumps(value, indent=indent, default=json_default, **kwargs)


def to_json_str(value: Any, **kwargs: Any) -> str:
    """Alias of :func:`to_json`; explicit single-call convenience."""
    return to_json(value, **kwargs)


def to_json_bytes(value: Any, **kwargs: Any) -> bytes:
    """UTF-8 bytes form of :func:`to_json` suitable for body upload."""
    return to_json(value, **kwargs).encode("utf-8")


def to_json_compact(value: Any) -> str:
    """Compact, separator-less serialization for cache keys and wire bodies."""
    return json.dumps(value, separators=(",", ":"), default=json_default)


def from_json(data: Any, *, default: Any = None) -> Any:
    """Parse JSON text/bytes with a safe default (never raises)."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    if not isinstance(data, str) or not data.strip():
        return default
    try:
        return json.loads(data)
    except (TypeError, ValueError):
        return default


def from_json_bytes(data: bytes, *, default: Any = None) -> Any:
    """Parse JSON from UTF-8 bytes."""
    return from_json(data, default=default)


def to_base64(data: Any) -> str:
    """Encode UTF-8 bytes of a string (or raw bytes) to base64."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(bytes(data)).decode("ascii")


def from_base64(data: str) -> bytes:
    """Decode a base64 string back to bytes."""
    return base64.b64decode(data.encode("ascii"))


def is_serializable(value: Any) -> bool:
    """True when the value survives a JSON round-trip unchanged in shape."""
    try:
        json.dumps(value, default=json_default)
        return True
    except (TypeError, ValueError):
        return False