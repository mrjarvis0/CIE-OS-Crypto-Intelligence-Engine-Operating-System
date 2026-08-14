"""
Similarity Service

Computes vector similarity metrics: cosine, dot product, and euclidean
distance with scoring utilities.
"""

from __future__ import annotations

from math import sqrt
from typing import Callable


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"Vector length mismatch: {len(vec_a)} vs {len(vec_b)}"
        )
    if not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sqrt(sum(x * x for x in vec_a))
    norm_b = sqrt(sum(x * x for x in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def dot_product(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"Vector length mismatch: {len(vec_a)} vs {len(vec_b)}"
        )
    return sum(a * b for a, b in zip(vec_a, vec_b))


def euclidean_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"Vector length mismatch: {len(vec_a)} vs {len(vec_b)}"
        )
    return sqrt(sum((a - b) ** 2 for a, b in zip(vec_a, vec_b)))


def manhattan_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"Vector length mismatch: {len(vec_a)} vs {len(vec_b)}"
        )
    return sum(abs(a - b) for a, b in zip(vec_a, vec_b))


def normalize(vector: list[float]) -> list[float]:
    norm = sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return [0.0] * len(vector)
    return [x / norm for x in vector]


def threshold_classify(score: float, threshold: float = 0.5) -> bool:
    return score >= threshold


_DISTANCE_METRICS = frozenset({"euclidean", "manhattan"})


def _is_distance(metric: str | None) -> bool:
    return (metric or "").lower() in _DISTANCE_METRICS


class SimilarityService:
    """
    Computes similarity scores between embedding vectors.

    Responsibilities:
        * Cosine similarity scoring
        * Dot product and distance metrics
        * Threshold-based classification
    """

    def __init__(
        self,
        *,
        default_threshold: float = 0.5,
        default_metric: str = "cosine",
    ) -> None:
        self._default_threshold = default_threshold
        self._default_metric = default_metric
        self._metrics: dict[str, Callable[[list[float], list[float]], float]] = {
            "cosine": cosine_similarity,
            "dot": dot_product,
            "euclidean": euclidean_distance,
            "manhattan": manhattan_distance,
        }

    @property
    def default_threshold(self) -> float:
        return self._default_threshold

    @property
    def default_metric(self) -> str:
        return self._default_metric

    def cosine(self, vec_a: list[float], vec_b: list[float]) -> float:
        return cosine_similarity(vec_a, vec_b)

    def dot(self, vec_a: list[float], vec_b: list[float]) -> float:
        return dot_product(vec_a, vec_b)

    def euclidean(self, vec_a: list[float], vec_b: list[float]) -> float:
        return euclidean_distance(vec_a, vec_b)

    def manhattan(self, vec_a: list[float], vec_b: list[float]) -> float:
        return manhattan_distance(vec_a, vec_b)

    def score(
        self,
        vec_a: list[float],
        vec_b: list[float],
        *,
        metric: str | None = None,
    ) -> float:
        fn = self._metrics.get(metric or self._default_metric)
        if fn is None:
            raise ValueError(f"Unknown metric '{metric or self._default_metric}'")
        return fn(vec_a, vec_b)

    def classify(
        self,
        score: float,
        *,
        threshold: float | None = None,
        metric: str | None = None,
    ) -> bool:
        t = (
            threshold
            if threshold is not None
            else self._default_threshold
        )
        if _is_distance(metric):
            return score <= t
        return score >= t

    def rank(
        self,
        candidates: list[tuple[list[float], str]],
        query_vec: list[float],
        *,
        metric: str | None = None,
    ) -> list[tuple[str, float]]:
        use_metric = metric or self._default_metric
        results = [
            (key, self.score(query_vec, vec, metric=use_metric))
            for vec, key in candidates
        ]
        results.sort(key=lambda x: x[1], reverse=not _is_distance(use_metric))
        return results

    def top_k(
        self,
        candidates: list[tuple[list[float], str]],
        query_vec: list[float],
        *,
        k: int = 10,
        metric: str | None = None,
    ) -> list[tuple[str, float]]:
        ranked = self.rank(candidates, query_vec, metric=metric)
        return ranked[:k]

    def filter_by_threshold(
        self,
        results: list[tuple[str, float]],
        *,
        threshold: float | None = None,
        metric: str | None = None,
    ) -> list[tuple[str, float]]:
        t = (
            threshold
            if threshold is not None
            else self._default_threshold
        )
        if _is_distance(metric):
            return [(key, score) for key, score in results if score <= t]
        return [(key, score) for key, score in results if score >= t]