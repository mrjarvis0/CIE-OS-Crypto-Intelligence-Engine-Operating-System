"""
Embedding Cache

Explicit LRU cache for embeddings with TTL, statistics, and eviction
controls. Complements the embedder's internal cache for cases where
callers want a separate, observable cache.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class CacheStats:
    """
    Cache accounting snapshot.
    """

    size: int = 0
    capacity: int = 0
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    hit_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "capacity": self.capacity,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": self.hit_rate,
        }


class EmbeddingCache:
    """
    LRU cache for embedding vectors with optional TTL.

    Responsibilities:
        * Store embeddings by text key
        * Enforce a bounded capacity with LRU eviction
        * Track hit/miss statistics
    """

    def __init__(
        self,
        *,
        capacity: int = 10_000,
        ttl_seconds: float | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be strictly positive.")
        self._capacity = capacity
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[list[float], float]] = (
            OrderedDict()
        )
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._cache)

    def get(self, key: str) -> list[float] | None:
        item = self._cache.get(key)
        if item is None:
            self._misses += 1
            return None
        vector, stored_at = item
        if self._is_expired(stored_at):
            self._evict(key)
            self._misses += 1
            return None
        self._hits += 1
        self._cache.move_to_end(key)
        return list(vector)

    def set(self, key: str, vector: list[float]) -> None:
        now = _now_seconds()
        if key in self._cache:
            self._cache[key] = (list(vector), now)
            self._cache.move_to_end(key)
            return
        while len(self._cache) >= self._capacity:
            self._cache.popitem(last=False)
            self._evictions += 1
        self._cache[key] = (list(vector), now)

    def get_or_compute(
        self,
        key: str,
        compute: Any,
    ) -> list[float]:
        cached = self.get(key)
        if cached is not None:
            return cached
        vector = compute()
        self.set(key, vector)
        return vector

    def contains(self, key: str) -> bool:
        item = self._cache.get(key)
        if item is None:
            return False
        if self._is_expired(item[1]):
            self._evict(key)
            return False
        return True

    def remove(self, key: str) -> bool:
        return self._evict(key)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def prune_expired(self) -> int:
        now = _now_seconds()
        expired = [
            key
            for key, (_, stored_at) in self._cache.items()
            if self._is_expired(stored_at, now=now)
        ]
        for key in expired:
            self._evict(key)
        return len(expired)

    def stats(self) -> CacheStats:
        total = self._hits + self._misses
        return CacheStats(
            size=len(self._cache),
            capacity=self._capacity,
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            hit_rate=self._hits / total if total > 0 else 0.0,
        )

    def _is_expired(
        self,
        stored_at: float,
        *,
        now: float | None = None,
    ) -> bool:
        if self._ttl_seconds is None:
            return False
        current = now if now is not None else _now_seconds()
        return current - stored_at >= self._ttl_seconds

    def _evict(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False


def _now_seconds() -> float:
    return datetime.now(UTC).timestamp()
