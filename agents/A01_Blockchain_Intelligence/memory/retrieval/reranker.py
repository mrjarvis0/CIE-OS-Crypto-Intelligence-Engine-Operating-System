"""
Reranker

Re-orders an initial candidate set using additional signals: recency,
importance, metadata affinity, and optional external scoring. Provides
a pluggable reranker interface plus concrete implementations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Protocol

from memory.base.memory import (
    MemoryEntry,
    MemoryPriority,
    MemorySearchResult,
)
from memory.retrieval.ranking import (
    RankedResult,
    RankingEngine,
    importance_factor,
    recency_factor,
)

ScoringFn = Callable[[MemoryEntry[Any], str], float]


class Reranker(Protocol):
    """
    Reranks a candidate result list.
    """

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        ...


class IdentityReranker:
    """
    No-op reranker that preserves candidate order.
    """

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        return list(results)


class RecencyReranker:
    """
    Reranks by recency using exponential decay.
    """

    def __init__(
        self,
        *,
        half_life_hours: float = 24.0,
    ) -> None:
        self._half_life_hours = half_life_hours

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        now = datetime.now(UTC)
        ordered = sorted(
            results,
            key=lambda r: (
                recency_factor(
                    r.entry.metadata.updated_at,
                    reference=now,
                    half_life_hours=self._half_life_hours,
                ),
                r.entry.key,
            ),
            reverse=True,
        )
        return ordered


class PriorityReranker:
    """
    Reranks by memory priority and confidence.
    """

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        ordered = sorted(
            results,
            key=lambda r: (
                importance_factor(
                    r.entry.metadata.priority,
                    r.entry.metadata.confidence,
                ),
                r.entry.key,
            ),
            reverse=True,
        )
        return ordered


class BoostedReranker:
    """
    Applies a weighted additive boost to a subset of results.

    Responsibilities:
        * Detect boost-worthy results via a predicate
        * Add a fixed or query-relative boost
        * Keep deterministic ordering for ties
    """

    def __init__(
        self,
        *,
        boost: float = 0.15,
        predicate: Callable[[MemoryEntry[Any]], bool] | None = None,
        base: Reranker | None = None,
    ) -> None:
        self._boost = boost
        self._predicate = predicate or (lambda entry: False)
        self._base = base or IdentityReranker()

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        base = self._base.rerank(results, query)
        boosted = [
            MemorySearchResult(
                entry=r.entry,
                score=r.score + (self._boost if self._predicate(r.entry) else 0.0),
                distance=r.distance,
            )
            for r in base
        ]
        boosted.sort(key=lambda r: (round(r.score, 12), r.entry.key), reverse=True)
        return boosted


class ScoreBoosterReranker:
    """
    Reranks using an arbitrary external scoring function per entry.
    """

    def __init__(
        self,
        scorer: ScoringFn,
        *,
        weight: float = 0.5,
    ) -> None:
        self._scorer = scorer
        self._weight = weight

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        scored: list[tuple[float, MemorySearchResult[Any]]] = []
        for r in results:
            external = max(0.0, min(1.0, self._scorer(r.entry, query)))
            combined = (1.0 - self._weight) * r.score + self._weight * external
            scored.append((combined, r))
        scored.sort(key=lambda item: (round(item[0], 12), item[1].entry.key), reverse=True)
        return [
            MemorySearchResult(entry=r.entry, score=score, distance=r.distance)
            for score, r in scored
        ]


class CompositeReranker:
    """
    Runs several rerankers in sequence, then applies a final
    deterministic ranking pass using the RankingEngine signals.
    """

    def __init__(
        self,
        *,
        steps: Iterable[Reranker] | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        self._steps = list(steps or [])
        defaults = {
            "relevance_weight": 0.5,
            "recency_weight": 0.25,
            "importance_weight": 0.25,
        }
        if weights is not None:
            mapping = {
                "relevance": "relevance_weight",
                "recency": "recency_weight",
                "importance": "importance_weight",
            }
            for key, value in weights.items():
                defaults[mapping.get(key, key)] = value
        self._weights = defaults

    @property
    def steps(self) -> list[Reranker]:
        return list(self._steps)

    def add_step(self, reranker: Reranker) -> None:
        self._steps.append(reranker)

    def rerank(
        self,
        results: list[MemorySearchResult[Any]],
        query: str,
    ) -> list[MemorySearchResult[Any]]:
        current = list(results)
        for step in self._steps:
            current = step.rerank(current, query)
        engine = RankingEngine(**self._weights)
        ranked = engine.rank(current)
        return [item.to_search_result() for item in ranked]