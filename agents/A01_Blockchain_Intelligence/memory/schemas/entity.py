"""
Entity Schema

Canonical data model and validation for extracted entities and their
relations. Complements ``Entity`` in ``memory.base.summarizer``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now


class EntityKind(str, Enum):
    """
    Canonical entity categories.
    """

    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    TOKEN = "token"
    PROJECT = "project"
    CONCEPT = "concept"
    DATE = "date"
    OTHER = "other"


@dataclass(slots=True)
class EntitySchema:
    """
    Canonical entity data model.

    Fields:
        * Name, kind, and aliases
        * Mention count and confidence
        * Relations and provenance
    """

    name: str
    kind: EntityKind = EntityKind.OTHER
    aliases: list[str] = field(default_factory=list)
    mention_count: int = 1
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    first_seen: datetime = field(default_factory=_now)
    last_seen: datetime = field(default_factory=_now)
    entity_uuid: UUID = field(default_factory=uuid4)

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise SchemaValidationError("entity name must be non-empty.")
        if self.mention_count < 0:
            raise SchemaValidationError("mention_count must be non-negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaValidationError("confidence must be within [0, 1].")
        if self.first_seen > self.last_seen:
            raise SchemaValidationError("first_seen cannot exceed last_seen.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "aliases": list(self.aliases),
            "mention_count": self.mention_count,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "entity_uuid": str(self.entity_uuid),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EntitySchema":
        try:
            schema = cls(
                name=str(payload["name"]),
                kind=EntityKind(str(payload.get("kind", EntityKind.OTHER.value))),
                aliases=list(payload.get("aliases", [])),
                mention_count=int(payload.get("mention_count", 1)),
                confidence=float(payload.get("confidence", 1.0)),
                tags=list(payload.get("tags", [])),
                metadata=dict(payload.get("metadata", {})),
                first_seen=datetime.fromisoformat(payload.get("first_seen", _now().isoformat())),
                last_seen=datetime.fromisoformat(payload.get("last_seen", _now().isoformat())),
                entity_uuid=UUID(str(payload.get("entity_uuid", uuid4()))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid entity payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"EntitySchema(name={self.name!r}, kind={self.kind.value!r})"


@dataclass(slots=True)
class EntityRelationSchema:
    """
    Canonical relation between two entities.

    Fields:
        * Source and target names
        * Relation type and confidence
    """

    source: str
    relation: str
    target: str
    confidence: float = 1.0
    context: str | None = None

    def validate(self) -> None:
        if not self.source or not self.relation or not self.target:
            raise SchemaValidationError("relation fields must be non-empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaValidationError("confidence must be within [0, 1].")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "confidence": self.confidence,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EntityRelationSchema":
        try:
            schema = cls(
                source=str(payload["source"]),
                relation=str(payload["relation"]),
                target=str(payload["target"]),
                confidence=float(payload.get("confidence", 1.0)),
                context=payload.get("context"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid relation payload: {exc}") from exc
        schema.validate()
        return schema
