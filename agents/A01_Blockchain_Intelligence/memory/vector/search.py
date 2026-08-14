"""
Vector Search

Search executor over vector memory supporting semantic, exact,
hybrid, and metadata modes with query planning and result shaping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from memory.base.memory import (
    MemoryPriority,
    MemorySearchResult,
    SearchMode,
)
from memory.vector.retriever import RetrievalResult, VectorRetriever

VectorSource = Any

VALID_MODES = {
    SearchMode.SEMANTIC.value,
    SearchMode.EXACT.value,
    SearchMode.HYBRID.value,
    "metadata",
    "keyword",
    "prefix",
}


@dataclass(slots=True)
class SearchPlan:
    """
    The resolved strategy for a search request.
    """

    mode: str
    limit: int
    threshold: float | None
    strategy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "limit": self.limit,
            "threshold": self.threshold,
            "strategy": self.strategy,
        }


class SearchExecutor:
    """
    Executes and coordinates vector searches.

    Responsibilities:
        * Validate and plan search strategies
        * Dispatch to the configured retriever
        * Normalize and threshold-filter results
    """

    def __init__(
        self,
        memory: VectorSource,
        *,
        retriever: VectorRetriever | None = None,
        default_mode: str = SearchMode.SEMANTIC.value,
        default_limit: int = 10,
        default_threshold: float | None = None,
    ) -> None:
        self._memory = memory
        self._retriever = retriever or VectorRetriever(
            memory,
            default_mode=default_mode,
            default_limit=default_limit,
            default_threshold=default_threshold,
        )
        self._default_mode = default_mode
        self._default_limit = default_limit
        self._default_threshold = default_threshold

    @property
    def memory(self) -> VectorSource:
        return self._memory

    @property
    def retriever(self) -> VectorRetriever:
        return self._retriever

    def plan(
        self,
        text: str,
        *,
        mode: str | None = None,
        limit: int | None = None,
        threshold: float | None = None,
    ) -> SearchPlan:
        resolved_mode = (mode or self._default_mode).lower()
        if resolved_mode not in VALID_MODES:
            raise ValueError(
                f"Unknown search mode '{resolved_mode}'. "
                f"Valid: {sorted(VALID_MODES)}"
            )
        if resolved_mode in {"keyword", "prefix"}:
            resolved_mode = SearchMode.EXACT.value
        strategy = (
            "metadata"
            if resolved_mode == "metadata"
            else resolved_mode
        )
        return SearchPlan(
            mode=resolved_mode,
            limit=limit if limit is not None else self._default_limit,
            threshold=threshold
            if threshold is not None
            else self._default_threshold,
            strategy=strategy,
        )

    async def search(
        self,
        text: str,
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
        normalize: bool = False,
    ) -> RetrievalResult:
        plan = self.plan(
            text,
            mode=mode,
            limit=limit,
            threshold=threshold,
        )
        result = await self._retriever.retrieve(
            text,
            mode=plan.mode,
            limit=plan.limit,
            threshold=plan.threshold,
            namespace=namespace,
            collection=collection,
            tags=tags,
            priority=priority,
            min_importance=min_importance,
            time_from=time_from,
            time_to=time_to,
            metadata_filter=metadata_filter,
        )
        if normalize:
            result = self._retriever.normalize_scores(result)
        return result

    async def search_many(
        self,
        queries: Sequence[str],
        *,
        limit: int | None = None,
        mode: str | None = None,
        **kwargs: Any,
    ) -> list[RetrievalResult]:
        return [
            await self.search(
                query,
                mode=mode,
                limit=limit,
                **kwargs,
            )
            for query in queries
        ]

    def flatten(
        self,
        results: list[RetrievalResult],
        *,
        max_results: int = 20,
    ) -> list[MemorySearchResult[Any]]:
        """
        Merge multiple result sets and keep the top scored keys.
        """
        merged: dict[str, MemorySearchResult[Any]] = {}
        for result in results:
            for item in result.results:
                key = item.entry.key
                if key not in merged or item.score > merged[key].score:
                    merged[key] = item
        ranked = sorted(
            merged.values(),
            key=lambda r: r.score,
            reverse=True,
        )
        return ranked[:max_results]
