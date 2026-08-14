"""
Metrics Schema

Canonical data model and validation for memory statistics, health
snapshots, and operation metrics. Complements ``MemoryStatistics``
and the health/metrics methods in ``memory.base.memory``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from memory.schemas.memory import SchemaValidationError, _now


class HealthState(str, Enum):
    """
    Canonical health states.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


@dataclass(slots=True)
class MetricsSchema:
    """
    Canonical memory statistics model.

    Fields:
        * Entry and operation counters
        * Cache metrics and uptime
    """

    entries: int = 0
    reads: int = 0
    writes: int = 0
    updates: int = 0
    deletes: int = 0
    searches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    started_at: datetime = field(default_factory=_now)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, (_now() - self.started_at).total_seconds())

    def validate(self) -> None:
        for name in ("entries", "reads", "writes", "updates", "deletes", "searches", "cache_hits", "cache_misses"):
            if getattr(self, name) < 0:
                raise SchemaValidationError(f"{name} must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "reads": self.reads,
            "writes": self.writes,
            "updates": self.updates,
            "deletes": self.deletes,
            "searches": self.searches,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.cache_hit_rate,
            "uptime_seconds": self.uptime_seconds,
            "started_at": self.started_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MetricsSchema":
        try:
            schema = cls(
                entries=int(payload.get("entries", 0)),
                reads=int(payload.get("reads", 0)),
                writes=int(payload.get("writes", 0)),
                updates=int(payload.get("updates", 0)),
                deletes=int(payload.get("deletes", 0)),
                searches=int(payload.get("searches", 0)),
                cache_hits=int(payload.get("cache_hits", 0)),
                cache_misses=int(payload.get("cache_misses", 0)),
                started_at=datetime.fromisoformat(payload.get("started_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid metrics payload: {exc}") from exc
        schema.validate()
        return schema


@dataclass(slots=True)
class HealthSchema:
    """
    Canonical health snapshot model.

    Fields:
        * Component name and state
        * Entry counts and backend info
    """

    component: str
    state: HealthState = HealthState.UNKNOWN
    entries: int = 0
    expired_entries: int = 0
    initialized: bool = False
    closed: bool = False
    backend: str | None = None
    namespace: str | None = None
    message: str | None = None
    checked_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        if not self.component or not self.component.strip():
            raise SchemaValidationError("component must be non-empty.")
        if self.entries < 0 or self.expired_entries < 0:
            raise SchemaValidationError("entry counts must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "state": self.state.value,
            "entries": self.entries,
            "expired_entries": self.expired_entries,
            "initialized": self.initialized,
            "closed": self.closed,
            "backend": self.backend,
            "namespace": self.namespace,
            "message": self.message,
            "checked_at": self.checked_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HealthSchema":
        try:
            schema = cls(
                component=str(payload["component"]),
                state=HealthState(str(payload.get("state", HealthState.UNKNOWN.value))),
                entries=int(payload.get("entries", 0)),
                expired_entries=int(payload.get("expired_entries", 0)),
                initialized=_coerce_bool(payload.get("initialized"), False),
                closed=_coerce_bool(payload.get("closed"), False),
                backend=payload.get("backend"),
                namespace=payload.get("namespace"),
                message=payload.get("message"),
                checked_at=datetime.fromisoformat(payload.get("checked_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid health payload: {exc}") from exc
        schema.validate()
        return schema


@dataclass(slots=True)
class SnapshotSchema:
    """
    Canonical runtime snapshot model.

    Fields:
        * Health, metrics, and keys
        * Snapshot timestamp
    """

    health: HealthSchema
    metrics: MetricsSchema
    keys: list[str] = field(default_factory=list)
    taken_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "health": self.health.to_dict(),
            "metrics": self.metrics.to_dict(),
            "keys": list(self.keys),
            "taken_at": self.taken_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SnapshotSchema":
        try:
            raw_time = payload.get("taken_at", payload.get("timestamp"))
            schema = cls(
                health=HealthSchema.from_dict(payload["health"]),
                metrics=MetricsSchema.from_dict(payload["metrics"]),
                keys=list(payload.get("keys", [])),
                taken_at=datetime.fromisoformat(raw_time if raw_time else _now().isoformat()),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid snapshot payload: {exc}") from exc
        return schema
