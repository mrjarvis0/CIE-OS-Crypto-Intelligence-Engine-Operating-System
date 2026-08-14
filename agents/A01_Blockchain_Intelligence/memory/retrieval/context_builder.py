"""
Context Builder

Assembles retrieved memories into structured, token-bounded context
blocks for prompts and downstream consumers. Preserves ordering and
provenance while enforcing configurable token and size limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from memory.base.memory import (
    MemoryEntry,
    MemorySearchResult,
)

DEFAULT_MAX_TOKENS = 2000
DEFAULT_HEADROOM = 0.85


@dataclass(slots=True)
class ContextBlock:
    """
    A single unit of assembled context.
    """

    index: int
    key: str
    text: str
    tokens: int
    score: float
    source: str
    timestamp: str
    namespace: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "key": self.key,
            "text": self.text,
            "tokens": self.tokens,
            "score": self.score,
            "source": self.source,
            "timestamp": self.timestamp,
            "namespace": self.namespace,
        }


@dataclass(slots=True)
class ContextAssembly:
    """
    Final assembled context payload.
    """

    blocks: list[ContextBlock] = field(default_factory=list)
    total_tokens: int = 0
    truncated: bool = False
    dropped: int = 0

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    def to_text(self, separator: str = "\n\n") -> str:
        return separator.join(block.text for block in self.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": [block.to_dict() for block in self.blocks],
            "total_tokens": self.total_tokens,
            "block_count": self.block_count,
            "truncated": self.truncated,
            "dropped": self.dropped,
        }

    def __len__(self) -> int:
        return self.block_count

    def __iter__(self):
        return iter(self.blocks)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count using a whitespace heuristic (4 chars/token).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


class ContextBuilder:
    """
    Builds structured context from retrieved memory entries.

    Responsibilities:
        * Package results into context blocks
        * Enforce token and size limits
        * Preserve ordering and provenance
    """

    def __init__(
        self,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        headroom: float = DEFAULT_HEADROOM,
        tokenizer: Any | None = None,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be strictly positive.")
        if not 0.0 < headroom <= 1.0:
            raise ValueError("headroom must be within (0, 1].")
        self._max_tokens = max_tokens
        self._headroom = headroom
        self._budget = int(max_tokens * headroom)
        self._tokenizer = tokenizer

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def budget(self) -> int:
        return self._budget

    def build(
        self,
        results: Iterable[MemorySearchResult[Any]],
        *,
        format_fn: Any | None = None,
        max_blocks: int | None = None,
    ) -> ContextAssembly:
        """
        Assemble search results into a token-bounded ContextAssembly.

        ``format_fn`` receives (entry, index) and returns text; defaults
        to the entry's string value.
        """
        fmt = format_fn or (lambda entry, index: _entry_text(entry))
        blocks: list[ContextBlock] = []
        total = 0
        truncated = False
        dropped = 0

        for index, result in enumerate(results):
            if max_blocks is not None and len(blocks) >= max_blocks:
                truncated = True
                dropped += 1
                continue
            text = fmt(result.entry, index)
            if not text.strip():
                dropped += 1
                continue
            tokens = self._count_tokens(text)
            if tokens > self._budget:
                truncated = True
                dropped += 1
                continue
            if total + tokens > self._budget:
                truncated = True
                dropped += 1
                continue
            total += tokens
            entry = result.entry
            metadata = entry.metadata
            blocks.append(
                ContextBlock(
                    index=index,
                    key=entry.key,
                    text=text,
                    tokens=tokens,
                    score=result.score,
                    source=metadata.source,
                    timestamp=metadata.created_at.isoformat(),
                    namespace=metadata.namespace,
                )
            )

        return ContextAssembly(
            blocks=blocks,
            total_tokens=total,
            truncated=truncated,
            dropped=dropped,
        )

    def _count_tokens(self, text: str) -> int:
        if self._tokenizer is not None:
            count = self._tokenizer(text)
            if isinstance(count, int):
                return max(0, count)
        return estimate_tokens(text)


def _entry_text(entry: MemoryEntry[Any]) -> str:
    return entry.value if isinstance(entry.value, str) else str(entry.value)
