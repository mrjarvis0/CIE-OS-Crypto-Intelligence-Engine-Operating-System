"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.serialization

Purpose:
    Serialization infrastructure for the planning subsystem.

Provides canonical JSON (deterministic, hash-friendly), dict conversion,
optional compression, an allow-listed pickle gate, and a type-marked
safe serializer for structured payload exchange.

Design rules:
    - Canonical JSON is the default interchange format.
    - Pickle is internal-only and requires an explicit allow flag.
    - Optional msgpack/yaml are imported gracefully (stdlib-first).
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import pickle
import zlib

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .constants import SerializationFormat

# ==============================================================================
# OPTIONAL BACKENDS
# ==============================================================================


def _optional_msgpack() -> Any:
    """Return msgpack module or None."""
    try:
        import msgpack  # type: ignore
    except ImportError:
        return None
    return msgpack


def _optional_yaml() -> Any:
    """Return yaml module or None."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    return yaml


# ==============================================================================
# DEFAULT HANDLER
# ==============================================================================


def _default_json_handler(value: Any) -> Any:
    """
    Convert non-JSON-safe values into JSON-safe representations.

    Supports datetimes, dates, enums, dataclasses, Paths, sets, and bytes.
    """

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value):
        return asdict(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (set, frozenset)):
        return sorted(
            _default_json_handler(item) for item in value
        )

    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")

    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


# ==============================================================================
# CANONICAL JSON
# ==============================================================================


def canonical_json(data: Any) -> str:
    """
    Produce deterministic canonical JSON.

    Guarantees:
        - Keys sorted recursively
        - Compact separators
        - ASCII-safe escaping
        - Stable ordering for hashing / diffing

    Examples
    --------
        canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    """

    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_default_json_handler,
    )


def canonical_json_bytes(data: Any) -> bytes:
    """Return canonical JSON encoded as UTF-8 bytes."""
    return canonical_json(data).encode("utf-8")


# ==============================================================================
# JSON HELPERS
# ==============================================================================


def json_dumps(
    data: Any,
    *,
    pretty: bool = False,
    ensure_ascii: bool = False,
) -> str:
    """Serialize data to JSON string with sensible defaults."""

    if pretty:
        return json.dumps(
            data,
            indent=2,
            sort_keys=True,
            ensure_ascii=ensure_ascii,
            default=_default_json_handler,
        )

    return json.dumps(
        data,
        ensure_ascii=ensure_ascii,
        default=_default_json_handler,
    )


def json_loads(data: str | bytes) -> Any:
    """Deserialize JSON string or bytes."""
    return json.loads(data)


# ==============================================================================
# SPEC-FACING ALIASES
# ==============================================================================

# Short, conventional aliases matching the standard to_X/from_X naming.


def to_json(data: Any, **kwargs: Any) -> str:
    """Serialize to a JSON string (alias of :func:`json_dumps`)."""
    return json_dumps(data, **kwargs)


def from_json(data: str | bytes, **kwargs: Any) -> Any:
    """Deserialize a JSON string or bytes (alias of :func:`json_loads`)."""
    return json_loads(data, **kwargs)


def to_bytes(data: Any, **kwargs: Any) -> bytes:
    """Serialize to canonical JSON bytes."""
    return canonical_json_bytes(data, **kwargs)


def from_bytes(data: bytes, **kwargs: Any) -> Any:
    """Deserialize canonical JSON bytes."""
    _ = kwargs
    return json_loads(data)


# ==============================================================================
# PICKLE HELPERS (INTERNAL ONLY)
# ==============================================================================


def pickle_dumps(data: Any) -> bytes:
    """Serialize to pickle bytes (highest protocol)."""
    return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)


def pickle_loads(
    data: bytes,
    *,
    allow_pickle: bool = False,
) -> Any:
    """
    Deserialize pickle bytes.

    Raises
    ------
    PermissionError
        When allow_pickle is False.
    """

    if not allow_pickle:
        raise PermissionError(
            "Pickle deserialization is disabled. "
            "Pass allow_pickle=True to enable."
        )

    return pickle.loads(data)


# ==============================================================================
# DICT CONVERSION
# ==============================================================================


def to_dict(
    data: Any,
    *,
    deep: bool = True,
) -> dict[str, Any]:
    """Convert a dataclass/dict into a plain dict."""

    if is_dataclass(data):
        result = asdict(data) if deep else {
            field_: getattr(data, field_)
            for field_ in data.__dataclass_fields__
        }
        return result

    if isinstance(data, dict):
        return data

    raise TypeError(
        f"Cannot convert {type(data).__name__} to dict"
    )


def from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of a dict as plain data."""
    return json.loads(canonical_json(data))


# ==============================================================================
# COMPRESSION
# ==============================================================================


def compress_zlib(data: bytes, *, level: int = 6) -> bytes:
    """Compress bytes with zlib."""
    return zlib.compress(data, level=level)


def decompress_zlib(data: bytes) -> bytes:
    """Decompress zlib bytes."""
    return zlib.decompress(data)


def compress_gzip(data: bytes, *, level: int = 6) -> bytes:
    """Compress bytes with gzip."""
    buffer = io.BytesIO()

    with gzip.GzipFile(
        fileobj=buffer,
        mode="wb",
        compresslevel=level,
    ) as handle:
        handle.write(data)

    return buffer.getvalue()


def decompress_gzip(data: bytes) -> bytes:
    """Decompress gzip bytes."""
    return gzip.decompress(data)


# ==============================================================================
# MSGPACK / YAML (OPTIONAL)
# ==============================================================================


def msgpack_dumps(data: Any) -> bytes:
    """Serialize to MessagePack bytes when available."""
    msgpack = _optional_msgpack()

    if msgpack is None:
        raise ImportError(
            "msgpack is not installed. Install 'msgpack' to use this format."
        )

    return msgpack.packb(
        json.loads(canonical_json(data)),
        use_bin_type=True,
    )


def msgpack_loads(
    data: bytes,
    *,
    allow_pickle: bool = False,
) -> Any:
    """Deserialize MessagePack bytes when available."""
    _ = allow_pickle
    msgpack = _optional_msgpack()

    if msgpack is None:
        raise ImportError(
            "msgpack is not installed. Install 'msgpack' to use this format."
        )

    return msgpack.unpackb(
        data,
        raw=False,
        strict_map_key=False,
    )


def yaml_dumps(data: Any) -> str:
    """Serialize to YAML when available."""
    yaml = _optional_yaml()

    if yaml is None:
        raise ImportError(
            "yaml is not installed. Install 'pyyaml' to use this format."
        )

    return yaml.safe_dump(
        json.loads(canonical_json(data)),
        sort_keys=True,
        default_flow_style=False,
    )


def yaml_loads(data: str) -> Any:
    """Deserialize YAML when available."""
    yaml = _optional_yaml()

    if yaml is None:
        raise ImportError(
            "yaml is not installed. Install 'pyyaml' to use this format."
        )

    return yaml.safe_load(data)


# ==============================================================================
# SAFE SERIALIZER
# ==============================================================================

_TYPE_PREFIX_JSON: str = "json:"

_TYPE_PREFIX_PICKLE: str = "pickle:"


class SafeSerializer:
    """
    Type-marked serializer for structured payload exchange.

    JSON payloads are always allowed. Pickle payloads require an
    explicit allow flag, matching enterprise agent frameworks.
    """

    def __init__(
        self,
        *,
        allow_pickle: bool = False,
        compress: bool = False,
    ) -> None:
        self._allow_pickle = allow_pickle
        self._compress = compress

    # ------------------------------------------------------------------
    # Serialize
    # ------------------------------------------------------------------

    def serialize(self, data: Any) -> str:
        """Serialize data into a type-marked string payload."""

        if self._allow_pickle:
            return self._serialize_pickle(data)

        return self._serialize_json(data)

    def _serialize_json(self, data: Any) -> str:
        payload = canonical_json(data).encode("utf-8")

        if self._compress:
            payload = compress_gzip(payload)

        return _TYPE_PREFIX_JSON + base64.b64encode(payload).decode("ascii")

    def _serialize_pickle(self, data: Any) -> str:
        payload = pickle_dumps(data)

        if self._compress:
            payload = compress_gzip(payload)

        return _TYPE_PREFIX_PICKLE + base64.b64encode(payload).decode("ascii")

    # ------------------------------------------------------------------
    # Deserialize
    # ------------------------------------------------------------------

    def deserialize(self, payload: str) -> Any:
        """Deserialize a type-marked string payload."""

        if not isinstance(payload, str) or not payload:
            raise ValueError("payload must be a non-empty string")

        if payload.startswith(_TYPE_PREFIX_JSON):
            return self._deserialize_json(payload)

        if payload.startswith(_TYPE_PREFIX_PICKLE):
            return self._deserialize_pickle(payload)

        raise ValueError(f"Unknown payload prefix: {payload[:8]}...")

    def _deserialize_json(self, payload: str) -> Any:
        raw = base64.b64decode(payload[len(_TYPE_PREFIX_JSON) :])

        if self._compress:
            raw = decompress_gzip(raw)

        return json.loads(raw.decode("utf-8"))

    def _deserialize_pickle(self, payload: str) -> Any:
        if not self._allow_pickle:
            raise PermissionError(
                "Pickle deserialization is disabled for this serializer."
            )

        raw = base64.b64decode(payload[len(_TYPE_PREFIX_PICKLE) :])

        if self._compress:
            raw = decompress_gzip(raw)

        return pickle_loads(raw, allow_pickle=True)


# ==============================================================================
# FORMAT DISPATCH
# ==============================================================================


def serialize(
    data: Any,
    fmt: SerializationFormat | str = SerializationFormat.JSON,
    *,
    allow_pickle: bool = False,
) -> Any:
    """
    Serialize data using the requested format.

    Returns str for JSON/YAML and bytes for msgpack/pickle.
    """

    format_name = (
        fmt.value if isinstance(fmt, SerializationFormat) else fmt
    )

    if format_name == SerializationFormat.JSON.value:
        return canonical_json(data)

    if format_name == SerializationFormat.MSGPACK.value:
        return msgpack_dumps(data)

    if format_name == SerializationFormat.YAML.value:
        return yaml_dumps(data)

    if format_name == SerializationFormat.PICKLE.value:
        if not allow_pickle:
            raise PermissionError(
                "Pickle serialization requires allow_pickle=True."
            )
        return pickle_dumps(data)

    if format_name == SerializationFormat.DICT.value:
        return json.loads(canonical_json(data))

    raise ValueError(f"Unsupported serialization format: {format_name}")


def deserialize(
    data: Any,
    fmt: SerializationFormat | str = SerializationFormat.JSON,
    *,
    allow_pickle: bool = False,
) -> Any:
    """Deserialize data produced by :func:`serialize`."""

    format_name = (
        fmt.value if isinstance(fmt, SerializationFormat) else fmt
    )

    if format_name == SerializationFormat.JSON.value:
        return json.loads(data)

    if format_name == SerializationFormat.MSGPACK.value:
        return msgpack_loads(data)

    if format_name == SerializationFormat.YAML.value:
        return yaml_loads(data)

    if format_name == SerializationFormat.PICKLE.value:
        return pickle_loads(data, allow_pickle=allow_pickle)

    if format_name == SerializationFormat.DICT.value:
        return data

    raise ValueError(f"Unsupported serialization format: {format_name}")


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "canonical_json",
    "canonical_json_bytes",
    "json_dumps",
    "json_loads",
    "to_json",
    "from_json",
    "to_bytes",
    "from_bytes",
    "pickle_dumps",
    "pickle_loads",
    "to_dict",
    "from_dict",
    "compress_zlib",
    "decompress_zlib",
    "compress_gzip",
    "decompress_gzip",
    "msgpack_dumps",
    "msgpack_loads",
    "yaml_dumps",
    "yaml_loads",
    "SafeSerializer",
    "serialize",
    "deserialize",
]
