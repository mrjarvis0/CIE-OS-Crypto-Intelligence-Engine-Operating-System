"""
Lexical Retriever

Exact, prefix, and keyword-overlap retrieval over memory entries.
Provides lightweight text matching without embeddings, complementing
the semantic retriever for fast, deterministic lookups.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from memory.base.memory import (
    MemoryEntry,
    MemorySearchResult,
)

EntrySource = Callable[[], Iterable[MemoryEntry[Any]]]


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[\w-]+\b", text.lower()))


class LexicalRetriever:
    """
    Performs exact, prefix, and keyword-overlap text retrieval.

    Responsibilities:
        * Exact and prefix key matching
        * Token-overlap keyword scoring
        * Deterministic ordering of text matches
    """

    def __init__(
        self,
        *,
        default_limit: int = 10,
        min_overlap: float = 0.0,
    ) -> None:
        self._default_limit = default_limit
        self._min_overlap = min_overlap

    @property
    def default_limit(self) -> int:
        return self._default_limit

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
        source: EntrySource | Iterable[MemoryEntry[Any]] | None = None,
        memory_source: Any | None = None,
        mode: str = "overlap",
    ) -> list[MemorySearchResult[Any]]:
        """
        Retrieve entries using the selected lexical strategy.

        Modes:
            * overlap — token intersection ratio scoring
            * prefix  — substring-prefix matching on values
            * exact   — case-insensitive exact value match
        """
        entries = await self._collect_entries(
            source=source,
            memory_source=memory_source,
        )
        limit_value = self._default_limit if limit is None else limit
        query_norm = query.strip().lower()

        if mode == "exact":
            return self._match_exact(entries, query_norm, limit_value)
        if mode == "prefix":
            return self._match_prefix(entries, query_norm, limit_value)
        if mode == "overlap":
            return self._match_overlap(entries, query_norm, limit_value)
        raise ValueError(f"Unknown lexical mode '{mode}'.")

    def _match_exact(
        self,
        entries: Iterable[MemoryEntry[Any]],
        query_norm: str,
        limit: int,
    ) -> list[MemorySearchResult[Any]]:
        results: list[MemorySearchResult[Any]] = []
        for entry in entries:
            if _as_text(entry.value).strip().lower() == query_norm:
                results.append(
                    MemorySearchResult(entry=entry, score=1.0, distance=0.0)
                )
        return results[:limit]

    def _match_prefix(
        self,
        entries: Iterable[MemoryEntry[Any]],
        query_norm: str,
        limit: int,
    ) -> list[MemorySearchResult[Any]]:
        results: list[MemorySearchResult[Any]] = []
        for entry in entries:
            text = _as_text(entry.value).strip().lower()
            score = 1.0 if text.startswith(query_norm) else 0.0
            if score > 0.0:
                results.append(
                    MemorySearchResult(entry=entry, score=score, distance=1.0 - score)
                )
        results.sort(key=lambda r: (r.score, r.entry.key), reverse=True)
        return results[:limit]

    def _match_overlap(
        self,
        entries: Iterable[MemoryEntry[Any]],
        query_norm: str,
        limit: int,
    ) -> list[MemorySearchResult[Any]]:
        query_tokens = _tokenize(query_norm)
        if not query_tokens:
            return []
        results: list[MemorySearchResult[Any]] = []
        for entry in entries:
            text_tokens = _tokenize(_as_text(entry.value))
            if not text_tokens:
                continue
            overlap = query_tokens & text_tokens
            score = len(overlap) / len(query_tokens)
            if score < self._min_overlap:
                continue
            results.append(
                MemorySearchResult(entry=entry, score=score, distance=1.0 - score)
            )
        results.sort(key=lambda r: (r.score, r.entry.key), reverse=True)
        return results[:limit]

    async def _collect_entries(
        self,
        *,
        source: EntrySource | Iterable[MemoryEntry[Any]] | None,
        memory_source: Any | None,
    ) -> list[MemoryEntry[Any]]:
        if source is not None:
            if callable(source):
                return list(source())
            return list(source)
        if memory_source is not None:
            active = getattr(memory_source, "active_entries", None)
            if callable(active):
                result = active()
                if hasattr(result, "__await__"):
                    return list(await result)
                return list(result)
        raise ValueError(
            "A 'source' callable, iterable, or 'memory_source' with "
            "active_entries() must be provided."
        )
