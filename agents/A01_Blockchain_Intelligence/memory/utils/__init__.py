"""
Memory Utils Package

Cross-cutting utilities: key generation, hashing, time, validation,
serialization, batching, retry, logging, and tag converters.
"""

from __future__ import annotations

from memory.utils.batching import (
    BatchError,
    batched,
    chunks,
    flatten,
    partition,
    windows,
)
from memory.utils.hashing import (
    HashError,
    KeyError,
    composite_key,
    content_key,
    fingerprint,
    namespaced_key,
    sanitize,
    short_hash,
    stable_hash,
    value_hash,
)
from memory.utils.logging import get_logger, log_error, log_op
from memory.utils.retry import RetryError, retry, retry_async
from memory.utils.serialization import (
    ConvertError,
    SerializationError,
    build_tags,
    decode_importance,
    decode_memory_type,
    decode_priority,
    dict_to_entry,
    encode_importance,
    encode_memory_type,
    encode_priority,
    entry_to_dict,
    from_json,
    to_json,
)
from memory.utils.time import (
    TimeError,
    expires_at,
    is_expired,
    iso_timestamp,
    parse_ttl,
    ttl_seconds,
)
from memory.utils.validation import (
    ValidationError,
    normalize_tags,
    require_key,
    require_tags,
    require_value,
    validate_namespace,
    valid_key,
    valid_tags,
)

__all__ = [
    "BatchError",
    "ConvertError",
    "HashError",
    "KeyError",
    "RetryError",
    "SerializationError",
    "TimeError",
    "ValidationError",
    "batched",
    "build_tags",
    "chunks",
    "composite_key",
    "content_key",
    "decode_importance",
    "decode_memory_type",
    "decode_priority",
    "dict_to_entry",
    "encode_importance",
    "encode_memory_type",
    "encode_priority",
    "entry_to_dict",
    "expires_at",
    "fingerprint",
    "flatten",
    "from_json",
    "get_logger",
    "is_expired",
    "iso_timestamp",
    "log_error",
    "log_op",
    "namespaced_key",
    "normalize_tags",
    "parse_ttl",
    "partition",
    "require_key",
    "require_tags",
    "require_value",
    "retry",
    "retry_async",
    "sanitize",
    "short_hash",
    "stable_hash",
    "to_json",
    "ttl_seconds",
    "validate_namespace",
    "valid_key",
    "valid_tags",
    "value_hash",
    "windows",
]
