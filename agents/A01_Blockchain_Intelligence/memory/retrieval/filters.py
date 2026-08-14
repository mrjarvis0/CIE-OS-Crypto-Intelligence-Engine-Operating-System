"""
Memory Query Filters

Pre- and post-retrieval filtering constraints: namespace, memory type,
priority, confidence, time window, tags, and value predicates.

The filters in this module are query-time constraints applied over
``MemoryEntry`` objects. They complement (not duplicate) the
``MemoryFilter`` protocol declared in ``memory.base.memory`` by
composing arbitrary predicates into chainable, reusable objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterable

from memory.base.memory import (
    MemoryEntry,
    MemoryPriority,
    MemoryType,
)

EntryPredicate = Callable[[MemoryEntry[Any]], bool]


def _entry_value_text(entry: MemoryEntry[Any]) -> str:
    value = entry.value
    return value if isinstance(value, str) else str(value)


def _entry_memory_type(entry: MemoryEntry[Any]) -> MemoryType | None:
    prefix = "lt:type:"
    for tag in entry.metadata.tags:
        if tag.startswith(prefix):
            try:
                return MemoryType(tag[len(prefix):])
            except ValueError:
                continue
    return None


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class QueryFilter:
    """
    Immutable retrieval constraints applied over memory entries.
    """

    namespace: str | None = None
    memory_type: MemoryType | None = None
    min_priority: MemoryPriority | None = None
    min_confidence: float = 0.0
    max_confidence: float = 1.0
    tags: frozenset[str] = field(default_factory=frozenset)
    tags_mode: str = "all"
    time_from: datetime | None = None
    time_to: datetime | None = None
    keys: frozenset[str] = field(default_factory=frozenset)
    text_contains: str | None = None
    value_predicate: EntryPredicate | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= self.max_confidence <= 1.0:
            raise ValueError("Confidence bounds must satisfy 0 <= min <= max <= 1.")
        if self.tags_mode not in {"all", "any"}:
            raise ValueError("tags_mode must be 'all' or 'any'.")

    def matches(self, entry: MemoryEntry[Any]) -> bool:
        """
        Return True when the entry satisfies every constraint.
        """
        metadata = entry.metadata

        if self.namespace is not None and metadata.namespace != self.namespace:
            return False

        if self.memory_type is not None:
            entry_type = _entry_memory_type(entry)
            if entry_type is not None and entry_type != self.memory_type:
                return False

        if self.min_priority is not None and metadata.priority.value < self.min_priority.value:
            return False

        if not (self.min_confidence <= metadata.confidence <= self.max_confidence):
            return False

        if self.tags:
            entry_tags = set(metadata.tags)
            if self.tags_mode == "all":
                if not self.tags.issubset(entry_tags):
                    return False
            elif not self.tags.intersection(entry_tags):
                return False

        created = metadata.created_at
        if self.time_from is not None and created < self.time_from:
            return False
        if self.time_to is not None and created > self.time_to:
            return False

        if self.keys and entry.key not in self.keys:
            return False

        if self.text_contains is not None:
            if self.text_contains.lower() not in _entry_value_text(entry).lower():
                return False

        if self.value_predicate is not None and not self.value_predicate(entry):
            return False

        return True


class MemoryQueryFilter:
    """
    Composes and applies filtering constraints to memory entries.

    Responsibilities:
        * Build a constraint set incrementally
        * Apply constraints to a single entry
        * Filter a collection of entries
    """

    def __init__(
        self,
        *,
        constraints: QueryFilter | None = None,
    ) -> None:
        self._constraints = constraints or QueryFilter()

    @property
    def constraints(self) -> QueryFilter:
        return self._constraints

    def with_namespace(self, namespace: str) -> "MemoryQueryFilter":
        return self._derive(namespace=namespace)

    def with_memory_type(self, memory_type: MemoryType) -> "MemoryQueryFilter":
        return self._derive(memory_type=memory_type)

    def with_min_priority(self, priority: MemoryPriority) -> "MemoryQueryFilter":
        return self._derive(min_priority=priority)

    def with_confidence(self, minimum: float, maximum: float = 1.0) -> "MemoryQueryFilter":
        return self._derive(min_confidence=minimum, max_confidence=maximum)

    def with_tags(self, tags: Iterable[str], mode: str = "all") -> "MemoryQueryFilter":
        return self._derive(tags=frozenset(tags), tags_mode=mode)

    def with_time_window(self, since: datetime, until: datetime) -> "MemoryQueryFilter":
        return self._derive(time_from=since, time_to=until)

    def with_keys(self, keys: Iterable[str]) -> "MemoryQueryFilter":
        return self._derive(keys=frozenset(keys))

    def containing(self, text: str) -> "MemoryQueryFilter":
        return self._derive(text_contains=text)

    def where(self, predicate: EntryPredicate) -> "MemoryQueryFilter":
        return self._derive(value_predicate=predicate)

    def _derive(self, **changes: Any) -> "MemoryQueryFilter":
        updated = {
            "namespace": self._constraints.namespace,
            "memory_type": self._constraints.memory_type,
            "min_priority": self._constraints.min_priority,
            "min_confidence": self._constraints.min_confidence,
            "max_confidence": self._constraints.max_confidence,
            "tags": self._constraints.tags,
            "tags_mode": self._constraints.tags_mode,
            "time_from": self._constraints.time_from,
            "time_to": self._constraints.time_to,
            "keys": self._constraints.keys,
            "text_contains": self._constraints.text_contains,
            "value_predicate": self._constraints.value_predicate,
        }
        updated.update(changes)
        return MemoryQueryFilter(constraints=QueryFilter(**updated))

    def matches(self, entry: MemoryEntry[Any]) -> bool:
        return self._constraints.matches(entry)

    def apply(
        self,
        entries: Iterable[MemoryEntry[Any]],
    ) -> list[MemoryEntry[Any]]:
        return [entry for entry in entries if self.matches(entry)]

    def reject(
        self,
        entries: Iterable[MemoryEntry[Any]],
    ) -> list[MemoryEntry[Any]]:
        return [entry for entry in entries if not self.matches(entry)]


class FilterChain:
    """
    Chains multiple filters and applies them in order.
    """

    def __init__(self, *filters: EntryPredicate) -> None:
        self._filters = list(filters)

    @property
    def filters(self) -> list[EntryPredicate]:
        return list(self._filters)

    def add(self, predicate: EntryPredicate) -> None:
        self._filters.append(predicate)

    def passes(self, entry: MemoryEntry[Any]) -> bool:
        return all(predicate(entry) for predicate in self._filters)

    def apply(
        self,
        entries: Iterable[MemoryEntry[Any]],
    ) -> list[MemoryEntry[Any]]:
        return [entry for entry in entries if self.passes(entry)]
