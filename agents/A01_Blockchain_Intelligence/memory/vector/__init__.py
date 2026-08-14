"""
Memory Vector Package

Vector storage and retrieval: embeddings, similarity, chunking,
retrieval, search, namespaces, collections, index, deduplication,
snapshots, compaction, metrics, batch operations, and store adapters.
"""

from __future__ import annotations

from memory.vector.adapter import VectorAdapter
from memory.vector.batch import BatchOperator, BatchResult
from memory.vector.cache import CacheStats, EmbeddingCache
from memory.vector.chroma_store import ChromaDocument, ChromaStore
from memory.vector.chunk import Chunk, TextChunker
from memory.vector.dedup import DedupDecision, Deduplicator
from memory.vector.embeddings import (
    EmbeddingService,
    LocalHashEmbedder,
    ResilientEmbedding,
)
from memory.vector.maintenance import (
    IndexStatus,
    MaintenanceReport,
    VectorCompactor,
    VectorIndex,
    VectorMetrics,
    VectorMetricsCollector,
)
from memory.vector.pipeline import PipelineReport, VectorWritePipeline
from memory.vector.retriever import (
    RetrievalQuery,
    RetrievalResult,
    VectorRetriever,
)
from memory.vector.scoring import (
    ScoreAggregator,
    ScoredResult,
    min_max_scale,
    reciprocal_rank_score,
)
from memory.vector.search import SearchExecutor, SearchPlan
from memory.vector.similarity import (
    SimilarityService,
    cosine_similarity,
    dot_product,
    euclidean_distance,
    manhattan_distance,
    normalize,
)
from memory.vector.spaces import (
    CollectionError,
    CollectionManager,
    CollectionNotFoundError,
    NamespaceError,
    NamespaceExistsError,
    NamespaceManager,
    NamespaceNotFoundError,
    SnapshotError,
    SnapshotManager,
)

__all__ = [
    "BatchOperator",
    "BatchResult",
    "CacheStats",
    "ChromaDocument",
    "ChromaStore",
    "Chunk",
    "CollectionError",
    "CollectionManager",
    "CollectionNotFoundError",
    "DedupDecision",
    "Deduplicator",
    "EmbeddingCache",
    "EmbeddingService",
    "IndexStatus",
    "LocalHashEmbedder",
    "MaintenanceReport",
    "NamespaceError",
    "NamespaceManager",
    "NamespaceNotFoundError",
    "PipelineReport",
    "RetrievalQuery",
    "RetrievalResult",
    "ResilientEmbedding",
    "ScoreAggregator",
    "ScoredResult",
    "SearchExecutor",
    "SearchPlan",
    "SimilarityService",
    "SnapshotManager",
    "TextChunker",
    "VectorAdapter",
    "VectorCompactor",
    "VectorIndex",
    "VectorMetrics",
    "VectorMetricsCollector",
    "VectorRetriever",
    "VectorWritePipeline",
    "cosine_similarity",
    "dot_product",
    "euclidean_distance",
    "manhattan_distance",
    "min_max_scale",
    "normalize",
    "reciprocal_rank_score",
]
