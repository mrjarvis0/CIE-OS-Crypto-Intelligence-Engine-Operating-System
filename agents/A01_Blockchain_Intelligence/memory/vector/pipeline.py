"""
Vector Write Pipeline

Orchestrates the ingestion path for vector memory: chunking large
text, embedding each chunk, and persisting entries through a
``VectorMemory``-like source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from memory.base.memory import MemoryEntry, MemoryPriority
from memory.vector.chunk import TextChunker

VectorSource = Any


@dataclass(slots=True)
class PipelineReport:
    """
    Result of a pipeline run.
    """

    stored: int = 0
    skipped: int = 0
    failed: int = 0
    keys: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "PipelineReport") -> None:
        self.stored += other.stored
        self.skipped += other.skipped
        self.failed += other.failed
        self.keys.extend(other.keys)
        self.errors.extend(other.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stored": self.stored,
            "skipped": self.skipped,
            "failed": self.failed,
            "keys": self.keys,
            "errors": self.errors,
        }


class VectorWritePipeline:
    """
    Ingests content into vector memory.

    Responsibilities:
        * Chunk long text before embedding
        * Persist entries via the source put()
        * Skip empty or already-present keys when requested
        * Report per-run statistics
    """

    def __init__(
        self,
        memory: VectorSource,
        *,
        chunker: TextChunker | None = None,
        chunk_long_text: bool = True,
    ) -> None:
        self._memory = memory
        self._chunker = chunker or TextChunker()
        self._chunk_long_text = chunk_long_text

    @property
    def memory(self) -> VectorSource:
        return self._memory

    async def put(
        self,
        key: str,
        content: str,
        *,
        namespace: str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        importance: float = 0.5,
        source: str = "runtime",
        expires_at: datetime | None = None,
        overwrite: bool = True,
        **kwargs: Any,
    ) -> PipelineReport:
        """
        Store a single content blob. Long text is chunked into multiple
        entries when configured.
        """
        report = PipelineReport()
        if not content or not content.strip():
            report.skipped += 1
            report.errors.append(f"{key}: empty content")
            return report

        chunks = self._split(content)
        put = getattr(self._memory, "put", None)
        if not callable(put):
            raise AttributeError("memory source must expose put()")

        for index, chunk in enumerate(chunks):
            chunk_key = key if len(chunks) == 1 else f"{key}#{index}"
            if not overwrite and await self._exists(
                chunk_key, namespace, collection
            ):
                report.skipped += 1
                continue
            try:
                result = put(
                    chunk_key,
                    chunk,
                    namespace=namespace,
                    collection=collection,
                    tags=tags,
                    priority=priority,
                    importance=importance,
                    source=source,
                    expires_at=expires_at,
                    **kwargs,
                )
                await result if hasattr(result, "__await__") else None
                report.stored += 1
                report.keys.append(chunk_key)
            except Exception as exc:  # pragma: no cover - defensive
                report.failed += 1
                report.errors.append(f"{chunk_key}: {exc}")
        return report

    async def put_many(
        self,
        entries: Iterable[tuple[str, str]],
        **kwargs: Any,
    ) -> PipelineReport:
        """
        Store many (key, content) pairs, merging per-entry reports.
        """
        report = PipelineReport()
        for key, content in entries:
            report.merge(
                await self.put(key, content, **kwargs)
            )
        return report

    async def _exists(
        self,
        key: str,
        namespace: str | None,
        collection: str | None,
    ) -> bool:
        get_entry = getattr(self._memory, "get", None)
        if not callable(get_entry):
            return False
        result = get_entry(key, namespace=namespace, collection=collection)
        entry = await result if hasattr(result, "__await__") else result
        return entry is not None

    def _split(self, content: str) -> list[str]:
        if not self._chunk_long_text:
            return [content]
        if self._chunker.is_chunked(content):
            return self._chunker.chunk_to_texts(content)
        return [content]

    def estimate(self, content: str) -> dict[str, Any]:
        """
        Report how many entries a blob would produce.
        """
        chunks = self._split(content)
        return {
            "chunks": len(chunks),
            "estimated_entries": len(chunks),
            "chunk_sizes": [len(c) for c in chunks],
        }
