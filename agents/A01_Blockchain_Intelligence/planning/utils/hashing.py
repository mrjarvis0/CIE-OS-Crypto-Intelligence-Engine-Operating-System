"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.hashing

Purpose:
    Content hashing infrastructure for the planning subsystem.

Hashes are used for plan/task fingerprints, cache keys, deduplication,
integrity checks, and graph snapshot comparison -- never for passwords.

All object hashing is based on canonical JSON to guarantee
deterministic results across runs and processes.
"""

from __future__ import annotations

import hashlib
import hmac
import zlib

from pathlib import Path
from typing import Any

from .constants import DEFAULT_HASH_ALGORITHM, DEFAULT_HASH_CHUNK_BYTES
from .serialization import canonical_json_bytes

# ==============================================================================
# ALGORITHM REGISTRY
# ==============================================================================

_ALGORITHM_FACTORIES = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
    "sha3_256": hashlib.sha3_256,
    "blake2b": hashlib.blake2b,
    "blake2s": hashlib.blake2s,
}

# Algorithms that are fast but NOT collision/cryptographically secure.
# They remain useful for checksums and cheap deduplication keys, but must
# never be used for security-sensitive integrity or authentication.
NON_SECURITY_ALGORITHMS: frozenset[str] = frozenset({"md5", "sha1"})


def supported_algorithms() -> tuple[str, ...]:
    """Return names of supported hash algorithms."""
    return tuple(_ALGORITHM_FACTORIES.keys())


def _new_hasher(
    algorithm: str,
    *,
    usedforsecurity: bool | None = None,
) -> Any:
    """
    Create a hasher for the given algorithm.

    ``usedforsecurity`` defaults to False for md5/sha1 so FIPS-mode
    systems permit their use for non-security checksums.
    """

    factory = _ALGORITHM_FACTORIES.get(algorithm)

    if factory is None:
        raise ValueError(
            f"Unsupported hash algorithm: {algorithm}. "
            f"Supported: {supported_algorithms()}"
        )

    if usedforsecurity is None:
        usedforsecurity = algorithm not in NON_SECURITY_ALGORITHMS

    try:
        return factory(usedforsecurity=usedforsecurity)
    except TypeError:
        return factory()


# ==============================================================================
# PRIMITIVE HASHES
# ==============================================================================


def hash_bytes(
    data: bytes,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    usedforsecurity: bool | None = None,
) -> str:
    """Return hex digest of raw bytes."""
    hasher = _new_hasher(algorithm, usedforsecurity=usedforsecurity)
    hasher.update(data)
    return hasher.hexdigest()


def hash_text(
    text: str,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    usedforsecurity: bool | None = None,
) -> str:
    """Return hex digest of a UTF-8 string."""
    return hash_bytes(
        text.encode("utf-8"),
        algorithm=algorithm,
        usedforsecurity=usedforsecurity,
    )


def hash_object(
    data: Any,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    usedforsecurity: bool | None = None,
) -> str:
    """Return hex digest of an arbitrary object via canonical JSON."""
    return hash_bytes(
        canonical_json_bytes(data),
        algorithm=algorithm,
        usedforsecurity=usedforsecurity,
    )


def hash_stream(
    stream: Any,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    chunk_size: int = DEFAULT_HASH_CHUNK_BYTES,
    usedforsecurity: bool | None = None,
) -> str:
    """
    Stream an open binary handle and return its hex digest.

    Accepts any file-like object exposing ``read()`` (bytes). Memory stays
    O(chunk_size) regardless of stream length.
    """

    hasher = _new_hasher(algorithm, usedforsecurity=usedforsecurity)

    while chunk := stream.read(chunk_size):
        hasher.update(chunk)

    return hasher.hexdigest()


def hash_file(
    path: str | Path,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    chunk_size: int = DEFAULT_HASH_CHUNK_BYTES,
    usedforsecurity: bool | None = None,
) -> str:
    """
    Stream a file and return its hex digest.

    Uses fixed-size chunks (64 KiB by default) so memory usage stays
    O(1) regardless of file size.
    """

    with Path(path).open("rb") as handle:
        return hash_stream(
            handle,
            algorithm=algorithm,
            chunk_size=chunk_size,
            usedforsecurity=usedforsecurity,
        )


def hash_lines(
    lines: list[str],
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
    usedforsecurity: bool | None = None,
) -> str:
    """
    Return a hash of a list of text lines.

    The exact line order is significant; duplicate lines are preserved.
    Useful for fingerprints of ordered rule/policy lists.
    """

    payload = "".join(f"{line}\n" for line in lines)

    return hash_text(
        payload,
        algorithm=algorithm,
        usedforsecurity=usedforsecurity,
    )


def crc32(data: bytes) -> str:
    """Return CRC32 checksum as an 8-character hex string."""
    return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")


# ==============================================================================
# FINGERPRINTS
# ==============================================================================


def fingerprint(
    data: Any,
    *,
    namespace: str = "obj",
    algorithm: str = DEFAULT_HASH_ALGORITHM,
) -> str:
    """
    Produce a namespaced content fingerprint.

    Examples
    --------
        fingerprint({"a": 1}, namespace="plan") -> "plan_<hex>"
    """

    digest = hash_object(data, algorithm=algorithm)
    return f"{namespace}_{digest}"


def plan_fingerprint(plan: Any, **kwargs: Any) -> str:
    """Fingerprint a plan object."""
    return fingerprint(plan, namespace="plan", **kwargs)


def task_fingerprint(task: Any, **kwargs: Any) -> str:
    """Fingerprint a task object."""
    return fingerprint(task, namespace="task", **kwargs)


def graph_fingerprint(graph: Any, **kwargs: Any) -> str:
    """Fingerprint a graph structure."""
    return fingerprint(graph, namespace="graph", **kwargs)


def config_fingerprint(config: Any, **kwargs: Any) -> str:
    """Fingerprint a configuration object."""
    return fingerprint(config, namespace="config", **kwargs)


def state_fingerprint(state: Any, **kwargs: Any) -> str:
    """Fingerprint a state snapshot."""
    return fingerprint(state, namespace="state", **kwargs)


# ==============================================================================
# INTEGRITY HELPERS
# ==============================================================================


def hmac_hex(
    key: bytes,
    data: bytes,
    *,
    algorithm: str = "sha256",
) -> str:
    """Return HMAC hex digest for integrity verification."""
    digest = hmac.new(
        key,
        data,
        digestmod=algorithm,
    )
    return digest.hexdigest()


def hmac_verify(
    key: bytes,
    data: bytes,
    expected: str,
    *,
    algorithm: str = "sha256",
) -> bool:
    """Verify an HMAC digest using a timing-safe comparison."""
    actual = hmac_hex(key, data, algorithm=algorithm)
    return hmac.compare_digest(actual, expected)


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "supported_algorithms",
    "NON_SECURITY_ALGORITHMS",
    "hash_bytes",
    "hash_text",
    "hash_object",
    "hash_stream",
    "hash_file",
    "hash_lines",
    "crc32",
    "fingerprint",
    "plan_fingerprint",
    "task_fingerprint",
    "graph_fingerprint",
    "config_fingerprint",
    "state_fingerprint",
    "hmac_hex",
    "hmac_verify",
]
