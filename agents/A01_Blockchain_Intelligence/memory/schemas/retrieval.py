"""
Retrieval Schema

Canonical data model for retrieval queries, filters, and ranked
results. Complements the runtime ``MemorySearchResult`` in
``memory.base.memory`` and the ``memory.retrieval`` package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now


class RetrievalMode(str, Enum):
    """
    Canonical retrieval strategies.
    """

    EXACT = "exact"
    PREFIX = "prefix"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    KEYWORD = "keyword"


class FusionMode(str, Enum):
    """
    Canonical hybrid fusion strategies.
    """

    RRF = "rrf"
    WEIGHTED = "weighted"


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


@dataclass(slots=True)
class RetrievalQuerySchema:
    """
    Canonical retrieval query data model.

    Fields:
        * Query text and mode
        * Limits, thresholds, and filters
        * Provenance metadata
    """

    text: str
    mode: RetrievalMode = RetrievalMode.HYBRID
    limit: int = 10
    threshold: float = 0.0
    namespace: str | None = None
    tags: list[str] = field(default_factory=list)
    time_from: datetime | None = None
    time_to: datetime | None = None
    min_priority: int | None = None
    min_confidence: float = 0.0
    fusion: FusionMode = FusionMode.RRF
    rerank: bool = True
    query_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        if not self.text or not self.text.strip():
            raise SchemaValidationError("query text must be non-empty.")
        if self.limit <= 0:
            raise SchemaValidationError("limit must be strictly positive.")
        if not 0.0 <= self.threshold <= 1.0:
            raise SchemaValidationError("threshold must be within [0, 1].")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise SchemaValidationError("min_confidence must be within [0, 1].")
        if self.time_from is not None and self.time_to is not None:
            if self.time_from > self.time_to:
                raise SchemaValidationError("time_from cannot exceed time_to.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "mode": self.mode.value,
            "limit": self.limit,
            "threshold": self.threshold,
            "namespace": self.namespace,
            "tags": list(self.tags),
            "time_from": self.time_from.isoformat() if self.time_from is not None else None,
            "time_to": self.time_to.isoformat() if self.time_to is not None else None,
            "min_priority": self.min_priority,
            "min_confidence": self.min_confidence,
            "fusion": self.fusion.value,
            "rerank": self.rerank,
            "query_id": str(self.query_id),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RetrievalQuerySchema":
        try:
            time_from = payload.get("time_from")
            time_to = payload.get("time_to")
            raw_priority = payload.get("min_priority")
            schema = cls(
                text=str(payload["text"]),
                mode=RetrievalMode(str(payload.get("mode", RetrievalMode.HYBRID.value))),
                limit=int(payload.get("limit", 10)),
                threshold=float(payload.get("threshold", 0.0)),
                namespace=payload.get("namespace"),
                tags=list(payload.get("tags", [])),
                time_from=datetime.fromisoformat(time_from) if time_from else None,
                time_to=datetime.fromisoformat(time_to) if time_to else None,
                min_priority=int(raw_priority) if raw_priority is not None else None,
                min_confidence=float(payload.get("min_confidence", 0.0)),
                fusion=FusionMode(str(payload.get("fusion", FusionMode.RRF.value))),
                rerank=_coerce_bool(payload.get("rerank"), True),
                query_id=UUID(str(payload.get("query_id", uuid4()))),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid query payload: {exc}") from exc
        schema.validate()
        return schema


@dataclass(slots=True)
class RetrievalResultSchema:
    """
    Canonical ranked retrieval result.

    Fields:
        * Entry key and value
        * Composite and component scores
        * Provenance metadata
    """

    key: str
    value: Any
    score: float
    relevance: float = 0.0
    recency: float = 0.0
    importance: float = 0.0
    distance: float | None = None
    namespace: str = "default"
    source: str = "runtime"
    tags: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        if not self.key or not self.key.strip():
            raise SchemaValidationError("result key must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "score": self.score,
            "relevance": self.relevance,
            "recency": self.recency,
            "importance": self.importance,
            "distance": self.distance,
            "namespace": self.namespace,
            "source": self.source,
            "tags": list(self.tags),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RetrievalResultSchema":
        try:
            schema = cls(
                key=str(payload["key"]),
                value=payload.get("value"),
                score=float(payload.get("score", 0.0)),
                relevance=float(payload.get("relevance", 0.0)),
                recency=float(payload.get("recency", 0.0)),
                importance=float(payload.get("importance", 0.0)),
                distance=payload.get("distance"),
                namespace=str(payload.get("namespace", "default")),
                source=str(payload.get("source", "runtime")),
                tags=list(payload.get("tags", [])),
                updated_at=datetime.fromisoformat(payload.get("updated_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid result payload: {exc}") from exc
        schema.validate()
        return schema
