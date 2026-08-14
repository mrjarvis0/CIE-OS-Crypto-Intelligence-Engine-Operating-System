"""
Vector Adapter

Bridge between the storage layer's ``StorageBackend`` protocol and the
vector layer, so any durable backend (sqlite, postgres, redis, ...) can
serve as the persistence engine for vector operations.
"""

from __future__ import annotations

from typing import Any

from memory.base.memory import (
    MemoryEntry,
    MemoryMetadata,
    MemoryPriority,
    MemorySearchResult,
)


class VectorAdapter:
    """
    Exposes a storage backend as a vector-capable source.

    The wrapped backend only needs to implement the ``StorageBackend``
    protocol (connect / save / delete / load / search / keys / clear).
    This adapter adds the vector API surface used by retrievers,
    executors, and pipelines.
    """

    def __init__(
        self,
        backend: Any,
        *,
        embedder: Any | None = None,
    ) -> None:
        self._backend = backend
        self._embedder = embedder

    @property
    def backend(self) -> Any:
        return self._backend

    @property
    def embedder(self) -> Any | None:
        return self._embedder

    async def connect(self) -> None:
        connect = getattr(self._backend, "connect", None)
        if callable(connect):
            result = connect()
            await result if hasattr(result, "__await__") else None

    async def disconnect(self) -> None:
        disconnect = getattr(self._backend, "disconnect", None)
        if callable(disconnect):
            result = disconnect()
            await result if hasattr(result, "__await__") else None

    async def put(
        self,
        key: str,
        value: Any,
        *,
        namespace: str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        source: str = "runtime",
        **kwargs: Any,
    ) -> MemoryEntry[Any]:
        metadata = MemoryMetadata(
            namespace=namespace or "default",
            tags=tags or [],
            priority=priority or MemoryPriority.NORMAL,
            source=source,
        )
        entry = MemoryEntry(key=key, value=value, metadata=metadata)
        await self._backend.save(entry)
        return entry

    async def get(
        self,
        key: str,
        **kwargs: Any,
    ) -> MemoryEntry[Any] | None:
        return await self._backend.load(key)

    async def get_batch(
        self,
        keys: list[str],
        **kwargs: Any,
    ) -> list[MemoryEntry[Any]]:
        entries: list[MemoryEntry[Any]] = []
        for key in keys:
            entry = await self._backend.load(key)
            if entry is not None:
                entries.append(entry)
        return entries

    async def delete(
        self,
        key: str,
        **kwargs: Any,
    ) -> bool:
        await self._backend.delete(key)
        return True

    async def keys(self, **kwargs: Any) -> list[str]:
        keys = getattr(self._backend, "keys", None)
        if not callable(keys):
            return []
        result = keys()
        return await result if hasattr(result, "__await__") else list(result)

    async def count(self) -> int:
        count = getattr(self._backend, "count", None)
        if callable(count):
            result = count()
            return await result if hasattr(result, "__await__") else result
        return len(await self.keys())

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[MemorySearchResult[Any]]:
        search = getattr(self._backend, "search", None)
        if not callable(search):
            if self._embedder is None:
                return []
            return await self._embedder_search(query, limit=limit)
        result = search(query, limit=limit)
        entries = (
            await result if hasattr(result, "__await__") else result
        )
        return [
            MemorySearchResult(entry=entry, score=1.0)
            for entry in entries
        ]

    async def _embedder_search(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[MemorySearchResult[Any]]:
        query_vec = self._embedder.embed(query)
        entries = await self.get_batch(await self.keys())
        scored: list[tuple[float, MemoryEntry[Any]]] = []
        for entry in entries:
            text = str(entry.value)
            vector = self._embedder.embed(text)
            score = _cosine(query_vec, vector)
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            MemorySearchResult(entry=entry, score=score)
            for score, entry in scored[:limit]
        ]

    async def clear(self, **kwargs: Any) -> None:
        clear = getattr(self._backend, "clear", None)
        if callable(clear):
            result = clear()
            await result if hasattr(result, "__await__") else None


def _cosine(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(x * x for x in vec_a) ** 0.5
    norm_b = sum(x * x for x in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
