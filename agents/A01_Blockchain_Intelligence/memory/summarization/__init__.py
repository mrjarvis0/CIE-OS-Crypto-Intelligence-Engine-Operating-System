"""
Memory Summarization Package

Summarization and filtering: summarizer, compressor, importance, and memory filter.

The MemorySummarizer engine in memory.base.summarizer is the primary
knowledge-extraction entry point. This package provides the modular,
deterministic scoring / compression / filtering components used to
manage context growth and retention decisions:

* ImportanceScorer — multi-signal importance scoring (recency, type,
  keyword, frequency, confidence).
* ContextCompressor — token-budgeted compression with anchored
  iterative summarization.
* MemoryFilter — selective retention and semantic deduplication.
"""

from memory.summarization.importance import (
    ImportanceScorer,
    ImportanceScorerConfig,
    MemoryImportanceLevel,
    ScoredEntry,
    SignalBundle,
)
from memory.summarization.compressor import (
    AnchorState,
    ArchiveRef,
    CompressedBlock,
    CompressionResult,
    CompressionStrategy,
    CompressorConfig,
    ContextCompressor,
    count_tokens,
    truncate_to_tokens,
)
from memory.summarization.memory_filter import (
    DropReason,
    FilterDecision,
    FilterResult,
    MemoryFilter,
    MemoryFilterConfig,
    RetainReason,
    token_overlap_similarity,
)
from memory.summarization.pipeline import (
    PipelineResult,
    PipelineStage,
    SummarizationPipeline,
)

__all__ = [
    "ImportanceScorer",
    "ImportanceScorerConfig",
    "MemoryImportanceLevel",
    "ScoredEntry",
    "SignalBundle",
    "AnchorState",
    "ArchiveRef",
    "CompressedBlock",
    "CompressionResult",
    "CompressionStrategy",
    "CompressorConfig",
    "ContextCompressor",
    "count_tokens",
    "truncate_to_tokens",
    "DropReason",
    "FilterDecision",
    "FilterResult",
    "MemoryFilter",
    "MemoryFilterConfig",
    "RetainReason",
    "token_overlap_similarity",
    "PipelineResult",
    "PipelineStage",
    "SummarizationPipeline",
]
