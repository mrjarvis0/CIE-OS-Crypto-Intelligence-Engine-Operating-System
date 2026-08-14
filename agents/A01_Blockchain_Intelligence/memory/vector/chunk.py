"""
Text Chunker

Splits long text into overlapping chunks suitable for embedding,
with size and overlap controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(slots=True)
class Chunk:
    """
    A single text fragment.
    """

    index: int
    text: str
    start: int = 0
    end: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.text)


class TextChunker:
    """
    Splits text into overlapping chunks.

    Responsibilities:
        * Enforce a maximum chunk size
        * Maintain overlap between adjacent chunks
        * Break on whitespace to avoid splitting words mid-token
    """

    def __init__(
        self,
        *,
        max_chars: int = 512,
        overlap_chars: int = 64,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be strictly positive.")
        if overlap_chars < 0 or overlap_chars >= max_chars:
            raise ValueError(
                "overlap_chars must be non-negative and smaller than max_chars."
            )
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    @property
    def max_chars(self) -> int:
        return self._max_chars

    @property
    def overlap_chars(self) -> int:
        return self._overlap_chars

    def is_chunked(self, text: str) -> bool:
        return len(text) > self._max_chars

    def chunk(self, text: str) -> list[Chunk]:
        """
        Split ``text`` into overlapping chunks.
        """
        if not text:
            return []
        if not self.is_chunked(text):
            return [Chunk(index=0, text=text, start=0, end=len(text))]

        chunks: list[Chunk] = []
        step = self._max_chars - self._overlap_chars
        start = 0
        index = 0
        length = len(text)

        while start < length:
            end = min(start + self._max_chars, length)
            fragment = text[start:end]
            trimmed = _trim_end(fragment)
            if trimmed:
                chunks.append(
                    Chunk(
                        index=index,
                        text=trimmed,
                        start=start,
                        end=start + len(trimmed),
                    )
                )
                index += 1
            if end >= length:
                break
            advance = len(trimmed) - self._overlap_chars
            if advance < 1:
                advance = step
            start += advance
            if start >= length:
                break

        return chunks

    def chunk_to_texts(self, text: str) -> list[str]:
        return [chunk.text for chunk in self.chunk(text)]

    def chunk_batch(self, texts: Iterable[str]) -> list[list[Chunk]]:
        return [self.chunk(text) for text in texts]

    def stats(self, text: str) -> dict[str, object]:
        chunks = self.chunk(text)
        sizes = [len(c) for c in chunks]
        return {
            "source_length": len(text),
            "chunk_count": len(chunks),
            "max_size": self._max_chars,
            "overlap": self._overlap_chars,
            "min_chunk_size": min(sizes) if sizes else 0,
            "max_chunk_size": max(sizes) if sizes else 0,
        }


def _trim_end(fragment: str) -> str:
    """
    Trim trailing whitespace so a fragment never ends mid-word, but
    never return empty for a non-empty fragment.
    """
    stripped = fragment.rstrip()
    if not stripped:
        return fragment
    return stripped
