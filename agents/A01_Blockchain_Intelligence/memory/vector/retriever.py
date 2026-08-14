"""
Vector Retriever

Retrieves memory entries from vector storage by embedding similarity.
Thin facade over a ``VectorMemory``-like source's search engine with
ranking, filtering, and score normalization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from memory.base.memory import (
    MemoryPriority,
    MemorySearchResult,
    SearchMode,
)
from memory.vector.similarity import SimilarityService

VectorSource = Any


@dataclass(slots=True)
class RetrievalQuery:
    """
    Parameterized vector retrieval request.
    """

    text: str
    mode: str = SearchMode.SEMANTIC.value
    limit: int = 10
    threshold: float | None = None
    namespace: str | None = None
    collection: str | None = None
    tags: list[str] | None = None
    priority: MemoryPriority | None = None
    min_importance: float = 0.0
    time_from: datetime | None = None
    time_to: datetime | None = None
    metadata_filter: dict[str, Any] | None = None


@dataclass(slots=True)
class RetrievalResult:
    """
    Outcome of a vector retrieval with normalized scores.
    """

    results: list[MemorySearchResult[Any]] = field(default_factory=list)
    mode: str = SearchMode.SEMANTIC.value
    query: str = ""

    @property
    def count(self) -> int:
        return len(self.results)

    @property
    def top_score(self) -> float:
        return self.results[0].score if self.results else 0.0

    def entries(self) -> list[Any]:
        return [result.entry for result in self.results]

    def keys(self) -> list[str]:
        return [result.entry.key for result in self.results]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "count": self.count,
            "results": [
                {
                    "key": result.entry.key,
                    "score": result.score,
                    "distance": result.distance,
                }
                for result in self.results
            ],
        }


class VectorRetriever:
    """
    Queries vector storage for similar entries.

    Responsibilities:
        * Encode queries via the embedding service
        * Execute semantic / exact / hybrid searches
        * Rank and threshold-filter candidate entries
    """

    def __init__(
        self,
        memory: VectorSource,
        *,
        similarity: SimilarityService | None = None,
        default_mode: str = SearchMode.SEMANTIC.value,
        default_limit: int = 10,
        default_threshold: float | None = None,
    ) -> None:
        self._memory = memory
        self._similarity = similarity or SimilarityService(
            default_threshold=(
                0.5 if default_threshold is None else default_threshold
            )
        )
        self._default_mode = default_mode
        self._default_limit = default_limit
        self._default_threshold = default_threshold

    @property
    def memory(self) -> VectorSource:
        return self._memory

    @property
    def similarity(self) -> SimilarityService:
        return self._similarity

    def _require_search(self) -> None:
        if not callable(getattr(self._memory, "search", None)):
            raise AttributeError("memory source must expose search()")

    async def retrieve(
        self,
        query: str,
        *,
        mode: str | None = None,
        limit: int | None = None,
        threshold: float | None = None,
        namespace: str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        min_importance: float = 0.0,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """
        Execute a retrieval request against the underlying source.
        """
        self._require_search()
        if metadata_filter is not None:
            return await self._retrieve_metadata(
                query,
                metadata_filter,
                limit=limit,
                namespace=namespace,
                collection=collection,
            )
        search = getattr(self._memory, "search", None)
        result = search(
            query,
            limit=limit if limit is not None else self._default_limit,
            mode=mode if mode is not None else self._default_mode,
            threshold=threshold
            if threshold is not None
            else self._default_threshold,
            namespace=namespace,
            collection=collection,
            tags=tags,
            priority=priority,
            min_importance=min_importance,
            time_from=time_from,
            time_to=time_to,
        )
        results = (
            await result if hasattr(result, "__await__") else result
        )
        return RetrievalResult(
            results=list(results),
            mode=mode if mode is not None else self._default_mode,
            query=query,
        )

    async def _retrieve_metadata(
        self,
        query: str,
        metadata_filter: dict[str, Any],
        *,
        limit: int | None,
        namespace: str | None,
        collection: str | None,
    ) -> RetrievalResult:
        search_by_metadata = getattr(
            self._memory, "search_by_metadata", None
        )
        if not callable(search_by_metadata):
            raise AttributeError(
                "memory source must expose search_by_metadata() "
                "for metadata_filter queries"
            )
        result = search_by_metadata(
            metadata_filter,
            limit=limit if limit is not None else self._default_limit,
            namespace=namespace,
            collection=collection,
        )
        results = await result if hasattr(result, "__await__") else result
        return RetrievalResult(
            results=list(results),
            mode="metadata",
            query=query,
        )

    async def retrieve_by_id(
        self,
        key: str,
        *,
        namespace: str | None = None,
        collection: str | None = None,
    ) -> Any | None:
        get_entry = getattr(self._memory, "get", None)
        if not callable(get_entry):
            raise AttributeError("memory source must expose get()")
        result = get_entry(
            key,
            namespace=namespace,
            collection=collection,
        )
        return await result if hasattr(result, "__await__") else result

    async def retrieve_many(
        self,
        keys: Iterable[str],
    ) -> list[Any]:
        get_batch = getattr(self._memory, "get_batch", None)
        if not callable(get_batch):
            raise AttributeError("memory source must expose get_batch()")
        result = get_batch(list(keys))
        return await result if hasattr(result, "__await__") else result

    def normalize_scores(
        self,
        result: RetrievalResult,
        *,
        floor: float = 0.0,
        ceiling: float = 1.0,
    ) -> RetrievalResult:
        """
        Min-max normalize retrieval scores into ``[floor, ceiling]``.
        """
        if not result.results:
            return result
        scores = [r.score for r in result.results]
        lo, hi = min(scores), max(scores)
        span = hi - lo
        normalized: list[MemorySearchResult[Any]] = []
        for r in result.results:
            if span == 0.0:
                new_score = ceiling
            else:
                new_score = floor + (r.score - lo) / span * (ceiling - floor)
            normalized.append(
                MemorySearchResult(
                    entry=r.entry,
                    score=new_score,
                    distance=r.distance,
                )
            )
        result.results = normalized
        return result

    def apply_threshold(
        self,
        result: RetrievalResult,
        *,
        threshold: float | None = None,
    ) -> RetrievalResult:
        t = (
            threshold
            if threshold is not None
            else self._default_threshold
        )
        if t is None:
            return result
        result.results = [
            r for r in result.results if r.score >= t
        ]
        return result
