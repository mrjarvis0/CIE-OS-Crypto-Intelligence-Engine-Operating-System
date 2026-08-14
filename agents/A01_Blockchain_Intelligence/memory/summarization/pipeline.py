"""
Summarization Pipeline

Orchestrates the memory summarization workflow by composing the
modular scoring, filtering, and compression components into a single
pipeline:

    1. Score    — ImportanceScorer assigns a [0,1] importance score.
    2. Filter   — MemoryFilter retains valuable entries, drops expired /
                  low-importance / duplicate entries.
    3. Compress — ContextCompressor compresses retained content to a
                  token budget (archive -> extract -> summarize ->
                  anchored ladder).

This is intentionally an orchestrator only. All behavior lives in the
component modules; the pipeline provides the coordination layer and a
single typed result contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from memory.summarization.compressor import (
    CompressionResult,
    CompressionStrategy,
    CompressorConfig,
    ContextCompressor,
    count_tokens,
)
from memory.summarization.importance import (
    ImportanceScorer,
    ImportanceScorerConfig,
    ScoredEntry,
)
from memory.summarization.memory_filter import (
    FilterResult,
    MemoryFilter,
    MemoryFilterConfig,
)


@dataclass(slots=True)
class PipelineStage:
    """
    Result of a single pipeline stage.
    """

    name: str
    input_count: int = 0
    output_count: int = 0
    detail: Any = None

    def to_dict(self) -> dict[str, Any]:
        detail = self.detail
        if hasattr(detail, "to_dict"):
            detail = detail.to_dict()
        return {
            "name": self.name,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "detail": detail,
        }


@dataclass(slots=True)
class PipelineResult:
    """
    Outcome of a full summarization pipeline run.
    """

    kept: list[Any] = field(default_factory=list)
    dropped: list[Any] = field(default_factory=list)
    scored: list[ScoredEntry] = field(default_factory=list)
    compression: CompressionResult | None = None
    stages: list[PipelineStage] = field(default_factory=list)

    @property
    def kept_count(self) -> int:
        return len(self.kept)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept_count": self.kept_count,
            "dropped_count": self.dropped_count,
            "kept_keys": [
                _entry_key(entry) for entry in self.kept
            ],
            "dropped_keys": [
                _entry_key(entry) for entry in self.dropped
            ],
            "compression": (
                self.compression.to_dict()
                if self.compression
                else None
            ),
            "stages": [stage.to_dict() for stage in self.stages],
        }


class SummarizationPipeline:
    """
    Composes scoring, filtering, and compression into one workflow.

    Responsibilities:
        * Run importance scoring over a batch of entries
        * Apply the retention filter (expired / low / duplicate)
        * Compress the retained content to a token budget
        * Report per-stage statistics
    """

    def __init__(
        self,
        *,
        scorer: ImportanceScorer | None = None,
        memory_filter: MemoryFilter | None = None,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self._scorer = scorer or ImportanceScorer()
        self._memory_filter = memory_filter or MemoryFilter(
            scorer=self._scorer,
        )
        self._compressor = compressor or ContextCompressor(
            scorer=self._scorer,
        )

    @property
    def scorer(self) -> ImportanceScorer:
        return self._scorer

    @property
    def memory_filter(self) -> MemoryFilter:
        return self._memory_filter

    @property
    def compressor(self) -> ContextCompressor:
        return self._compressor

    # ------------------------------------------------------------------
    # Stage 1: Score
    # ------------------------------------------------------------------

    def score(self, entries: Iterable[Any]) -> list[ScoredEntry]:
        return self._scorer.rank(entries)

    # ------------------------------------------------------------------
    # Stage 2: Filter
    # ------------------------------------------------------------------

    def filter(self, entries: Iterable[Any]) -> FilterResult:
        return self._memory_filter.filter(entries)

    # ------------------------------------------------------------------
    # Stage 3: Compress
    # ------------------------------------------------------------------

    async def compress(
        self,
        content: str,
        *,
        budget: int | None = None,
        strategy: CompressionStrategy | str = CompressionStrategy.EXTRACT,
        key: str = "",
    ) -> CompressionResult:
        return await self._compressor.compress(
            content,
            budget=budget,
            strategy=strategy,
            key=key,
        )

    # ------------------------------------------------------------------
    # Full Run
    # ------------------------------------------------------------------

    async def run(
        self,
        entries: Iterable[Any],
        *,
        compress_content: str | None = None,
        budget: int | None = None,
        strategy: CompressionStrategy | str = CompressionStrategy.EXTRACT,
        key: str = "",
    ) -> PipelineResult:
        """
        Execute the full pipeline: score -> filter -> compress.

        When ``compress_content`` is supplied, the retained entries are
        flattened to text and compressed; otherwise the stage is skipped.
        """
        entry_list = list(entries)
        result = PipelineResult()

        # Stage 1: score
        scored = self.score(entry_list)
        result.scored = scored
        result.stages.append(
            PipelineStage(
                name="score",
                input_count=len(entry_list),
                output_count=len(scored),
                detail={
                    "top_score": scored[0].score if scored else 0.0,
                    "levels": _level_breakdown(self._scorer, scored),
                },
            )
        )

        # Stage 2: filter on the original entries (filter re-scores them)
        filter_input = [s.entry for s in scored] if scored else entry_list
        filter_result = self.filter(filter_input)
        result.kept = list(filter_result.kept_entries())
        result.dropped = list(filter_result.dropped_entries())
        result.stages.append(
            PipelineStage(
                name="filter",
                input_count=len(entry_list),
                output_count=result.kept_count,
                detail=filter_result,
            )
        )

        # Stage 3: compress
        if compress_content is not None:
            compression = await self.compress(
                compress_content,
                budget=budget,
                strategy=strategy,
                key=key,
            )
            result.compression = compression
            result.stages.append(
                PipelineStage(
                    name="compress",
                    input_count=count_tokens(compress_content),
                    output_count=compression.compressed_tokens,
                    detail=compression,
                )
            )

        return result

    async def run_content(
        self,
        content: str,
        *,
        budget: int | None = None,
        strategy: CompressionStrategy | str = CompressionStrategy.EXTRACT,
        key: str = "",
    ) -> PipelineResult:
        """
        Convenience path: score + filter a single content string treated
        as one entry, then compress it.
        """
        return await self.run(
            [content],
            compress_content=content,
            budget=budget,
            strategy=strategy,
            key=key,
        )

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def statistics(self) -> dict[str, Any]:
        return {
            "compressor": self._compressor.statistics(),
            "memory_filter_config": {
                "importance_threshold": self._memory_filter.config.importance_threshold,
                "deduplicate": self._memory_filter.config.deduplicate,
                "drop_expired": self._memory_filter.config.drop_expired,
            },
        }


def _entry_key(entry: Any) -> str | None:
    if hasattr(entry, "key"):
        return entry.key
    return None


def _level_breakdown(
    scorer: ImportanceScorer,
    scored: list[ScoredEntry],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in scored:
        level = scorer.level(item.score).value
        counts[level] = counts.get(level, 0) + 1
    return counts
