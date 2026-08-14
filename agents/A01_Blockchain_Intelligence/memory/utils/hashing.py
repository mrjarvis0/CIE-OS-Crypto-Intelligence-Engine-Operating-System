"""
Memory Hash Utilities

Stable content fingerprinting for deduplication and comparison, plus
deterministic key generation.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_.:-]")


class HashError(Exception):
    pass


def stable_hash(
    content: str,
    algorithm: str = "sha256",
) -> str:
    """
    Deterministic hash of a string, stable across runs.
    """
    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:
        raise HashError(f"unknown algorithm '{algorithm}'") from exc
    digest.update(content.encode("utf-8"))
    return digest.hexdigest()


def short_hash(
    content: str,
    length: int = 16,
) -> str:
    """
    Truncated stable hash suitable for keys.
    """
    return stable_hash(content)[:length]


def value_hash(
    value: Any,
    length: int = 16,
) -> str:
    """
    Hash of an arbitrary value using its repr.
    """
    return short_hash(repr(value), length=length)


def fingerprint(
    content: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Fingerprint combining content and optional metadata.
    """
    material = content
    if metadata:
        ordered = sorted(
            (str(k), repr(v)) for k, v in metadata.items()
        )
        material += "|" + "|".join(f"{k}={v}" for k, v in ordered)
    return stable_hash(material)


class KeyError(Exception):
    pass


def sanitize(key: str, replacement: str = "_") -> str:
    """
    Replace characters unsafe for memory keys.
    """
    return _INVALID_CHARS.sub(replacement, str(key))


def content_key(
    content: str,
    namespace: str = "default",
) -> str:
    """
    Deterministic key derived from content and namespace.
    """
    digest = hashlib.sha256(
        f"{namespace}::{content}".encode("utf-8")
    ).hexdigest()[:32]
    return f"content:{namespace}:{digest}"


def namespaced_key(
    key: str,
    namespace: str,
) -> str:
    """
    Prefix a key with a namespace.
    """
    return f"{namespace}:{sanitize(key)}"


def composite_key(*parts: Any) -> str:
    """
    Build a deterministic composite key from parts.
    """
    cleaned = [sanitize(str(part)) for part in parts if part is not None]
    if not cleaned:
        raise KeyError("composite_key requires at least one part.")
    digest = hashlib.sha256(
        "::".join(cleaned).encode("utf-8")
    ).hexdigest()[:16]
    return f"composite:{':'.join(cleaned)[:80]}:{digest}"


def encode_key(value: Any) -> str:
    """
    Encode an arbitrary value into a stable string key.
    """
    if isinstance(value, str):
        return value
    try:
        return repr(value)
    except Exception:
        return str(value)
