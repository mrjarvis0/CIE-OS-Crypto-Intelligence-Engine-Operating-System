"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.cache

Purpose:
    Thread-safe in-memory cache utilities for runtime data, metadata, and
    expensive read-only computations.

Design goals:
    - Bounded memory usage
    - TTL support
    - LRU eviction
    - Thread-safe access
    - No side effects
    - No business logic
    - Safe to import anywhere

Notes:
    Python's standard library recommends bounded LRU caches for reusable values,
    and cache implementations should not be used for functions with side effects.
    This module follows those principles by keeping the cache bounded and
    deterministic. The cache is for reusable, read-only values only.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from typing import Any, Callable, Final, Generic, Iterable, Mapping, MutableMapping, TypeVar

K = TypeVar("K")
V = TypeVar("V")

DEFAULT_MAXSIZE: Final[int] = 1024
DEFAULT_TTL_SECONDS: Final[float] = 300.0


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """Immutable cache configuration."""

    maxsize: int = DEFAULT_MAXSIZE
    ttl_seconds: float = DEFAULT_TTL_SECONDS

    def __post_init__(self) -> None:
        if self.maxsize <= 0:
            raise ValueError("maxsize must be greater than zero")
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Lightweight cache statistics."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0


@dataclass(slots=True)
class _CacheEntry(Generic[V]):
    value: V
    expires_at: float


class Cache(Generic[K, V]):
    """
    Thread-safe bounded TTL + LRU cache.

    This cache is intended for:
    - repeated read-only lookups
    - metadata
    - API responses
    - derived values that can be recomputed

    It is NOT intended for:
    - secrets
    - mutable state-of-record
    - business logic
    - side-effectful operations
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        self._config = config or CacheConfig()
        self._lock = RLock()
        self._data: OrderedDict[K, _CacheEntry[V]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0
        self._expirations = 0

    @property
    def config(self) -> CacheConfig:
        return self._config

    @property
    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                sets=self._sets,
                evictions=self._evictions,
                expirations=self._expirations,
            )

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            entry = self._data[key]  # type: ignore[index]
            if entry.expires_at <= monotonic():
                return False
            return True

    def get(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default

            now = monotonic()
            if entry.expires_at <= now:
                self._misses += 1
                self._expirations += 1
                del self._data[key]
                return default

            self._data.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: K, value: V, *, ttl_seconds: float | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._config.ttl_seconds
        if ttl <= 0:
            raise ValueError("ttl_seconds must be greater than zero")

        with self._lock:
            expires_at = monotonic() + ttl
            self._data[key] = _CacheEntry(value=value, expires_at=expires_at)
            self._data.move_to_end(key)
            self._sets += 1

            self._purge_expired_locked()
            self._evict_lru_locked()

    def delete(self, key: K) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def keys(self) -> list[K]:
        with self._lock:
            self._purge_expired_locked()
            return list(self._data.keys())

    def values(self) -> list[V]:
        with self._lock:
            self._purge_expired_locked()
            return [entry.value for entry in self._data.values()]

    def items(self) -> list[tuple[K, V]]:
        with self._lock:
            self._purge_expired_locked()
            return [(key, entry.value) for key, entry in self._data.items()]

    def get_or_set(
        self,
        key: K,
        factory: Callable[[], V],
        *,
        ttl_seconds: float | None = None,
    ) -> V:
        existing = self.get(key, default=None)
        if existing is not None:
            return existing

        value = factory()
        self.set(key, value, ttl_seconds=ttl_seconds)
        return value

    def get_many(self, keys: Iterable[K]) -> dict[K, V]:
        result: dict[K, V] = {}
        for key in keys:
            value = self.get(key, default=None)
            if value is not None:
                result[key] = value
        return result

    def update_from_mapping(
        self,
        data: Mapping[K, V],
        *,
        ttl_seconds: float | None = None,
    ) -> None:
        for key, value in data.items():
            self.set(key, value, ttl_seconds=ttl_seconds)

    def _purge_expired_locked(self) -> None:
        now = monotonic()
        expired_keys = [
            key for key, entry in self._data.items()
            if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._data[key]
            self._expirations += 1

    def _evict_lru_locked(self) -> None:
        while len(self._data) > self._config.maxsize:
            self._data.popitem(last=False)
            self._evictions += 1


# Global runtime cache instances for common use-cases.
default_cache: Final[Cache[str, Any]] = Cache()
metadata_cache: Final[Cache[str, Any]] = Cache(
    CacheConfig(maxsize=2048, ttl_seconds=600.0)
)
token_cache: Final[Cache[str, Any]] = Cache(
    CacheConfig(maxsize=4096, ttl_seconds=900.0)
)


def build_cache(maxsize: int = DEFAULT_MAXSIZE, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> Cache[Any, Any]:
    """Build a new cache instance with the requested limits."""
    return Cache(CacheConfig(maxsize=maxsize, ttl_seconds=ttl_seconds))


def clear_all_caches() -> None:
    """Clear the module-level cache instances."""
    default_cache.clear()
    metadata_cache.clear()
    token_cache.clear()


__all__ = [
    "CacheConfig",
    "CacheStats",
    "Cache",
    "DEFAULT_MAXSIZE",
    "DEFAULT_TTL_SECONDS",
    "default_cache",
    "metadata_cache",
    "token_cache",
    "build_cache",
    "clear_all_caches",
]
