"""
Batch Operations

High-volume CRUD over vector memory: put_many, get_many, delete_many,
and batch search through a ``VectorMemory``-like source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

from memory.base.memory import MemoryEntry, MemoryPriority


@dataclass(slots=True)
class BatchResult:
    """
    Outcome of a batch operation.
    """

    succeeded: int = 0
    failed: int = 0
    keys: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "succeeded": self.succeeded,
            "failed": self.failed,
            "keys": self.keys,
            "errors": self.errors,
        }


class BatchOperator:
    """
    Executes bulk CRUD operations on vector memory.

    Responsibilities:
        * Store and load many entries
        * Delete many entries
        * Search for multiple queries
    """

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        return self._memory

    async def put_many(
        self,
        entries: Iterable[tuple[str, Any]],
        **kwargs: Any,
    ) -> BatchResult:
        result = BatchResult()
        put = getattr(self._memory, "put", None)
        if not callable(put):
            raise AttributeError("memory source must expose put()")
        for key, value in entries:
            try:
                put_result = put(key, value, **kwargs)
                await put_result if hasattr(put_result, "__await__") else None
                result.succeeded += 1
                result.keys.append(key)
            except Exception as exc:  # pragma: no cover - defensive
                result.failed += 1
                result.errors.append(f"{key}: {exc}")
        return result

    async def get_many(
        self,
        keys: Sequence[str],
    ) -> list[MemoryEntry[Any]]:
        get_batch = getattr(self._memory, "get_batch", None)
        if callable(get_batch):
            result = get_batch(list(keys))
            return await result if hasattr(result, "__await__") else result
        get_entry = getattr(self._memory, "get", None)
        if not callable(get_entry):
            raise AttributeError(
                "memory source must expose get_batch() or get()"
            )
        entries: list[MemoryEntry[Any]] = []
        for key in keys:
            result = get_entry(key)
            entry = await result if hasattr(result, "__await__") else result
            if entry is not None:
                entries.append(entry)
        return entries

    async def delete_many(
        self,
        keys: Sequence[str],
        *,
        namespace: str | None = None,
        collection: str | None = None,
    ) -> BatchResult:
        result = BatchResult()
        delete = getattr(self._memory, "delete", None)
        if not callable(delete):
            raise AttributeError("memory source must expose delete()")
        for key in keys:
            try:
                delete_result = delete(
                    key,
                    namespace=namespace,
                    collection=collection,
                )
                await delete_result if hasattr(delete_result, "__await__") else None
                result.succeeded += 1
                result.keys.append(key)
            except Exception as exc:  # pragma: no cover - defensive
                result.failed += 1
                result.errors.append(f"{key}: {exc}")
        return result

    async def search_many(
        self,
        queries: Sequence[str],
        **kwargs: Any,
    ) -> list[list[Any]]:
        search = getattr(self._memory, "search", None)
        if not callable(search):
            raise AttributeError("memory source must expose search()")
        results: list[list[Any]] = []
        for query in queries:
            result = search(query, **kwargs)
            results.append(
                await result if hasattr(result, "__await__") else result
            )
        return results
