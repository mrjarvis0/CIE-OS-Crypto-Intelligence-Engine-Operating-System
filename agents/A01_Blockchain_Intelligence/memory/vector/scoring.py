"""
Vector Scoring

Score aggregation and ranking utilities for vector retrieval:
min-max scaling, threshold filtering, weighted fusion, and
rank aggregation across multiple candidate lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from memory.base.memory import MemorySearchResult


@dataclass(slots=True)
class ScoredResult:
    """
    A key with an aggregated score and its per-source breakdown.
    """

    key: str
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "score": self.score,
            "breakdown": self.breakdown,
        }


def min_max_scale(
    scores: Sequence[float],
    *,
    floor: float = 0.0,
    ceiling: float = 1.0,
) -> list[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    span = hi - lo
    if span == 0.0:
        return [ceiling] * len(scores)
    return [
        floor + (s - lo) / span * (ceiling - floor) for s in scores
    ]


def reciprocal_rank_score(
    rank: int,
    *,
    k: int = 60,
) -> float:
    return 1.0 / (k + rank)


class ScoreAggregator:
    """
    Combines per-source scores into a single ranking.

    Responsibilities:
        * Min-max normalize per source
        * Weighted linear fusion
        * Reciprocal-rank fusion (RRF)
        * Threshold filtering
    """

    def __init__(
        self,
        *,
        default_threshold: float | None = None,
    ) -> None:
        self._default_threshold = default_threshold

    def weighted_fuse(
        self,
        sources: dict[str, Sequence[tuple[str, float]]],
        weights: dict[str, float] | None = None,
    ) -> list[ScoredResult]:
        """
        Fuse score lists by weighted linear combination.
        """
        weights = weights or {name: 1.0 for name in sources}
        aggregated: dict[str, dict[str, float]] = {}
        totals: dict[str, float] = {}
        for name, items in sources.items():
            weight = weights.get(name, 1.0)
            if len(items) == 1:
                scaled = [items[0][1]]
            else:
                scaled = min_max_scale([s for _, s in items])
            for (key, _), score in zip(items, scaled):
                breakdown = aggregated.setdefault(key, {})
                breakdown[name] = score * weight
                totals[key] = totals.get(key, 0.0) + score * weight
        results = [
            ScoredResult(key=key, score=score, breakdown=breakdown)
            for key, score in totals.items()
            for breakdown in [aggregated[key]]
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def rrf_fuse(
        self,
        sources: Sequence[Sequence[str]],
        *,
        k: int = 60,
    ) -> list[ScoredResult]:
        """
        Fuse ranked key lists using reciprocal-rank fusion.
        """
        scores: dict[str, float] = {}
        breakdowns: dict[str, dict[str, float]] = {}
        for source_index, ranked in enumerate(sources):
            name = str(source_index)
            for rank, key in enumerate(ranked, start=1):
                add = reciprocal_rank_score(rank, k=k)
                scores[key] = scores.get(key, 0.0) + add
                breakdowns.setdefault(key, {})[name] = add
        results = [
            ScoredResult(key=key, score=score, breakdown=breakdowns[key])
            for key, score in scores.items()
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def filter_threshold(
        self,
        results: list[ScoredResult],
        *,
        threshold: float | None = None,
    ) -> list[ScoredResult]:
        t = (
            threshold
            if threshold is not None
            else self._default_threshold
        )
        if t is None:
            return results
        return [r for r in results if r.score >= t]

    def dedupe(
        self,
        results: Iterable[ScoredResult],
    ) -> list[ScoredResult]:
        seen: dict[str, ScoredResult] = {}
        for result in results:
            if result.key not in seen or result.score > seen[result.key].score:
                seen[result.key] = result
        return sorted(
            seen.values(),
            key=lambda r: r.score,
            reverse=True,
        )

    def from_search_results(
        self,
        results: Sequence[MemorySearchResult[Any]],
    ) -> list[ScoredResult]:
        return [
            ScoredResult(
                key=result.entry.key,
                score=result.score,
                breakdown={},
            )
            for result in results
        ]
