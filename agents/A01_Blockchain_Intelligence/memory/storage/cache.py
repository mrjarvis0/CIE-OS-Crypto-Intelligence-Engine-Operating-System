"""
Cache Storage

In-memory cache storage backend with TTL expiration and LRU eviction.
Provides fast, volatile memory for hot entries without persistence.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Sequence

from memory.base.memory import MemoryEntry
from memory.storage.repository import (
    StorageConnectionError,
    entry_payload_matches,
)

DEFAULT_MAX_SIZE = 10_000
DEFAULT_TTL_SECONDS = 300.0


class CacheStorage:
    """
    In-memory cache backend for memory.

    Responsibilities:
        * TTL-based expiration
        * LRU/FIFO eviction
        * Namespace-aware caching
    """

    def __init__(
        self,
        *,
        max_size: int = DEFAULT_MAX_SIZE,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, tuple[MemoryEntry[Any], float]] = OrderedDict()
        self._lock = threading.RLock()
        self._connected = False

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    @property
    def size(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._store)

    async def connect(self) -> None:
        with self._lock:
            self._connected = True

    async def disconnect(self) -> None:
        with self._lock:
            self._connected = False

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise StorageConnectionError("Cache storage is not connected.")

    def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (_, expires_at) in self._store.items()
            if expires_at is not None and expires_at <= now
        ]
        for key in expired:
            self._store.pop(key, None)

    def _evict_if_needed_locked(self) -> None:
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def _expires_at(self) -> float | None:
        if self._ttl_seconds <= 0:
            return None
        return time.monotonic() + self._ttl_seconds

    async def save(self, entry: MemoryEntry[Any]) -> None:
        self._ensure_connected()
        with self._lock:
            self._purge_expired_locked()
            self._store[entry.key] = (entry, self._expires_at())
            self._store.move_to_end(entry.key)
            self._evict_if_needed_locked()

    async def delete(self, key: str) -> None:
        self._ensure_connected()
        with self._lock:
            self._store.pop(key, None)

    async def load(self, key: str) -> MemoryEntry[Any] | None:
        self._ensure_connected()
        with self._lock:
            self._purge_expired_locked()
            item = self._store.get(key)
            if item is None:
                return None
            entry, expires_at = item
            if expires_at is not None and expires_at <= time.monotonic():
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return entry

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        results: list[MemoryEntry[Any]] = []
        for key in await self.keys():
            entry = await self.load(key)
            if entry is None:
                continue
            if entry_payload_matches(entry, query):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    async def keys(self) -> Sequence[str]:
        self._ensure_connected()
        with self._lock:
            self._purge_expired_locked()
            return list(self._store.keys())

    async def clear(self) -> None:
        self._ensure_connected()
        with self._lock:
            self._store.clear()

    async def get_ttl(self, key: str) -> float | None:
        """
        Return remaining TTL for a key, or None when absent/no TTL.
        """
        self._ensure_connected()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            _, expires_at = item
            if expires_at is None:
                return None
            remaining = expires_at - time.monotonic()
            return max(0.0, remaining)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            self._purge_expired_locked()
            return {
                "size": len(self._store),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl_seconds,
                "connected": self._connected,
            }
