"""
Tools :: Utils :: Hashing
=========================

Consistent, stdlib-only hashing helpers used by the Tools subsystem for
checksum validation, cache keys, deduplication, content addressing and
integrity verification.

Every helper accepts ``algorithm`` -- ``sha256`` is the default; ``sha512``
and others are supported through :mod:`hashlib`.  Where the security-sensitive
comparison is needed, functions use :func:`hmac.compare_digest` so timing
attacks are not exposed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

__all__ = [
    "hash_bytes",
    "hash_text",
    "hash_file",
    "hash_struct",
    "checksum",
    "verify_checksum",
    "fingerprint",
    "constant_time_compare",
    "new_hmac",
    "deterministic_key",
    "verify_signature",
]


def hash_bytes(data: bytes, algorithm: str = "sha256") -> str:
    """Hex digest of a bytes payload."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes or bytearray")
    return hashlib.new(algorithm, bytes(data)).hexdigest()


def hash_text(data: str, algorithm: str = "sha256", encoding: str = "utf-8") -> str:
    """Hex digest of a text payload encoded using ``encoding``."""
    return hashlib.new(algorithm, str(data).encode(encoding)).hexdigest()


def hash_file(path: str, algorithm: str = "sha256", chunk_size: int = 65536) -> str:
    """
    Streaming digest of a file, never loading the whole payload into memory.

    Suitable for large artifacts (packages, downloads, backups).  Raises
    :class:`FileNotFoundError` if the file is missing.
    """
    digest = hashlib.new(algorithm)
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_struct(
    data: Any,
    algorithm: str = "sha256",
    *,
    sort_keys: bool = True,
    separators: tuple = (",", ":"),
) -> str:
    """
    Deterministic hash of arbitrary structured data.

    ``sort_keys`` guarantees stability across dict orderings; unknown objects
    are stringified via ``default=str`` so callers never trip on exotic types.
    This is the canonical content-addressing primitive for cache keys and
    request deduplication.
    """
    try:
        payload = json.dumps(data, sort_keys=sort_keys, default=str, separators=separators)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        payload = repr(data)
    return hashlib.new(algorithm, payload.encode("utf-8", "replace")).hexdigest()


def checksum(data: bytes, algorithm: str = "sha256") -> str:
    """Short 16-hex-char checksum of binary payload."""
    return hash_bytes(data, algorithm)[:16]


def verify_checksum(data: bytes, expected: str, algorithm: str = "sha256") -> bool:
    """Constant-time check of ``expected`` against the payload digest.

    Accepts both full digests and short checksums (the :func:`checksum`
    16-hex-char prefix); the expected value is compared against a
    same-length prefix of the actual digest.
    """
    actual = hash_bytes(data, algorithm).lower()
    expected = expected.strip().lower()
    if len(expected) != len(actual):
        actual = actual[: len(expected)]
    return constant_time_compare(actual, expected)


def fingerprint(parts: Any, algorithm: str = "sha256") -> str:
    """
    Stable fingerprint over one or more values.

    When ``parts`` is a collection its items are serialized together with a
    record separator so that distinct boundaries hash distinctly.  Scalars are
    coerced through :func:`hash_struct` semantics for stable cross-module keys.
    """
    if isinstance(parts, (list, tuple)):
        payload = "\x1e".join(
            json.dumps(p, sort_keys=True, default=str) for p in parts
        )
        return hashlib.new(algorithm, payload.encode("utf-8", "replace")).hexdigest()
    if isinstance(parts, dict) or parts is None or isinstance(parts, (bool, int, float, str)):
        return hash_struct(parts, algorithm)
    return hash_struct({"value": parts}, algorithm)


def constant_time_compare(left: str, right: str) -> bool:
    """Compare strings without short-circuiting and without leakage."""
    return hmac.compare_digest(left.encode("utf-8", "replace"), right.encode("utf-8", "replace"))


def new_hmac(key: bytes, data: bytes, algorithm: str = "sha256") -> str:
    """HMAC-SHA* digest of ``data`` keyed by ``key`` (returns hex)."""
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("key must be bytes or bytearray")
    return hmac.new(bytes(key), bytes(data), algorithm).hexdigest()


def deterministic_key(*parts: Any, algorithm: str = "sha256") -> str:
    """
    Build a stable composite key for caches and routing lookups.

    Each part contributes one fingerprint joined with ``/``; the ordering of
    the whole call matters, so ``deterministic_key("a", "bc")`` differs from
    ``deterministic_key("ab", "c")``.
    """
    return "/".join(fingerprint(part, algorithm) for part in parts)


def verify_signature(data: bytes, signature: str, key: bytes, algorithm: str = "sha256") -> bool:
    """
    Verify an HMAC signature over ``data`` in constant time.

    ``key`` must hold the shared secret bytes; the ``signature`` may be hex.
    This is the canonical signature check for manifests and packages.
    """
    expected = new_hmac(key, data, algorithm)
    return constant_time_compare(expected, signature.strip().lower())