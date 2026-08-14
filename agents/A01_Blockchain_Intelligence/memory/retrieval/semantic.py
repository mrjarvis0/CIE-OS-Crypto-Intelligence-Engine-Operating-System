"""
Semantic Retriever

Embedding-based semantic retrieval over memory entries using vector
similarity scoring. Reuses ``memory.vector.embeddings`` and
``memory.vector.similarity`` for embedding generation and cosine
scoring respectively.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from memory.base.memory import (
    EmbeddingProvider,
    MemoryEntry,
    MemorySearchResult,
)
from memory.vector.embeddings import ResilientEmbedding
from memory.vector.similarity import cosine_similarity

EntrySource = Callable[[], Iterable[MemoryEntry[Any]]]


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _normalize(vector: list[float]) -> list[float]:
    norm = sum(x * x for x in vector) ** 0.5
    if norm == 0.0:
        return [0.0] * len(vector)
    return [x / norm for x in vector]


class SemanticRetriever:
    """
    Performs semantic retrieval over embedded memory content.

    The retriever works against any async memory source that exposes an
    ``active_entries()`` coroutine (e.g. ``BaseMemory`` subclasses) or
    against an arbitrary callable returning entries.

    Responsibilities:
        * Encode queries into embeddings
        * Score entries by semantic similarity
        * Return top-k relevant results above a threshold
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider | None = None,
        threshold: float = 0.0,
        default_limit: int = 10,
    ) -> None:
        self._embedder = embedder if embedder is not None else ResilientEmbedding()
        self._threshold = threshold
        self._default_limit = default_limit

    @property
    def embedder(self) -> EmbeddingProvider | None:
        return self._embedder

    @property
    def threshold(self) -> float:
        return self._threshold

    async def _embed(self, text: str) -> list[float]:
        if self._embedder is None:
            raise RuntimeError("No embedding provider has been configured.")
        result = self._embedder.embed(text)
        if hasattr(result, "__await__"):
            result = await result
        return _normalize(result)

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
        source: EntrySource | Iterable[MemoryEntry[Any]] | None = None,
        memory_source: Any | None = None,
        threshold: float | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Retrieve entries semantically similar to the query.

        ``source`` may be a callable returning entries, a plain
        iterable of entries, or omitted when ``memory_source`` is an
        object exposing ``async def active_entries()``.
        """
        entries = await self._collect_entries(
            source=source,
            memory_source=memory_source,
        )
        query_vec = await self._embed(query)
        thr = self._threshold if threshold is None else threshold
        limit_value = self._default_limit if limit is None else limit

        scored: list[tuple[float, float, MemoryEntry[Any]]] = []
        for entry in entries:
            value = _as_text(entry.value)
            if not value.strip():
                continue
            vec = await self._embed(value)
            score = cosine_similarity(query_vec, vec)
            if score < thr:
                continue
            scored.append((score, score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            MemorySearchResult(
                entry=entry,
                score=score,
                distance=1.0 - score,
            )
            for score, _, entry in scored[:limit_value]
        ]

    async def similarity_rank(
        self,
        query_vec: list[float],
        entries: Iterable[MemoryEntry[Any]],
        *,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Rank a pre-collected set of entries against an explicit query
        vector, bypassing the embedder for the query.
        """
        query_vec = _normalize(query_vec)
        scored: list[tuple[float, MemoryEntry[Any]]] = []
        for entry in entries:
            value = _as_text(entry.value)
            if not value.strip():
                continue
            vec = await self._embed(value)
            score = cosine_similarity(query_vec, vec)
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        limit_value = self._default_limit if limit is None else limit
        return [
            MemorySearchResult(
                entry=entry,
                score=score,
                distance=1.0 - score,
            )
            for score, entry in scored[:limit_value]
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
