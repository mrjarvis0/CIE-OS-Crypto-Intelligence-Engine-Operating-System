"""
Tools :: Utils :: Caching
=========================

Thread-safe in-memory caches shared across the Tools subsystem.

Two policies are provided:

* :class:`TTLCache` -- entries expire after a wall-clock timeout.
* :class:`LRUCache` -- bounded cache evicting least-recently-used entries.

Both support ``get``/``set``/``delete``/``clear`` and expose ``get_or_set``
for lock-protected computation, which makes them suitable for hot paths like
routing decisions, capability lookups and metadata reads.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Generic, Hashable, Optional, TypeVar

__all__ = ["TTLCache", "LRUCache", "CacheStats", "timed_lru_cache"]

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class CacheStats:
    """Counters describing cache behavior for observability."""

    __slots__ = ("hits", "misses", "evictions", "expirations")

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    def hit_ratio(self) -> float:
        """Ratio of hits to total lookups (0.0 when no lookups occurred)."""
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "hit_ratio": self.hit_ratio(),
        }


class TTLCache(Generic[K, V]):
    """
    Thread-safe cache with per-entry time-to-live.

    ``default_ttl`` (seconds) applies when no TTL is passed to :meth:`set`.
    A ``maxsize`` bound evicts the oldest entry once reached; ``None`` means
    unbounded (size is still tracked for stats).
    """

    def __init__(self, *, default_ttl: float = 60.0, maxsize: Optional[int] = None) -> None:
        if default_ttl <= 0:
            raise ValueError("default_ttl must be > 0")
        if maxsize is not None and maxsize <= 0:
            raise ValueError("maxsize must be > 0 or None")
        self._default_ttl = default_ttl
        self._maxsize = maxsize
        self._store: "OrderedDict[K, tuple[float, float, V]]" = OrderedDict()
        self._lock = threading.RLock()
        self.stats = CacheStats()

    @property
    def default_ttl(self) -> float:
        return self._default_ttl

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Return the value for ``key`` unless missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            now = time.monotonic()
            if entry is None:
                self.stats.misses += 1
                return default
            created, ttl, value = entry
            if ttl > 0 and now - created > ttl:
                del self._store[key]
                self.stats.expirations += 1
                self.stats.misses += 1
                return default
            self._store.move_to_end(key)
            self.stats.hits += 1
            return value

    def set(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        """Store ``value`` under ``key``; ``ttl`` overrides the default."""
        with self._lock:
            self._store[key] = (time.monotonic(), self._default_ttl if ttl is None else ttl, value)
            self._store.move_to_end(key)
            if self._maxsize is not None:
                while len(self._store) > self._maxsize:
                    self._store.popitem(last=False)
                    self.stats.evictions += 1

    def get_or_set(
        self, key: K, factory: Callable[[], V], ttl: Optional[float] = None
    ) -> V:
        """Return cached value or compute (under the lock) and store it."""
        with self._lock:
            cached = self.get(key)
            if cached is not None:
                return cached
            value = factory()
            self.set(key, value, ttl)
            return value

    def delete(self, key: K) -> bool:
        """Remove ``key``; returns True when it existed."""
        with self._lock:
            try:
                del self._store[key]
                return True
            except KeyError:
                return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def expire(self) -> int:
        """Drop expired entries and return how many were removed."""
        with self._lock:
            now = time.monotonic()
            expired = [
                k for k, (created, ttl, _) in self._store.items()
                if ttl > 0 and now - created > ttl
            ]
            for k in expired:
                del self._store[k]
            self.stats.expirations += len(expired)
            return len(expired)

    def keys(self) -> list:
        with self._lock:
            return list(self._store.keys())


class LRUCache(Generic[K, V]):
    """
    Thread-safe least-recently-used cache with a hard size bound.

    ``maxsize`` must be positive.  Entries are re-ordered on access, and the
    least-recently-used entry is evicted when the bound is exceeded.
    """

    def __init__(self, maxsize: int) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be > 0")
        self._maxsize = maxsize
        self._store: "OrderedDict[K, V]" = OrderedDict()
        self._lock = threading.RLock()
        self.stats = CacheStats()

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        with self._lock:
            value = self._store.get(key)
            if value is None and key not in self._store:
                self.stats.misses += 1
                return default
            self._store.move_to_end(key)
            self.stats.hits += 1
            return value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)
                self.stats.evictions += 1

    def get_or_set(self, key: K, factory: Callable[[], V]) -> V:
        with self._lock:
            cached = self.get(key)
            if cached is not None or key in self._store:
                return cached
            value = factory()
            self.set(key, value)
            return value

    def delete(self, key: K) -> bool:
        with self._lock:
            try:
                del self._store[key]
                return True
            except KeyError:
                return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def keys(self) -> list:
        with self._lock:
            return list(self._store.keys())


def timed_lru_cache(
    maxsize: int = 128, ttl: float = 60.0
) -> Callable[[Callable[..., V]], Callable[..., V]]:
    """
    Decorator combining LRU eviction with per-entry TTL.

    Thin wrapper over :class:`TTLCache` suitable for memoizing pure functions
    (metadata lookups, capability checks).  Keyword arguments are supported:
    the key is the repr of ``(args, kwargs)``.
    """

    def decorate(func: Callable[..., V]) -> Callable[..., V]:
        cache: "TTLCache[str, V]" = TTLCache(default_ttl=ttl, maxsize=maxsize)

        def wrapper(*args: Any, **kwargs: Any) -> V:
            key = repr((args, tuple(sorted(kwargs.items()))))
            return cache.get_or_set(key, lambda: func(*args, **kwargs))

        return wrapper

    return decorate