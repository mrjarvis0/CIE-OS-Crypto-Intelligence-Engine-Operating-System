"""
Deduplicator

Detects duplicate vector entries using embedding similarity so the
write pipeline can avoid persisting near-identical content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from memory.vector.embeddings import LocalHashEmbedder
from memory.vector.similarity import SimilarityService


@dataclass(slots=True)
class DedupDecision:
    """
    Outcome of checking a candidate against stored entries.
    """

    is_duplicate: bool
    nearest_key: str | None = None
    similarity: float = 0.0
    threshold: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_duplicate": self.is_duplicate,
            "nearest_key": self.nearest_key,
            "similarity": self.similarity,
            "threshold": self.threshold,
        }


class Deduplicator:
    """
    Detects near-duplicate content before insertion.

    Responsibilities:
        * Embed candidate text
        * Compare against stored candidate vectors
        * Report nearest match and similarity
    """

    def __init__(
        self,
        *,
        embedder: Any | None = None,
        similarity: SimilarityService | None = None,
        threshold: float = 0.95,
    ) -> None:
        self._embedder = embedder or LocalHashEmbedder()
        self._similarity = similarity or SimilarityService(
            default_threshold=threshold
        )
        self._threshold = threshold

    @property
    def embedder(self) -> Any:
        return self._embedder

    @property
    def threshold(self) -> float:
        return self._threshold

    def update_threshold(self, threshold: float) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be within [0.0, 1.0].")
        self._threshold = threshold

    def check_candidates(
        self,
        text: str,
        candidates: Iterable[tuple[str, list[float]]],
        *,
        threshold: float | None = None,
    ) -> DedupDecision:
        """
        Compare ``text`` against candidate (key, vector) pairs.
        """
        query_vec = self._embedder.embed(text)
        threshold_value = (
            threshold if threshold is not None else self._threshold
        )
        best_key: str | None = None
        best_score = 0.0
        for key, vector in candidates:
            if not vector:
                continue
            score = self._similarity.cosine(query_vec, vector)
            if score > best_score:
                best_score = score
                best_key = key
        return DedupDecision(
            is_duplicate=best_score >= threshold_value,
            nearest_key=best_key,
            similarity=best_score,
            threshold=threshold_value,
        )

    async def check_source(
        self,
        text: str,
        memory: Any,
        *,
        namespace: str | None = None,
        collection: str | None = None,
        limit: int = 20,
        threshold: float | None = None,
    ) -> DedupDecision:
        """
        Compare ``text`` against existing entries loaded from a
        ``VectorMemory``-like source.
        """
        load_all = getattr(memory, "load_all", None)
        if not callable(load_all):
            return DedupDecision(
                is_duplicate=False,
                threshold=threshold or self._threshold,
            )
        result = load_all(
            namespace=namespace,
            collection=collection,
        )
        entries = await result if hasattr(result, "__await__") else result
        query_vec = self._embedder.embed(text)
        scored: list[tuple[float, str]] = []
        for entry in entries:
            vector = _extract_vector(entry, self._embedder)
            if vector is None:
                continue
            scored.append(
                (
                    self._similarity.cosine(query_vec, vector),
                    entry.key,
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[:limit]
        if not best:
            return DedupDecision(
                is_duplicate=False,
                threshold=threshold or self._threshold,
            )
        top_score, top_key = best[0]
        return DedupDecision(
            is_duplicate=top_score >= (threshold or self._threshold),
            nearest_key=top_key,
            similarity=top_score,
            threshold=threshold or self._threshold,
        )


def _extract_vector(entry: Any, embedder: Any) -> list[float] | None:
    embedding = getattr(entry, "embedding", None)
    if isinstance(embedding, (list, tuple)) and embedding:
        return list(embedding)
    metadata = getattr(entry, "metadata", None)
    if metadata is not None:
        vector = getattr(metadata, "embedding", None)
        if isinstance(vector, (list, tuple)) and vector:
            return list(vector)
    value = getattr(entry, "value", None)
    if value is not None:
        return embedder.embed(str(value))
    return None
