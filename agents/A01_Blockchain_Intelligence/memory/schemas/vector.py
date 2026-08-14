"""
Vector Schema

Canonical data model and validation for vector embeddings and vector
store collections. Complements ``memory.vector`` without duplicating
runtime implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now

DEFAULT_DIM = 128
DEFAULT_COLLECTION = "default"
DEFAULT_NAMESPACE = "default"


class DistanceMetric(str, Enum):
    """
    Canonical vector distance metrics.
    """

    COSINE = "cosine"
    DOT = "dot"
    EUCLIDEAN = "euclidean"
    MANHATTAN = "manhattan"


class VectorStoreKind(str, Enum):
    """
    Canonical backing vector stores.
    """

    IN_MEMORY = "in_memory"
    SQLITE = "sqlite"
    QDRANT = "qdrant"
    PGVECTOR = "pgvector"
    FAISS = "faiss"
    WEAVIATE = "weaviate"


@dataclass(slots=True)
class VectorSchema:
    """
    Canonical embedding record.

    Fields:
        * Vector values and dimension
        * Collection and namespace
        * Provenance and metadata
    """

    key: str
    values: list[float]
    collection: str = DEFAULT_COLLECTION
    namespace: str = DEFAULT_NAMESPACE
    metric: DistanceMetric = DistanceMetric.COSINE
    source: str = "runtime"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    identifier: UUID = field(default_factory=uuid4)

    @property
    def dim(self) -> int:
        return len(self.values)

    def validate(self) -> None:
        if not self.key or not self.key.strip():
            raise SchemaValidationError("key must be non-empty.")
        if not self.values:
            raise SchemaValidationError("embedding values must be non-empty.")
        if any(not isinstance(v, (int, float)) for v in self.values):
            raise SchemaValidationError("embedding values must be numeric.")
        if self.dim == 0:
            raise SchemaValidationError("embedding dimension must be positive.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "dim": self.dim,
            "values": list(self.values),
            "collection": self.collection,
            "namespace": self.namespace,
            "metric": self.metric.value,
            "source": self.source,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "identifier": str(self.identifier),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VectorSchema":
        try:
            values = [float(v) for v in payload["values"]]
            schema = cls(
                key=str(payload["key"]),
                values=values,
                collection=str(payload.get("collection", DEFAULT_COLLECTION)),
                namespace=str(payload.get("namespace", DEFAULT_NAMESPACE)),
                metric=DistanceMetric(str(payload.get("metric", DistanceMetric.COSINE.value))),
                source=str(payload.get("source", "runtime")),
                tags=list(payload.get("tags", [])),
                metadata=dict(payload.get("metadata", {})),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
                identifier=UUID(str(payload.get("identifier", uuid4()))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid vector payload: {exc}") from exc
        schema.validate()
        return schema

    @classmethod
    def from_values(cls, key: str, values: Sequence[float], **kwargs: Any) -> "VectorSchema":
        return cls(key=key, values=list(values), **kwargs)

    def __repr__(self) -> str:
        return f"VectorSchema(key={self.key!r}, dim={self.dim!r})"


@dataclass(slots=True)
class VectorCollectionSchema:
    """
    Canonical vector collection descriptor.

    Fields:
        * Store kind and embedding dimension
        * Distance metric and namespace
    """

    name: str
    store: VectorStoreKind = VectorStoreKind.IN_MEMORY
    dim: int = DEFAULT_DIM
    metric: DistanceMetric = DistanceMetric.COSINE
    namespace: str = DEFAULT_NAMESPACE
    size: int = 0
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise SchemaValidationError("collection name must be non-empty.")
        if self.dim <= 0:
            raise SchemaValidationError("dim must be positive.")
        if self.size < 0:
            raise SchemaValidationError("size must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "store": self.store.value,
            "dim": self.dim,
            "metric": self.metric.value,
            "namespace": self.namespace,
            "size": self.size,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VectorCollectionSchema":
        try:
            schema = cls(
                name=str(payload["name"]),
                store=VectorStoreKind(str(payload.get("store", VectorStoreKind.IN_MEMORY.value))),
                dim=int(payload.get("dim", DEFAULT_DIM)),
                metric=DistanceMetric(str(payload.get("metric", DistanceMetric.COSINE.value))),
                namespace=str(payload.get("namespace", DEFAULT_NAMESPACE)),
                size=int(payload.get("size", 0)),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid collection payload: {exc}") from exc
        schema.validate()
        return schema
