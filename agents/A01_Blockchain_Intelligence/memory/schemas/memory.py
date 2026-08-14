"""
Memory Schema

Canonical data model and validation for memory entries. Provides a
versioned, serializable representation that complements (without
duplicating) the runtime ``MemoryEntry`` in ``memory.base.memory``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

SCHEMA_VERSION = 1
DEFAULT_NAMESPACE = "default"
DEFAULT_SOURCE = "runtime"


class SchemaError(Exception):
    """
    Base class for schema validation failures.
    """


class SchemaValidationError(SchemaError):
    """
    Raised when an entry fails schema validation.
    """


class MemoryKind(str, Enum):
    """
    Logical category of a memory entry.
    """

    FACT = "fact"
    EVENT = "event"
    PREFERENCE = "preference"
    DECISION = "decision"
    TASK = "task"
    MESSAGE = "message"
    KNOWLEDGE = "knowledge"
    UNKNOWN = "unknown"


class PriorityLevel(int, Enum):
    """
    Canonical priority scale.
    """

    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 100


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class MemorySchema:
    """
    Canonical memory entry data model.

    Fields:
        * Content, type, and namespace
        * Priority and expiry
        * Metadata and timestamps
    """

    key: str
    value: Any
    kind: MemoryKind = MemoryKind.UNKNOWN
    namespace: str = DEFAULT_NAMESPACE
    source: str = DEFAULT_SOURCE
    tags: list[str] = field(default_factory=list)
    priority: PriorityLevel = PriorityLevel.NORMAL
    confidence: float = 1.0
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    identifier: UUID = field(default_factory=uuid4)
    version: int = SCHEMA_VERSION

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.key or not self.key.strip():
            raise SchemaValidationError("key must be non-empty.")
        if len(self.key) > 257:
            raise SchemaValidationError("key must be at most 257 characters.")
        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaValidationError("confidence must be within [0, 1].")
        if not self.namespace or not self.namespace.strip():
            raise SchemaValidationError("namespace must be non-empty.")
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise SchemaValidationError("expires_at cannot precede created_at.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.version,
            "key": self.key,
            "value": self.value,
            "kind": self.kind.value,
            "namespace": self.namespace,
            "source": self.source,
            "tags": list(self.tags),
            "priority": self.priority.value,
            "confidence": self.confidence,
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at is not None else None
            ),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "identifier": str(self.identifier),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MemorySchema":
        try:
            expires = payload.get("expires_at")
            schema = cls(
                key=str(payload["key"]),
                value=payload.get("value"),
                kind=MemoryKind(str(payload.get("kind", MemoryKind.UNKNOWN.value))),
                namespace=str(payload.get("namespace", DEFAULT_NAMESPACE)),
                source=str(payload.get("source", DEFAULT_SOURCE)),
                tags=list(payload.get("tags", [])),
                priority=PriorityLevel(int(payload.get("priority", PriorityLevel.NORMAL.value))),
                confidence=float(payload.get("confidence", 1.0)),
                expires_at=datetime.fromisoformat(expires) if expires else None,
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
                updated_at=datetime.fromisoformat(payload.get("updated_at", _now().isoformat())),
                identifier=UUID(str(payload.get("identifier", uuid4()))),
                version=int(payload.get("schema_version", SCHEMA_VERSION)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid memory payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return (
            f"MemorySchema(key={self.key!r}, kind={self.kind.value!r}, "
            f"namespace={self.namespace!r})"
        )
