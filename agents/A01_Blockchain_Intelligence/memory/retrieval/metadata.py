"""
Metadata Retriever

Retrieves memory entries by metadata constraints: namespace, tags,
priority, confidence, and time window. Wraps the filtering primitives
from ``memory.retrieval.filters``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from memory.base.memory import (
    MemoryEntry,
    MemoryPriority,
    MemoryType,
    MemorySearchResult,
)
from memory.retrieval.filters import MemoryQueryFilter

EntrySource = Callable[[], Iterable[MemoryEntry[Any]]]


class MetadataRetriever:
    """
    Retrieves entries filtered by metadata attributes.

    Responsibilities:
        * Filter by namespace, type, tags, priority, confidence
        * Apply time windows and key constraints
        * Return deterministic metadata matches
    """

    def __init__(
        self,
        *,
        default_limit: int = 10,
    ) -> None:
        self._default_limit = default_limit

    async def retrieve(
        self,
        *,
        namespace: str | None = None,
        memory_type: MemoryType | None = None,
        min_priority: MemoryPriority | None = None,
        min_confidence: float = 0.0,
        max_confidence: float = 1.0,
        tags: Iterable[str] | None = None,
        tags_mode: str = "all",
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        keys: Iterable[str] | None = None,
        limit: int | None = None,
        source: EntrySource | Iterable[MemoryEntry[Any]] | None = None,
        memory_source: Any | None = None,
        score: float = 1.0,
    ) -> list[MemorySearchResult[Any]]:
        """
        Retrieve entries satisfying the given metadata constraints.
        """
        entries = await self._collect_entries(
            source=source,
            memory_source=memory_source,
        )
        query_filter = MemoryQueryFilter()
        if namespace is not None:
            query_filter = query_filter.with_namespace(namespace)
        if memory_type is not None:
            query_filter = query_filter.with_memory_type(memory_type)
        if min_priority is not None:
            query_filter = query_filter.with_min_priority(min_priority)
        if min_confidence != 0.0 or max_confidence != 1.0:
            query_filter = query_filter.with_confidence(min_confidence, max_confidence)
        if tags is not None:
            query_filter = query_filter.with_tags(tags, mode=tags_mode)
        if time_from is not None or time_to is not None:
            query_filter = query_filter.with_time_window(
                time_from or datetime.min,
                time_to or datetime.max,
            )
        if keys is not None:
            query_filter = query_filter.with_keys(keys)

        matched = query_filter.apply(entries)
        limit_value = self._default_limit if limit is None else limit
        matched.sort(key=lambda entry: (entry.metadata.priority.value, entry.key), reverse=True)
        return [
            MemorySearchResult(entry=entry, score=score, distance=0.0)
            for entry in matched[:limit_value]
        ]

    async def _collect_entries(
        self,
        *,
        source: EntrySource | Iterable[MemoryEntry[Any]] | None,
        memory_source: Any | None,
    ) -> list[MemoryEntry[Any]]:
        if source is not None:
            if callable(source):
                return list(source())
            return list(source)
        if memory_source is not None:
            active = getattr(memory_source, "active_entries", None)
            if callable(active):
                result = active()
                if hasattr(result, "__await__"):
                    return list(await result)
                return list(result)
        raise ValueError(
            "A 'source' callable, iterable, or 'memory_source' with "
            "active_entries() must be provided."
        )
