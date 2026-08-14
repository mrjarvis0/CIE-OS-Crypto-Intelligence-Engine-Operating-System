"""
Context Compressor

Compresses context blocks and long conversations while retaining
essential information.

Research foundations
--------------------
* Anchored iterative summarization — instead of regenerating a full
  summary from scratch on every cycle, extend a persistent anchor summary
  with only the newly evicted span (Factory: 36k session evaluation;
  higher accuracy, completeness and continuity vs full reconstruction).
* Token-budgeted compression — compress only what is needed to fit a
  budget, and always verify the result actually reduces tokens so
  compression can never enlarge the context (agent-memory-compressor).
* Importance-preserving eviction — low-value entries are compressed or
  dropped first; protected / recent entries are retained
  (Zylos Research; Atlan context-compression survey).
* Selective strategy ladder — apply the least-destructive strategy first:
  archive (truncate to reference) < extract facts < summarize
  (agent-memory-compressor three-axis strategy).

Design principles
-----------------
* Deterministic-first: extractive + rule-based compression requires no
  model. An optional ``generator`` callable can be supplied for
  abstractive summarization and is used only when present.
* Monotonic: every successful compression is verified to reduce the
  token count; a compression that enlarges the context is a bug.
* Reversible: archived entries keep a reference to their original
  content so information is never silently lost.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from .importance import ImportanceScorer

# ============================================================
# Public Constants
# ============================================================

DEFAULT_MAX_TOKENS = 4096

DEFAULT_TARGET_RATIO = 0.60

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

TOKEN_SPLIT_RE = re.compile(r"\s+")


def count_tokens(text: str) -> int:
    """Whitespace-based token estimate (deterministic, dependency-free)."""
    stripped = text.strip()
    if not stripped:
        return 0
    return len(TOKEN_SPLIT_RE.split(stripped))


def truncate_to_tokens(text: str, budget: int) -> str:
    """Keep the first ``budget`` whitespace tokens."""
    tokens = TOKEN_SPLIT_RE.split(text.strip())
    if len(tokens) <= budget:
        return text.strip()
    return " ".join(tokens[:budget])


# ============================================================
# Compression Strategies
# ============================================================


class CompressionStrategy(str, Enum):
    """Available context compression strategies."""

    ARCHIVE = "archive"
    EXTRACT = "extract"
    SUMMARIZE = "summarize"
    ANCHORED = "anchored"


@dataclass(slots=True)
class CompressorConfig:
    """Configuration for the context compressor."""

    max_tokens: int = DEFAULT_MAX_TOKENS
    target_ratio: float = DEFAULT_TARGET_RATIO
    preserve_recent: int = 2
    sentence_overlap: int = 1
    importance_threshold: float = 0.40
    generator: Callable[..., Any] | None = None
    retry_attempts: int = 2
    retry_delay: float = 0.2
    timeout: float = 10.0

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0.0 < self.target_ratio <= 1.0:
            raise ValueError("target_ratio must be in (0, 1]")
        if self.preserve_recent < 0:
            raise ValueError("preserve_recent must be non-negative")


@dataclass(slots=True)
class ArchiveRef:
    """A compact reference to archived content."""

    key: str = ""
    fingerprint: str = ""
    original_tokens: int = 0
    archived_at: str = ""
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "fingerprint": self.fingerprint,
            "original_tokens": self.original_tokens,
            "archived_at": self.archived_at,
        }


@dataclass(slots=True)
class CompressedBlock:
    """One compressed unit of context."""

    text: str
    strategy: CompressionStrategy
    tokens: int = 0
    archive: ArchiveRef | None = None


@dataclass(slots=True)
class CompressionResult:
    """Result of compressing a context block."""

    content: str
    blocks: list[CompressedBlock] = field(default_factory=list)
    original_tokens: int = 0
    compressed_tokens: int = 0
    ratio: float = 0.0
    strategy: CompressionStrategy = CompressionStrategy.EXTRACT
    archive: ArchiveRef | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "ratio": round(self.ratio, 4),
            "strategy": self.strategy.value,
            "archive": self.archive.to_dict() if self.archive else None,
        }


@dataclass(slots=True)
class AnchorState:
    """Persistent anchor for iterative summarization."""

    anchor: str = ""
    covered_tokens: int = 0
    generations: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "covered_tokens": self.covered_tokens,
            "generations": self.generations,
            "history": self.history,
        }


# ============================================================
# Context Compressor
# ============================================================


class ContextCompressor:
    """
    Compresses context to fit token budgets while preserving value.

    Responsibilities:
        * Token-aware compression with verified token reduction
        * Importance-preserving eviction (recent / protected first)
        * Strategy ladder: archive -> extract -> summarize -> anchored
        * Anchored iterative summarization across compression cycles
    """

    def __init__(
        self,
        config: CompressorConfig | None = None,
        scorer: ImportanceScorer | None = None,
    ) -> None:
        self._config = config or CompressorConfig()
        self._scorer = scorer or ImportanceScorer()
        self._anchors: dict[str, AnchorState] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> CompressorConfig:
        return self._config

    @property
    def scorer(self) -> ImportanceScorer:
        return self._scorer

    @staticmethod
    def token_count(text: str) -> int:
        """Count whitespace tokens in a string."""
        return count_tokens(text)

    # ------------------------------------------------------------------
    # Sentence / Content Splitting
    # ------------------------------------------------------------------

    def split_sentences(self, text: str) -> list[str]:
        """Split text into sentences on punctuation boundaries."""
        return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]

    def _split_blocks(self, text: str, overlap: int) -> list[str]:
        sentences = self.split_sentences(text)
        if not sentences:
            return [text] if text.strip() else []

        budget = max(1, self._config.max_tokens)
        blocks: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            tokens = count_tokens(sentence)
            if current and current_tokens + tokens > budget:
                blocks.append(" ".join(current))
                carry = current[-overlap:] if overlap else []
                current = list(carry)
                current_tokens = sum(count_tokens(s) for s in carry)
            current.append(sentence)
            current_tokens += tokens

        if current:
            blocks.append(" ".join(current))

        return blocks

    # ------------------------------------------------------------------
    # Importance-Guided Ordering
    # ------------------------------------------------------------------

    def _rank_sentences(
        self,
        text: str,
    ) -> list[tuple[float, str]]:
        sentences = self.split_sentences(text)
        scored: list[tuple[float, str]] = []
        for index, sentence in enumerate(sentences):
            score = self._scorer.score_text(sentence)
            position_bonus = 0.1 / (index + 1)
            scored.append((score + position_bonus, sentence))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Generator Invocation (optional abstractive summary)
    # ------------------------------------------------------------------

    async def _invoke_generator(
        self,
        content: str,
        budget: int,
    ) -> str | None:
        generator = self._config.generator
        if generator is None:
            return None
        attempts = max(1, self._config.retry_attempts)
        if inspect.iscoroutinefunction(generator):
            for attempt in range(attempts):
                try:
                    result = await asyncio.wait_for(
                        generator(content=content, max_tokens=budget),
                        timeout=self._config.timeout,
                    )
                    if result is None:
                        raise ValueError("empty generator result")
                    return str(result).strip()
                except Exception:  # noqa: BLE001
                    if attempt < attempts - 1:
                        await asyncio.sleep(self._config.retry_delay)
            return None
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        generator,
                        content=content,
                        max_tokens=budget,
                    ),
                    timeout=self._config.timeout,
                )
                if result is None:
                    return None
                return str(result).strip()
            except Exception:  # noqa: BLE001
                if attempt < attempts - 1:
                    await asyncio.sleep(self._config.retry_delay)
        return None

    # ------------------------------------------------------------------
    # Strategy: Archive
    # ------------------------------------------------------------------

    def _archive(
        self,
        text: str,
        *,
        key: str = "",
    ) -> CompressedBlock:
        import hashlib
        import time
        from datetime import UTC, datetime

        original_tokens = count_tokens(text)
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        if original_tokens > 3:
            reference = (
                f"[archived:{fingerprint}]"
                f"(tokens={original_tokens}, first={truncate_to_tokens(text, 8)})"
            )
        else:
            reference = text

        ref = ArchiveRef(
            key=key or fingerprint,
            fingerprint=fingerprint,
            original_tokens=original_tokens,
            archived_at=datetime.now(UTC).isoformat(),
            content=text,
        )

        return CompressedBlock(
            text=reference,
            strategy=CompressionStrategy.ARCHIVE,
            tokens=count_tokens(reference),
            archive=ref,
        )

    # ------------------------------------------------------------------
    # Strategy: Extract
    # ------------------------------------------------------------------

    def _extract(
        self,
        text: str,
        *,
        budget: int,
    ) -> CompressedBlock:
        ranked = self._rank_sentences(text)
        selected: list[str] = []
        selected_tokens = 0
        for score, sentence in ranked:
            tokens = count_tokens(sentence)
            if selected_tokens + tokens > budget and selected:
                break
            selected.append(sentence)
            selected_tokens += tokens
            if selected_tokens >= budget:
                break

        compressed = " ".join(selected) if selected else truncate_to_tokens(text, budget)
        final_text = truncate_to_tokens(compressed, budget)
        return CompressedBlock(
            text=final_text,
            strategy=CompressionStrategy.EXTRACT,
            tokens=count_tokens(final_text),
        )

    # ------------------------------------------------------------------
    # Strategy: Summarize
    # ------------------------------------------------------------------

    async def _summarize(
        self,
        text: str,
        *,
        budget: int,
        key: str = "",
    ) -> CompressedBlock:
        generated = await self._invoke_generator(text, budget)
        if generated:
            final_text = truncate_to_tokens(generated, budget)
            return CompressedBlock(
                text=final_text,
                strategy=CompressionStrategy.SUMMARIZE,
                tokens=count_tokens(final_text),
            )

        block = self._extract(text, budget=budget)
        return CompressedBlock(
            text=block.text,
            strategy=CompressionStrategy.SUMMARIZE,
            tokens=block.tokens,
        )

    # ------------------------------------------------------------------
    # Anchored Iterative Summarization
    # ------------------------------------------------------------------

    def get_anchor(self, key: str) -> AnchorState | None:
        """Return the persisted anchor for a conversation key."""
        return self._anchors.get(key)

    def anchor_state(self, key: str) -> AnchorState:
        """Return the anchor state, creating it if needed."""
        return self._anchors.setdefault(key, AnchorState())

    def anchor_summary(self, key: str) -> str:
        """Return the current anchor summary text."""
        state = self._anchors.get(key)
        return state.anchor if state else ""

    async def extend_anchor(
        self,
        key: str,
        new_content: str,
        *,
        budget: int | None = None,
    ) -> str:
        """
        Anchored iterative summarization.

        Instead of regenerating the whole summary from scratch, merge the
        new span's summary into the existing anchor summary (Factory
        approach). Returns the merged anchor text.
        """
        budget = budget or self._config.max_tokens
        state = self._anchors.setdefault(key, AnchorState())

        span_budget = max(1, min(budget, budget // 2))
        span_summary = self._extract(
            new_content,
            budget=span_budget,
        )

        anchor_tokens = count_tokens(state.anchor)
        span_tokens = count_tokens(span_summary.text)

        anchor_budget = max(0, budget - span_tokens)
        anchor_part = truncate_to_tokens(state.anchor, anchor_budget)

        combined = anchor_part
        if anchor_part and span_summary.text:
            combined += " "
        combined += span_summary.text

        combined = truncate_to_tokens(combined, budget)

        state.anchor = combined
        state.covered_tokens += count_tokens(new_content)
        state.generations += 1
        state.history.append({
            "generation": state.generations,
            "span_tokens": span_tokens,
            "anchor_tokens_before": anchor_tokens,
            "anchor_tokens_after": count_tokens(combined),
        })

        return combined

    # ------------------------------------------------------------------
    # Main Compression Entry Point
    # ------------------------------------------------------------------

    async def compress(
        self,
        content: str,
        *,
        budget: int | None = None,
        strategy: CompressionStrategy | str = CompressionStrategy.EXTRACT,
        key: str = "",
    ) -> CompressionResult:
        """
        Compress content down to a token budget.

        The default is extractive compression. When ``key`` is supplied,
        the anchored strategy is available for iterative sessions.
        """
        if isinstance(strategy, str):
            strategy = CompressionStrategy(strategy)

        budget = budget or self._config.max_tokens
        original_tokens = count_tokens(content)

        if strategy is CompressionStrategy.ANCHORED and not key:
            raise ValueError("anchored strategy requires a conversation key")

        if original_tokens <= budget and strategy in (
            CompressionStrategy.EXTRACT,
            CompressionStrategy.SUMMARIZE,
        ):
            return CompressionResult(
                content=truncate_to_tokens(content, budget),
                blocks=[
                    CompressedBlock(
                        text=content,
                        strategy=CompressionStrategy.EXTRACT,
                        tokens=original_tokens,
                    )
                ],
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                ratio=1.0,
                strategy=strategy,
            )

        if strategy is CompressionStrategy.ARCHIVE:
            block = self._archive(content, key=key)
            result_content = block.text
            archive = block.archive
        elif strategy is CompressionStrategy.SUMMARIZE:
            block = await self._summarize(content, budget=budget, key=key)
            result_content = block.text
            archive = None
        elif strategy is CompressionStrategy.ANCHORED:
            if not key:
                raise ValueError("anchored strategy requires a conversation key")
            anchor = await self.extend_anchor(key, content, budget=budget)
            result_content = anchor
            block = CompressedBlock(
                text=anchor,
                strategy=CompressionStrategy.ANCHORED,
                tokens=count_tokens(anchor),
            )
            archive = None
        else:
            block = self._extract(content, budget=budget)
            result_content = block.text
            archive = None

        compressed_tokens = count_tokens(result_content)

        if compressed_tokens > original_tokens:
            result_content = truncate_to_tokens(content, budget)
            compressed_tokens = count_tokens(result_content)
            block = CompressedBlock(
                text=result_content,
                strategy=CompressionStrategy.EXTRACT,
                tokens=compressed_tokens,
            )

        return CompressionResult(
            content=result_content,
            blocks=[block],
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            ratio=round(compressed_tokens / max(1, original_tokens), 4),
            strategy=strategy,
            archive=archive,
        )

    # ------------------------------------------------------------------
    # Batch API
    # ------------------------------------------------------------------

    async def compress_blocks(
        self,
        blocks: Iterable[str],
        *,
        budget: int | None = None,
        strategy: CompressionStrategy | str = CompressionStrategy.EXTRACT,
        key_prefix: str = "block",
    ) -> list[CompressionResult]:
        """Compress a sequence of blocks independently."""
        budget = budget or self._config.max_tokens
        block_list = list(blocks)
        per_block = max(1, budget // max(1, len(block_list)))
        results: list[CompressionResult] = []
        for index, block in enumerate(block_list):
            result = await self.compress(
                block,
                budget=per_block,
                strategy=strategy,
                key=f"{key_prefix}:{index}",
            )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def statistics(self) -> dict[str, Any]:
        """Return compressor usage statistics."""
        return {
            "anchors": len(self._anchors),
            "generations": sum(
                state.generations for state in self._anchors.values()
            ),
            "covered_tokens": sum(
                state.covered_tokens for state in self._anchors.values()
            ),
        }
