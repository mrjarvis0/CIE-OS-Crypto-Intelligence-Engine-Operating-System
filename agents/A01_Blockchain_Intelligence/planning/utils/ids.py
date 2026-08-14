"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.ids

Purpose:
    Identifier generation for the planning subsystem.

Supports multiple production ID formats:
    - UUID v4 (random)
    - UUID v7 (time-sortable, RFC 9562)
    - UUID v8 (custom, native in Python 3.14)
    - ULID (Crockford base32, time-sortable)
    - NanoID (URL-safe random, configurable)
    - Snowflake (64-bit time + worker + sequence)
    - Short ID
    - Deterministic hash ID

Includes a namespace manager, parser, validator, formatter, and a
collision checker.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

from dataclasses import dataclass
from typing import Any, Final

from .constants import (
    DEFAULT_ID_ALGORITHM,
    DEFAULT_ID_LENGTH,
    DEFAULT_SNOWFLAKE_SEQUENCE,
    DEFAULT_SNOWFLAKE_WORKER_ID,
    IdNamespace,
)
from .hashing import hash_object

# ==============================================================================
# CONSTANTS
# ==============================================================================

# Crockford base32 alphabet (excludes I, L, O, U).
_CROCKFORD_BASE32: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# NanoID URL-safe alphabet.
_NANOID_ALPHABET: Final[str] = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "_-"
)

# Short ID alphabet (unambiguous).
_SHORT_ALPHABET: Final[str] = (
    "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"
)

_SNOWFLAKE_EPOCH_MS: Final[int] = 1_700_000_000_000
_WORKER_BITS: Final[int] = 5
_SEQUENCE_BITS: Final[int] = 12
_MAX_SEQUENCE: Final[int] = (1 << _SEQUENCE_BITS) - 1
_MAX_WORKER_ID: Final[int] = (1 << _WORKER_BITS) - 1

# ULID timestamp field: first 10 Crockford base32 chars = 48 bits.
_ULID_TIMESTAMP_CHARS: Final[int] = 10

# Methods accepted by IDGenerator.generate_id().
_SUPPORTED_METHODS: Final[frozenset[str]] = frozenset(
    {"uuid4", "uuid7", "uuid8", "ulid", "nanoid", "snowflake", "short"}
)

# Reverse lookup for decoding Crockford base32 timestamps.
_CROCKFORD_DECODE: Final[dict[str, int]] = {
    char: index for index, char in enumerate(_CROCKFORD_BASE32)
}

# ==============================================================================
# GENERATORS
# ==============================================================================


def uuid4() -> str:
    """Return a random UUID v4 string."""
    return str(uuid.uuid4())


def uuid7() -> str:
    """Return a time-sortable UUID v7 string (RFC 9562)."""
    return str(uuid.uuid7())


def uuid8() -> str:
    """Return a custom UUID v8 string (native in Python 3.14)."""
    return str(uuid.uuid8())


def _encode_base32(data: bytes, length: int) -> str:
    """Encode bytes using Crockford base32 without padding."""
    bits = 0
    value = 0
    output: list[str] = []

    for byte in data:
        value = (value << 8) | byte
        bits += 8

        while bits >= 5:
            output.append(_CROCKFORD_BASE32[(value >> (bits - 5)) & 0x1F])
            bits -= 5

        value &= (1 << bits) - 1

    if bits > 0:
        output.append(_CROCKFORD_BASE32[(value << (5 - bits)) & 0x1F])

    return "".join(output)[:length]


def ulid() -> str:
    """Return a time-sortable ULID (26-char Crockford base32)."""
    timestamp_ms = int(time.time() * 1000)
    payload = (
        timestamp_ms.to_bytes(6, "big")
        + secrets.token_bytes(10)
    )
    return _encode_base32(payload, 26)


def nanoid(
    *,
    size: int = DEFAULT_ID_LENGTH,
    alphabet: str = _NANOID_ALPHABET,
) -> str:
    """
    Return a URL-safe NanoID.

    Parameters
    ----------
    size
        Output length (default 21, ~126 bits of entropy).

    alphabet
        Custom character alphabet.
    """

    if size <= 0:
        raise ValueError("nanoid size must be positive")

    return "".join(secrets.choice(alphabet) for _ in range(size))


class _SnowflakeGenerator:
    """
    Thread-safe Snowflake-style ID generator.

    64-bit layout: 41-bit timestamp + 5-bit worker + 12-bit sequence.
    """

    def __init__(
        self,
        *,
        worker_id: int = DEFAULT_SNOWFLAKE_WORKER_ID,
        sequence: int = DEFAULT_SNOWFLAKE_SEQUENCE,
    ) -> None:

        if not 0 <= worker_id <= _MAX_WORKER_ID:
            raise ValueError(
                f"worker_id must be between 0 and {_MAX_WORKER_ID}"
            )

        self._worker_id = worker_id
        self._sequence = sequence
        self._last_timestamp_ms = -1
        self._lock = threading.Lock()

    def generate(self) -> str:
        """Generate the next snowflake ID as a decimal string."""

        with self._lock:
            now_ms = int(time.time() * 1000)

            if now_ms < self._last_timestamp_ms:
                raise RuntimeError(
                    "Clock moved backwards; refusing to generate snowflake ID"
                )

            if now_ms == self._last_timestamp_ms:
                self._sequence = (self._sequence + 1) & _MAX_SEQUENCE

                if self._sequence == 0:
                    now_ms = self._wait_next_ms(self._last_timestamp_ms)
            else:
                self._sequence = 0

            self._last_timestamp_ms = now_ms

            timestamp = now_ms - _SNOWFLAKE_EPOCH_MS

            identifier = (
                (timestamp << (_WORKER_BITS + _SEQUENCE_BITS))
                | (self._worker_id << _SEQUENCE_BITS)
                | self._sequence
            )

            return str(identifier)

    @staticmethod
    def _wait_next_ms(last_timestamp_ms: int) -> int:
        now_ms = int(time.time() * 1000)

        while now_ms <= last_timestamp_ms:
            now_ms = int(time.time() * 1000)

        return now_ms


_snowflake_default = _SnowflakeGenerator()


def snowflake(
    *,
    worker_id: int = DEFAULT_SNOWFLAKE_WORKER_ID,
) -> str:
    """Return a snowflake ID using the shared or custom generator."""
    if worker_id == DEFAULT_SNOWFLAKE_WORKER_ID:
        return _snowflake_default.generate()

    return _SnowflakeGenerator(worker_id=worker_id).generate()


def short_id(
    *,
    size: int = 10,
    alphabet: str = _SHORT_ALPHABET,
) -> str:
    """Return a short, unambiguous, URL-safe random ID."""
    return "".join(secrets.choice(alphabet) for _ in range(size))


def deterministic_id(
    data: Any,
    *,
    namespace: str = "det",
    algorithm: str = "sha256",
) -> str:
    """
    Return a deterministic hash-based ID.

    The same input always produces the same ID, enabling plan
    deduplication and cache keys.
    """

    digest = hash_object(data, algorithm=algorithm)
    return f"{namespace}_{digest[:32]}"


# ==============================================================================
# NAMESPACE MANAGER
# ==============================================================================


def _generate_raw(
    algorithm: str = DEFAULT_ID_ALGORITHM,
    **kwargs: Any,
) -> str:
    """Generate an identifier without a namespace prefix."""

    if algorithm == "uuid4":
        return uuid4()
    if algorithm == "uuid7":
        return uuid7()
    if algorithm == "uuid8":
        return uuid8()
    if algorithm == "ulid":
        return ulid()
    if algorithm == "nanoid":
        return nanoid(**kwargs)
    if algorithm == "snowflake":
        return snowflake(**kwargs)
    if algorithm == "short":
        return short_id(**kwargs)

    raise ValueError(f"Unsupported ID algorithm: {algorithm}")


def generate(
    namespace: IdNamespace | str,
    *,
    algorithm: str = DEFAULT_ID_ALGORITHM,
    **kwargs: Any,
) -> str:
    """
    Generate an identifier scoped to a namespace.

    Examples
    --------
        generate(IdNamespace.TASK)      -> "task_01J..."
        generate(IdNamespace.PLAN)      -> "plan_01J..."
    """

    prefix = (
        namespace.value if isinstance(namespace, IdNamespace) else namespace
    )

    identifier = _generate_raw(algorithm, **kwargs)

    return f"{prefix}_{identifier}"


def generate_goal_id(**kwargs: Any) -> str:
    """Generate a goal identifier."""
    return generate(IdNamespace.GOAL, **kwargs)


def generate_objective_id(**kwargs: Any) -> str:
    """Generate an objective identifier."""
    return generate(IdNamespace.OBJECTIVE, **kwargs)


def generate_task_id(**kwargs: Any) -> str:
    """Generate a task identifier."""
    return generate(IdNamespace.TASK, **kwargs)


def generate_plan_id(**kwargs: Any) -> str:
    """Generate a plan identifier."""
    return generate(IdNamespace.PLAN, **kwargs)


def generate_execution_id(**kwargs: Any) -> str:
    """Generate an execution identifier."""
    return generate(IdNamespace.EXECUTION, **kwargs)


def generate_workflow_id(**kwargs: Any) -> str:
    """Generate a workflow identifier."""
    return generate(IdNamespace.WORKFLOW, **kwargs)


def generate_checkpoint_id(**kwargs: Any) -> str:
    """Generate a checkpoint identifier."""
    return generate(IdNamespace.CHECKPOINT, **kwargs)


def generate_route_id(**kwargs: Any) -> str:
    """Generate a routing decision identifier."""
    return generate(IdNamespace.ROUTE, **kwargs)


def generate_trace_id() -> str:
    """Generate a trace identifier."""
    return f"{IdNamespace.TRACE.value}_{uuid.uuid4().hex}"


def generate_correlation_id() -> str:
    """Generate a correlation identifier."""
    return uuid.uuid4().hex


# ==============================================================================
# PARSER / VALIDATOR / FORMATTER
# ==============================================================================


def parse_namespace(identifier: str) -> str | None:
    """Extract the namespace prefix from an identifier."""
    if "_" not in identifier:
        return None
    return identifier.split("_", 1)[0]


def strip_namespace(identifier: str) -> str:
    """Remove the namespace prefix, returning the raw identifier."""
    if "_" not in identifier:
        return identifier
    return identifier.split("_", 1)[1]


def validate_identifier(
    identifier: str,
    *,
    namespace: IdNamespace | str | None = None,
    min_length: int = 8,
) -> bool:
    """
    Validate a planning identifier.

    Parameters
    ----------
    identifier
        Identifier string to validate.

    namespace
        When provided, the identifier must carry this prefix.

    min_length
        Minimum total length.
    """

    if not isinstance(identifier, str) or not identifier:
        return False

    if len(identifier) < min_length:
        return False

    if namespace is not None:
        prefix = (
            namespace.value
            if isinstance(namespace, IdNamespace)
            else namespace
        )

        if not identifier.startswith(f"{prefix}_"):
            return False

    return True


def format_identifier(identifier: str) -> str:
    """Normalize an identifier to a canonical lowercase form."""
    return identifier.strip().lower()


# ==============================================================================
# TIMESTAMP PARSING
# ==============================================================================


def _decode_crockford(text: str) -> int:
    """Decode a Crockford base32 string into an integer."""
    value = 0

    for char in text:
        digit = _CROCKFORD_DECODE.get(char)

        if digit is None:
            raise ValueError(f"invalid Crockford base32 character: {char!r}")

        value = (value << 5) | digit

    return value


def _is_uuid_shape(text: str) -> bool:
    """Whether a string has the standard 8-4-4-4-12 UUID shape."""
    parts = text.split("-")
    return len(parts) == 5 and [len(part) for part in parts] == [8, 4, 4, 4, 12]


def _detect_time_algorithm(raw: str) -> str | None:
    """Detect the time-encoding of a raw identifier, if any."""
    if _is_uuid_shape(raw) and raw[14] == "7":
        return "uuid7"

    if len(raw) == 26 and all(char in _CROCKFORD_BASE32 for char in raw):
        return "ulid"

    if raw.isdigit() and len(raw) >= 17:
        return "snowflake"

    return None


def parse_timestamp(
    identifier: str,
    *,
    algorithm: str | None = None,
) -> float | None:
    """
    Extract the creation timestamp (epoch seconds) from a time-encoded ID.

    Supports UUID v7, ULID, and Snowflake identifiers. Namespace-prefixed
    identifiers (``goal_01J...``) are accepted and stripped automatically.

    Returns None when the identifier carries no recoverable timestamp.

    Examples
    --------
        parse_timestamp(generate(IdNamespace.TASK))   -> 1789... (float)
        parse_timestamp("abc")                        -> None
    """

    if not isinstance(identifier, str) or not identifier:
        return None

    raw = strip_namespace(identifier)

    detected = algorithm or _detect_time_algorithm(raw)

    if detected == "uuid7":
        if not _is_uuid_shape(raw):
            return None
        timestamp_ms = int(raw.replace("-", "")[:12], 16)
        return timestamp_ms / 1000.0

    if detected == "ulid":
        if len(raw) != 26 or any(char not in _CROCKFORD_BASE32 for char in raw):
            return None
        timestamp_ms = _decode_crockford(raw[:_ULID_TIMESTAMP_CHARS])
        return timestamp_ms / 1000.0

    if detected == "snowflake":
        if not raw.isdigit():
            return None
        timestamp_ms = (int(raw) >> (_WORKER_BITS + _SEQUENCE_BITS)) + _SNOWFLAKE_EPOCH_MS
        return timestamp_ms / 1000.0

    return None


# ==============================================================================
# CLASS API
# ==============================================================================


class IDGenerator:
    """
    Object-oriented identifier generator.

    Wraps the module-level functions behind a configurable instance:

    Examples
    --------
        generator = IDGenerator(namespace=IdNamespace.TASK, method="uuid7")

        task_id = generator.generate_id()

        if generator.validate_id(task_id):
            created = generator.parse_timestamp(task_id)
    """

    def __init__(
        self,
        *,
        method: str = DEFAULT_ID_ALGORITHM,
        namespace: IdNamespace | str | None = None,
        **kwargs: Any,
    ) -> None:

        if method not in _SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported ID method: {method}. "
                f"Supported: {sorted(_SUPPORTED_METHODS)}"
            )

        self.method = method
        self.namespace = namespace
        self._kwargs = dict(kwargs)

    def generate_id(self) -> str:
        """Generate a new identifier for this generator's configuration."""
        if self.namespace is None:
            return _generate_raw(self.method, **self._kwargs)

        return generate(
            self.namespace,
            algorithm=self.method,
            **self._kwargs,
        )

    def validate_id(
        self,
        identifier: str,
        *,
        min_length: int = 8,
    ) -> bool:
        """Validate an identifier against this generator's namespace."""
        if self.namespace is None:
            return validate_identifier(identifier, min_length=min_length)

        return validate_identifier(
            identifier,
            namespace=self.namespace,
            min_length=min_length,
        )

    def parse_timestamp(self, identifier: str) -> float | None:
        """Extract the creation timestamp of a time-encoded identifier."""
        return parse_timestamp(identifier, algorithm=self.method)


# ==============================================================================
# COLLISION CHECKER
# ==============================================================================


@dataclass(slots=True)
class CollisionReport:
    """
    Result of a collision check across generated identifiers.
    """

    total: int = 0

    unique: int = 0

    collisions: int = 0

    duplicate_ids: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.duplicate_ids is None:
            self.duplicate_ids = []

    @property
    def collision_rate(self) -> float:
        """Fraction of identifiers that collided."""
        if self.total == 0:
            return 0.0
        return self.collisions / self.total


def check_collisions(identifiers: list[str]) -> CollisionReport:
    """Detect duplicate identifiers in a collection."""
    seen: set[str] = set()
    duplicates: list[str] = []

    for identifier in identifiers:
        if identifier in seen:
            duplicates.append(identifier)
        seen.add(identifier)

    return CollisionReport(
        total=len(identifiers),
        unique=len(seen),
        collisions=len(duplicates),
        duplicate_ids=duplicates,
    )


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "uuid4",
    "uuid7",
    "uuid8",
    "ulid",
    "nanoid",
    "snowflake",
    "short_id",
    "deterministic_id",
    "generate",
    "generate_goal_id",
    "generate_objective_id",
    "generate_task_id",
    "generate_plan_id",
    "generate_execution_id",
    "generate_workflow_id",
    "generate_checkpoint_id",
    "generate_route_id",
    "generate_trace_id",
    "generate_correlation_id",
    "parse_namespace",
    "strip_namespace",
    "validate_identifier",
    "format_identifier",
    "parse_timestamp",
    "IDGenerator",
    "CollisionReport",
    "check_collisions",
]
