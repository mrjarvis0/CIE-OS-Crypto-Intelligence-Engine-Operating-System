"""
Ranking and Scoring Engine

Scores and orders retrieval results by relevance, recency, importance,
and memory priority, plus normalizes, merges, and fuses scores across
multiple strategies (Reciprocal Rank Fusion, weighted merge).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Iterable

from memory.base.memory import (
    MemoryEntry,
    MemoryPriority,
    MemorySearchResult,
)


def _now() -> datetime:
    return datetime.now(UTC)


def recency_factor(
    updated_at: datetime,
    *,
    reference: datetime | None = None,
    half_life_hours: float = 24.0,
) -> float:
    """
    Exponential recency decay in the [0, 1] range.

    A memory updated exactly ``half_life_hours`` before the reference
    time scores 0.5.
    """
    if half_life_hours <= 0.0:
        raise ValueError("half_life_hours must be strictly positive.")
    ref = reference or _now()
    delta_hours = max(0.0, (ref - updated_at).total_seconds() / 3600.0)
    return math.exp(-math.log(2.0) * delta_hours / half_life_hours)


def importance_factor(
    priority: MemoryPriority,
    confidence: float,
) -> float:
    """
    Combine memory priority and confidence into a [0, 1] importance
    signal. Priority is normalized by the CRITICAL ceiling.
    """
    normalized_priority = min(1.0, priority.value / MemoryPriority.CRITICAL.value)
    return 0.6 * normalized_priority + 0.4 * confidence


class RankedResult:
    """
    A retrieval result carrying its composite score breakdown.
    """

    __slots__ = ("entry", "score", "relevance", "recency", "importance", "distance")

    def __init__(
        self,
        entry: MemoryEntry[Any],
        *,
        score: float,
        relevance: float,
        recency: float,
        importance: float,
        distance: float | None = None,
    ) -> None:
        self.entry = entry
        self.score = score
        self.relevance = relevance
        self.recency = recency
        self.importance = importance
        self.distance = distance

    def to_search_result(self) -> MemorySearchResult[Any]:
        return MemorySearchResult(
            entry=self.entry,
            score=self.score,
            distance=self.distance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.entry.key,
            "score": self.score,
            "relevance": self.relevance,
            "recency": self.recency,
            "importance": self.importance,
            "distance": self.distance,
        }

    def __repr__(self) -> str:
        return (
            f"RankedResult(key={self.entry.key!r}, "
            f"score={self.score:.4f})"
        )


class RankingEngine:
    """
    Ranks retrieval results by composite relevance and quality signals.

    Responsibilities:
        * Compute a weighted composite score per result
        * Apply recency and importance weighting
        * Order results deterministically with tie-breaks
    """

    def __init__(
        self,
        *,
        relevance_weight: float = 0.5,
        recency_weight: float = 0.25,
        importance_weight: float = 0.25,
        half_life_hours: float = 24.0,
    ) -> None:
        total = relevance_weight + recency_weight + importance_weight
        if total <= 0.0:
            raise ValueError("Total weight must be strictly positive.")
        self._relevance_weight = relevance_weight
        self._recency_weight = recency_weight
        self._importance_weight = importance_weight
        self._half_life_hours = half_life_hours

    @property
    def weights(self) -> dict[str, float]:
        return {
            "relevance": self._relevance_weight,
            "recency": self._recency_weight,
            "importance": self._importance_weight,
        }

    def rank(
        self,
        results: Iterable[MemorySearchResult[Any]],
        *,
        reference: datetime | None = None,
    ) -> list[RankedResult]:
        """
        Rank raw search results into an ordered list of RankedResult.
        """
        ref = reference or _now()
        ranked: list[RankedResult] = []
        for result in results:
            entry = result.entry
            relevance = max(0.0, min(1.0, result.score))
            recency = recency_factor(
                entry.metadata.updated_at,
                reference=ref,
                half_life_hours=self._half_life_hours,
            )
            importance = importance_factor(
                entry.metadata.priority,
                entry.metadata.confidence,
            )
            composite = (
                self._relevance_weight * relevance
                + self._recency_weight * recency
                + self._importance_weight * importance
            )
            ranked.append(
                RankedResult(
                    entry=entry,
                    score=composite,
                    relevance=relevance,
                    recency=recency,
                    importance=importance,
                    distance=result.distance,
                )
            )
        ranked.sort(
            key=lambda item: (
                round(item.score, 12),
                item.entry.metadata.priority.value,
                item.entry.key,
            ),
            reverse=True,
        )
        return ranked

    def rank_entries(
        self,
        entries: Iterable[MemoryEntry[Any]],
        *,
        relevance: float = 0.0,
        reference: datetime | None = None,
    ) -> list[RankedResult]:
        """
        Rank plain entries using metadata-only signals.
        """
        ref = reference or _now()
        ranked: list[RankedResult] = []
        for entry in entries:
            recency = recency_factor(
                entry.metadata.updated_at,
                reference=ref,
                half_life_hours=self._half_life_hours,
            )
            importance = importance_factor(
                entry.metadata.priority,
                entry.metadata.confidence,
            )
            composite = (
                self._relevance_weight * relevance
                + self._recency_weight * recency
                + self._importance_weight * importance
            )
            ranked.append(
                RankedResult(
                    entry=entry,
                    score=composite,
                    relevance=relevance,
                    recency=recency,
                    importance=importance,
                )
            )
        ranked.sort(
            key=lambda item: (
                round(item.score, 12),
                item.entry.metadata.priority.value,
                item.entry.key,
            ),
            reverse=True,
        )
        return ranked

    def top_k(
        self,
        results: Iterable[MemorySearchResult[Any]],
        *,
        k: int = 10,
        reference: datetime | None = None,
    ) -> list[RankedResult]:
        """
        Return the k highest-ranked results.
        """
        if k < 0:
            raise ValueError("k must be non-negative.")
        return self.rank(results, reference=reference)[:k]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """
    Clamp a numeric score into the inclusive [low, high] range.
    """
    if value < low:
        return low
    if value > high:
        return high
    return value


def normalize_scores(scores: Iterable[float]) -> list[float]:
    """
    Min-max normalize a collection of scores to the [0, 1] range.

    When every input is equal, returns all zeros.
    """
    values = list(scores)
    if not values:
        return []
    low = min(values)
    high = max(values)
    span = high - low
    if span == 0.0:
        return [0.0 for _ in values]
    return [(value - low) / span for value in values]


def softmax_scores(scores: Iterable[float], temperature: float = 1.0) -> list[float]:
    """
    Convert raw scores into a softmax probability distribution.

    temperature < 1 sharpens the distribution; > 1 flattens it.
    """
    values = list(scores)
    if not values:
        return []
    if temperature <= 0.0:
        raise ValueError("Temperature must be strictly positive.")
    scaled = [value / temperature for value in values]
    max_scaled = max(scaled)
    exps = [math.exp(value - max_scaled) for value in scaled]
    total = sum(exps)
    if total == 0.0:
        return [0.0 for _ in values]
    return [exp / total for exp in exps]


def reciprocal_rank_fusion(
    ranked_lists: Iterable[Iterable[Any]],
    *,
    k: int = 60,
    weight: float = 1.0,
) -> list[tuple[Any, float]]:
    """
    Fuse multiple ranked lists using Reciprocal Rank Fusion.

    The constant ``k`` (default 60, from Cormack et al.) softens the
    rank contribution so early positions dominate without exploding.

    Returns a deduplicated list of (item, fused_score) sorted by score
    descending. Items are hashed by identity when unhashable.
    """
    if k <= 0:
        raise ValueError("k must be strictly positive.")
    accumulator: dict[Any, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            key = item if isinstance(item, (str, int, float, tuple, frozenset)) else id(item)
            accumulator[key] = accumulator.get(key, 0.0) + weight / (k + rank)
    fused = sorted(accumulator.items(), key=lambda pair: pair[1], reverse=True)
    return fused


def weighted_merge(
    *ranked_lists: Iterable[tuple[Any, float]],
    weights: Iterable[float] | None = None,
) -> list[tuple[Any, float]]:
    """
    Merge multiple (item, score) lists using per-list weights.

    Each list contributes ``weight * score`` to a shared accumulator.
    Items appearing in several lists accumulate their weighted scores.
    """
    lists = [list(items) for items in ranked_lists]
    if not lists:
        return []
    weight_values = list(weights) if weights is not None else [1.0] * len(lists)
    if len(weight_values) != len(lists):
        raise ValueError("Weights must match the number of ranked lists.")
    accumulator: dict[Any, float] = {}
    for items, w in zip(lists, weight_values):
        for item, score in items:
            key = item if isinstance(item, (str, int, float, tuple, frozenset)) else id(item)
            accumulator[key] = accumulator.get(key, 0.0) + w * score
    merged = sorted(accumulator.items(), key=lambda pair: pair[1], reverse=True)
    return merged


class ScoreAggregator:
    """
    Aggregates multiple numeric signals into one composite score.

    Responsibilities:
        * Combine weighted score components
        * Normalize each component before merging
        * Expose an explainable breakdown
    """

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        normalize: bool = True,
    ) -> None:
        self._weights = weights or {}
        self._normalize = normalize

    def add_signal(self, name: str, weight: float) -> None:
        """
        Register (or overwrite) a named weighted signal.
        """
        self._weights[name] = weight

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    def aggregate(
        self,
        signals: dict[str, float],
    ) -> tuple[float, dict[str, float]]:
        """
        Combine weighted signals into a single score.

        Returns (composite, contribution_breakdown).
        """
        unknown = set(signals) - set(self._weights)
        if unknown:
            raise ValueError(f"Unregistered signals: {sorted(unknown)}")
        missing = set(self._weights) - set(signals)
        if missing:
            raise ValueError(f"Missing signals: {sorted(missing)}")
        total_weight = sum(self._weights.values())
        if total_weight == 0.0:
            raise ValueError("Total signal weight must be non-zero.")
        values = [signals[name] for name in self._weights]
        normalized = normalize_scores(values) if self._normalize else list(values)
        breakdown: dict[str, float] = {}
        composite = 0.0
        for name, norm_value in zip(self._weights, normalized):
            contribution = (self._weights[name] / total_weight) * norm_value
            breakdown[name] = contribution
            composite += contribution
        return composite, breakdown
