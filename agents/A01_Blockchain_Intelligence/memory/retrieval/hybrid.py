"""
Hybrid Retriever

Combines semantic, lexical, and metadata retrieval strategies into a
unified, ranked result set using Reciprocal Rank Fusion and weighted
merging.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from memory.base.memory import (
    EmbeddingProvider,
    MemoryEntry,
    MemorySearchResult,
)
from memory.retrieval.lexical import LexicalRetriever
from memory.retrieval.ranking import reciprocal_rank_fusion, weighted_merge
from memory.retrieval.semantic import SemanticRetriever

EntrySource = Callable[[], Iterable[MemoryEntry[Any]]]

DEFAULT_WEIGHTS = {"semantic": 0.6, "lexical": 0.4}


class HybridRetriever:
    """
    Merges multiple retrieval strategies into one ranked result set.

    Responsibilities:
        * Execute semantic and lexical searches
        * Normalize and merge scores via RRF / weighted merge
        * Apply ranking and deduplication
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider | None = None,
        semantic: SemanticRetriever | None = None,
        lexical: LexicalRetriever | None = None,
        weights: dict[str, float] | None = None,
        default_limit: int = 10,
    ) -> None:
        self._semantic = semantic or SemanticRetriever(embedder=embedder)
        self._lexical = lexical or LexicalRetriever()
        self._weights = weights or DEFAULT_WEIGHTS
        self._default_limit = default_limit

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
        source: EntrySource | Iterable[MemoryEntry[Any]] | None = None,
        memory_source: Any | None = None,
        threshold: float | None = None,
        fusion: str = "rrf",
        semantic_weight: float | None = None,
        lexical_weight: float | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Run semantic + lexical retrieval and fuse the results.

        ``fusion`` selects 'rrf' (Reciprocal Rank Fusion) or 'weighted'
        (weighted score merge).
        """
        limit_value = self._default_limit if limit is None else limit
        semantic_results = await self._semantic.retrieve(
            query,
            limit=limit_value,
            source=source,
            memory_source=memory_source,
            threshold=threshold,
        )
        lexical_results = await self._lexical.retrieve(
            query,
            limit=limit_value,
            source=source,
            memory_source=memory_source,
        )
        return self._fuse(
            semantic_results,
            lexical_results,
            limit=limit_value,
            fusion=fusion,
            semantic_weight=semantic_weight,
            lexical_weight=lexical_weight,
        )

    def _fuse(
        self,
        semantic: list[MemorySearchResult[Any]],
        lexical: list[MemorySearchResult[Any]],
        *,
        limit: int,
        fusion: str,
        semantic_weight: float | None,
        lexical_weight: float | None,
    ) -> list[MemorySearchResult[Any]]:
        if fusion == "rrf":
            fused = reciprocal_rank_fusion(
                [[r.entry.key for r in semantic], [r.entry.key for r in lexical]],
            )
        elif fusion == "weighted":
            w_semantic = semantic_weight if semantic_weight is not None else self._weights.get("semantic", 0.6)
            w_lexical = lexical_weight if lexical_weight is not None else self._weights.get("lexical", 0.4)
            fused = weighted_merge(
                [(r.entry.key, r.score) for r in semantic],
                [(r.entry.key, r.score) for r in lexical],
                weights=[w_semantic, w_lexical],
            )
        else:
            raise ValueError(f"Unknown fusion mode '{fusion}'.")

        by_key: dict[str, MemorySearchResult[Any]] = {
            r.entry.key: r for r in [*semantic, *lexical]
        }
        results: list[MemorySearchResult[Any]] = []
        for key, score in fused[:limit]:
            original = by_key.get(key)
            if original is None:
                continue
            results.append(
                MemorySearchResult(
                    entry=original.entry,
                    score=score,
                    distance=original.distance,
                )
            )
        return results
