"""
CIE-OS Memory Subsystem

Short-Term Memory Engine

This module implements the working memory layer used by the
MemoryManager. It is responsible for temporary storage of
conversation context, runtime state and transient knowledge
before promotion into long-term memory.

The implementation provides:

- Session-scoped memory
- Configurable capacity
- TTL support
- Automatic expiration
- Fast key/value lookup
- Async lifecycle
- Statistics
- Health monitoring
"""

from __future__ import annotations

import asyncio
import time

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Mapping
from typing import MutableMapping
from typing import Optional

from .memory import BaseMemory
from .memory import MemoryEntry
from .memory import MemoryState


# ============================================================
# Constants
# ============================================================

DEFAULT_CAPACITY = 1024
DEFAULT_TTL_SECONDS = 3600
DEFAULT_NAMESPACE = "default"

DEFAULT_CLEANUP_INTERVAL = 60

DEFAULT_EVICTION_BATCH = 32


# ============================================================
# Enums
# ============================================================

class EvictionPolicy(str, Enum):
    """
    Memory eviction strategy.
    """

    FIFO = "fifo"

    LRU = "lru"

    LFU = "lfu"

    NONE = "none"


class EntryState(str, Enum):
    """
    Runtime state of a memory entry.
    """

    ACTIVE = "active"

    EXPIRED = "expired"

    EVICTED = "evicted"

    DELETED = "deleted"


# ============================================================
# Exceptions
# ============================================================

class ShortTermMemoryError(Exception):
    """
    Base exception for short-term memory.
    """


class MemoryCapacityExceeded(
    ShortTermMemoryError,
):
    """
    Raised when capacity cannot be increased.
    """


class MemoryEntryExpired(
    ShortTermMemoryError,
):
    """
    Raised when an expired entry is accessed.
    """


class MemoryNotFound(
    ShortTermMemoryError,
):
    """
    Raised when a key does not exist.
    """


# ============================================================
# Configuration
# ============================================================

@dataclass(slots=True)
class ShortTermMemoryConfig:
    """
    Runtime configuration.
    """

    capacity: int = DEFAULT_CAPACITY

    ttl_seconds: int = DEFAULT_TTL_SECONDS

    cleanup_interval: int = DEFAULT_CLEANUP_INTERVAL

    namespace: str = DEFAULT_NAMESPACE

    eviction_policy: EvictionPolicy = EvictionPolicy.LRU

    enable_statistics: bool = True

    enable_health_checks: bool = True

    auto_cleanup: bool = True

    auto_expire: bool = True

    thread_safe: bool = False


# ============================================================
# Runtime Statistics
# ============================================================

@dataclass(slots=True)
class MemoryStatistics:
    """
    Runtime counters.
    """

    writes: int = 0

    reads: int = 0

    updates: int = 0

    deletions: int = 0

    evictions: int = 0

    expirations: int = 0

    cache_hits: int = 0

    cache_misses: int = 0

    cleanup_runs: int = 0

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )


# ============================================================
# Internal Runtime Entry
# ============================================================

@dataclass(slots=True)
class RuntimeEntry:
    """
    Internal memory representation.
    """

    record: MemoryEntry

    created_at: float

    updated_at: float

    expires_at: float | None = None

    access_count: int = 0

    last_access: float = field(
        default_factory=time.time,
    )

    state: EntryState = EntryState.ACTIVE


# ============================================================
# Short-Term Memory
# ============================================================

class ShortTermMemory(BaseMemory):
    """
    High-performance working memory.

    Responsibilities
    ----------------
    * Session context
    * Temporary facts
    * Recent conversations
    * Runtime cache
    * TTL management
    * Capacity enforcement
    * Automatic cleanup
    """
    def __init__(
        self,
        config: ShortTermMemoryConfig | None = None,
    ) -> None:
        """
        Initialize the short-term memory engine.
        """

        super().__init__()

        self._config = (
            config
            or ShortTermMemoryConfig()
        )

        self._validate_configuration()

        self._entries: OrderedDict[
            str,
            RuntimeEntry,
        ] = OrderedDict()

        self._statistics = (
            MemoryStatistics()
        )

        self._state = (
            MemoryState.CREATED
        )

        self._lock = asyncio.Lock()

        self._cleanup_task: (
            asyncio.Task[Any] | None
        ) = None

        self._last_cleanup = time.time()

        self._created_at = time.time()

        self._metadata: dict[
            str,
            Any,
        ] = {}

        self._tags: dict[
            str,
            set[str],
        ] = {}

        self._namespace = (
            self._config.namespace
        )

        self._running = False


    # ----------------------------------------------------------
    # Internal Initialization
    # ----------------------------------------------------------

    def _validate_configuration(
        self,
    ) -> None:
        """
        Validate runtime configuration.
        """

        if self._config.capacity <= 0:
            raise ValueError(
                "capacity must be greater than zero."
            )

        if self._config.ttl_seconds < 0:
            raise ValueError(
                "ttl_seconds cannot be negative."
            )

        if self._config.cleanup_interval <= 0:
            raise ValueError(
                "cleanup_interval must be positive."
            )

        if (
            not self._config.namespace
            or not self._config.namespace.strip()
        ):
            raise ValueError(
                "namespace cannot be empty."
            )


    def _current_time(
        self,
    ) -> float:
        """
        Return current Unix timestamp.
        """

        return time.time()


    def _make_runtime_entry(
        self,
        entry: MemoryEntry,
        *,
        ttl: int | None = None,
    ) -> RuntimeEntry:
        """
        Build an internal runtime entry.
        """

        now = self._current_time()

        expires_at: float | None = None

        ttl_value = (
            ttl
            if ttl is not None
            else self._config.ttl_seconds
        )

        if ttl_value > 0:
            expires_at = (
                now + ttl_value
            )

        return RuntimeEntry(
            record=entry,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )


    @property
    def config(
        self,
    ) -> ShortTermMemoryConfig:
        """
        Return runtime configuration.
        """

        return self._config


    @property
    def namespace(
        self,
    ) -> str:
        """
        Active namespace.
        """

        return self._namespace


    @property
    def statistics(
        self,
    ) -> MemoryStatistics:
        """
        Runtime statistics.
        """

        return self._statistics


    @property
    def size(
        self,
    ) -> int:
        """
        Number of active entries.
        """

        return len(
            self._entries
        )


    @property
    def capacity(
        self,
    ) -> int:
        """
        Maximum capacity.
        """

        return self._config.capacity


    def is_full(
        self,
    ) -> bool:
        """
        Return True if memory
        reached capacity.
        """

        return (
            self.size
            >= self.capacity
        )


    def available_capacity(
        self,
    ) -> int:
        """
        Remaining capacity.
        """

        return max(
            0,
            self.capacity - self.size,
        )


    def state(
        self,
    ) -> MemoryState:
        """
        Current runtime state.
        """

        return self._state
        # ----------------------------------------------------------
    # Core CRUD Operations
    # ----------------------------------------------------------

    async def put(
        self,
        entry: MemoryEntry,
        *,
        ttl: int | None = None,
    ) -> MemoryEntry:
        """
        Store a memory entry.
        """

        async with self._lock:

            await self._evict_if_needed()

            runtime = self._make_runtime_entry(
                entry,
                ttl=ttl,
            )

            self._entries[
                entry.key
            ] = runtime

            self._entries.move_to_end(
                entry.key,
            )

            self._statistics.writes += 1

            return runtime.record


    async def get(
        self,
        key: str,
    ) -> MemoryEntry | None:
        """
        Retrieve a memory entry.
        """

        runtime = self._entries.get(
            key,
        )

        if runtime is None:

            self._statistics.cache_misses += 1

            return None

        if await self._is_expired(
            runtime,
        ):

            await self.delete(
                key,
            )

            self._statistics.expirations += 1

            return None

        runtime.last_access = (
            self._current_time()
        )

        runtime.access_count += 1

        runtime.updated_at = (
            self._current_time()
        )

        if (
            self._config.eviction_policy
            == EvictionPolicy.LRU
        ):
            self._entries.move_to_end(
                key,
            )

        self._statistics.reads += 1
        self._statistics.cache_hits += 1

        return runtime.record


    async def update(
        self,
        entry: MemoryEntry,
    ) -> MemoryEntry:
        """
        Replace an existing entry.
        """

        async with self._lock:

            runtime = self._entries.get(
                entry.key,
            )

            if runtime is None:
                raise MemoryNotFound(
                    entry.key,
                )

            runtime.record = entry

            runtime.updated_at = (
                self._current_time()
            )

            self._statistics.updates += 1

            return runtime.record


    async def delete(
        self,
        key: str,
    ) -> bool:
        """
        Delete an entry.
        """

        async with self._lock:

            runtime = self._entries.pop(
                key,
                None,
            )

            if runtime is None:
                return False

            runtime.state = (
                EntryState.DELETED
            )

            self._statistics.deletions += 1

            return True


    async def contains(
        self,
        key: str,
    ) -> bool:
        """
        Check key existence.
        """

        return (
            await self.get(key)
            is not None
        )


    async def clear(
        self,
    ) -> int:
        """
        Remove every entry.
        """

        async with self._lock:

            count = len(
                self._entries
            )

            self._entries.clear()

            self._statistics.deletions += count

            return count


    async def keys(
        self,
    ) -> list[str]:
        """
        Return all keys.
        """

        return list(
            self._entries.keys()
        )


    async def values(
        self,
    ) -> list[MemoryEntry]:
        """
        Return all entries.
        """

        result: list[
            MemoryEntry
        ] = []

        for key in await self.keys():

            entry = await self.get(
                key,
            )

            if entry is not None:
                result.append(
                    entry,
                )

        return result


    async def items(
        self,
    ) -> list[
        tuple[str, MemoryEntry]
    ]:
        """
        Return key/value pairs.
        """

        result = []

        for key in await self.keys():

            entry = await self.get(
                key,
            )

            if entry is not None:
                result.append(
                    (
                        key,
                        entry,
                    )
                )

        return result


    async def count(
        self,
    ) -> int:
        """
        Number of active entries.
        """

        return len(
            self._entries
        )
        # ----------------------------------------------------------
    # TTL & Expiration Engine
    # ----------------------------------------------------------

    async def _is_expired(
        self,
        runtime: RuntimeEntry,
    ) -> bool:
        """
        Determine whether an entry
        has expired.
        """

        if runtime.expires_at is None:
            return False

        return (
            self._current_time()
            >= runtime.expires_at
        )


    async def expire(
        self,
        key: str,
    ) -> bool:
        """
        Force expiration of an entry.
        """

        async with self._lock:

            runtime = self._entries.get(
                key,
            )

            if runtime is None:
                return False

            runtime.state = (
                EntryState.EXPIRED
            )

            runtime.expires_at = (
                self._current_time()
            )

        return await self.delete(
            key,
        )


    async def touch(
        self,
        key: str,
        *,
        ttl: int | None = None,
    ) -> bool:
        """
        Refresh entry lifetime.
        """

        runtime = self._entries.get(
            key,
        )

        if runtime is None:
            return False

        ttl_value = (
            ttl
            if ttl is not None
            else self._config.ttl_seconds
        )

        if ttl_value > 0:

            runtime.expires_at = (
                self._current_time()
                + ttl_value
            )

        runtime.updated_at = (
            self._current_time()
        )

        return True


    async def remaining_ttl(
        self,
        key: str,
    ) -> float | None:
        """
        Return remaining lifetime
        in seconds.
        """

        runtime = self._entries.get(
            key,
        )

        if runtime is None:
            return None

        if runtime.expires_at is None:
            return None

        remaining = (
            runtime.expires_at
            - self._current_time()
        )

        return max(
            0.0,
            remaining,
        )


    async def cleanup_expired(
        self,
    ) -> int:
        """
        Remove expired entries.
        """

        removed = 0

        async with self._lock:

            keys = list(
                self._entries.keys()
            )

            for key in keys:

                runtime = self._entries.get(
                    key,
                )

                if runtime is None:
                    continue

                if not await self._is_expired(
                    runtime,
                ):
                    continue

                runtime.state = (
                    EntryState.EXPIRED
                )

                self._entries.pop(
                    key,
                    None,
                )

                removed += 1

        self._statistics.expirations += (
            removed
        )

        self._statistics.cleanup_runs += 1

        self._last_cleanup = (
            self._current_time()
        )

        return removed


    async def has_expired_entries(
        self,
    ) -> bool:
        """
        Check whether expired entries
        exist.
        """

        for runtime in self._entries.values():

            if await self._is_expired(
                runtime,
            ):
                return True

        return False


    async def expiration_statistics(
        self,
    ) -> dict[str, Any]:
        """
        Export expiration statistics.
        """

        expired = 0

        for runtime in self._entries.values():

            if await self._is_expired(
                runtime,
            ):
                expired += 1

        return {
            "expired": expired,
            "active": (
                self.size - expired
            ),
            "cleanup_runs": (
                self._statistics.cleanup_runs
            ),
            "expirations": (
                self._statistics.expirations
            ),
            "last_cleanup": (
                self._last_cleanup
            ),
        }


    async def cleanup_if_needed(
        self,
    ) -> int:
        """
        Execute cleanup only when the
        configured interval elapsed.
        """

        if (
            not self._config.auto_cleanup
        ):
            return 0

        elapsed = (
            self._current_time()
            - self._last_cleanup
        )

        if (
            elapsed
            < self._config.cleanup_interval
        ):
            return 0

        return await self.cleanup_expired()
        # ----------------------------------------------------------
    # Capacity Management
    # ----------------------------------------------------------

    async def _evict_if_needed(
        self,
    ) -> int:
        """
        Evict entries until the configured
        capacity is satisfied.
        """

        removed = 0

        while self.is_full():

            if not await self._evict_one():
                break

            removed += 1

        return removed


    async def _evict_one(
        self,
    ) -> bool:
        """
        Evict a single entry according
        to the configured policy.
        """

        if not self._entries:
            return False

        policy = self._config.eviction_policy

        if policy == EvictionPolicy.FIFO:
            return await self._evict_fifo()

        if policy == EvictionPolicy.LRU:
            return await self._evict_lru()

        if policy == EvictionPolicy.LFU:
            return await self._evict_lfu()

        return False


    async def _evict_fifo(
        self,
    ) -> bool:
        """
        Evict the oldest inserted entry.
        """

        key, runtime = next(
            iter(self._entries.items())
        )

        runtime.state = EntryState.EVICTED

        self._entries.pop(
            key,
            None,
        )

        self._statistics.evictions += 1

        return True


    async def _evict_lru(
        self,
    ) -> bool:
        """
        Evict the least recently used entry.
        """

        key = None
        oldest = float("inf")

        for candidate, runtime in self._entries.items():

            if runtime.last_access < oldest:
                oldest = runtime.last_access
                key = candidate

        if key is None:
            return False

        runtime = self._entries.pop(
            key,
        )

        runtime.state = EntryState.EVICTED

        self._statistics.evictions += 1

        return True


    async def _evict_lfu(
        self,
    ) -> bool:
        """
        Evict the least frequently used entry.
        """

        key = None
        lowest = float("inf")
        oldest = float("inf")

        for candidate, runtime in self._entries.items():

            if (
                runtime.access_count < lowest
                or (
                    runtime.access_count == lowest
                    and runtime.last_access < oldest
                )
            ):
                lowest = runtime.access_count
                oldest = runtime.last_access
                key = candidate

        if key is None:
            return False

        runtime = self._entries.pop(
            key,
        )

        runtime.state = EntryState.EVICTED

        self._statistics.evictions += 1

        return True


    async def set_capacity(
        self,
        capacity: int,
    ) -> None:
        """
        Update maximum capacity.
        """

        if capacity <= 0:
            raise ValueError(
                "capacity must be positive."
            )

        self._config.capacity = capacity

        await self._evict_if_needed()


    async def shrink_to_fit(
        self,
    ) -> int:
        """
        Reduce memory usage until it
        satisfies capacity.
        """

        return await self._evict_if_needed()


    async def eviction_statistics(
        self,
    ) -> dict[str, Any]:
        """
        Export eviction metrics.
        """

        return {
            "policy": (
                self._config.eviction_policy.value
            ),
            "capacity": self.capacity,
            "size": self.size,
            "available": (
                self.available_capacity()
            ),
            "evictions": (
                self._statistics.evictions
            ),
        }
        # ----------------------------------------------------------
    # Search & Filtering
    # ----------------------------------------------------------

    async def find(
        self,
        query: str,
        *,
        case_sensitive: bool = False,
        limit: int | None = None,
    ) -> list[MemoryEntry]:
        """
        Search entries by key or textual content.
        """

        results: list[MemoryEntry] = []

        if not case_sensitive:
            query = query.lower()

        for runtime in self._entries.values():

            if await self._is_expired(runtime):
                continue

            entry = runtime.record

            key = entry.key
            value = str(entry.value)

            if not case_sensitive:
                key = key.lower()
                value = value.lower()

            if query in key or query in value:
                results.append(entry)

                if (
                    limit is not None
                    and len(results) >= limit
                ):
                    break

        return results


    async def filter(
        self,
        predicate: Callable[[MemoryEntry], bool],
    ) -> list[MemoryEntry]:
        """
        Filter entries using a predicate.
        """

        results: list[MemoryEntry] = []

        for runtime in self._entries.values():

            if await self._is_expired(runtime):
                continue

            entry = runtime.record

            if predicate(entry):
                results.append(entry)

        return results


    async def find_by_tag(
        self,
        tag: str,
    ) -> list[MemoryEntry]:
        """
        Return entries containing a tag.
        """

        return await self.filter(
            lambda entry: (
                tag
                in getattr(
                    entry,
                    "tags",
                    [],
                )
            )
        )


    async def find_by_namespace(
        self,
        namespace: str,
    ) -> list[MemoryEntry]:
        """
        Return entries belonging to a namespace.
        """

        return await self.filter(
            lambda entry: (
                getattr(
                    entry,
                    "namespace",
                    self.namespace,
                )
                == namespace
            )
        )


    async def recent(
        self,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """
        Return recently accessed entries.
        """

        entries = sorted(
            self._entries.values(),
            key=lambda item: item.last_access,
            reverse=True,
        )

        results: list[
            MemoryEntry
        ] = []

        for runtime in entries:

            if await self._is_expired(runtime):
                continue

            results.append(
                runtime.record,
            )

            if len(results) >= limit:
                break

        return results


    async def oldest(
        self,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """
        Return oldest active entries.
        """

        entries = sorted(
            self._entries.values(),
            key=lambda item: item.created_at,
        )

        results: list[
            MemoryEntry
        ] = []

        for runtime in entries:

            if await self._is_expired(runtime):
                continue

            results.append(
                runtime.record,
            )

            if len(results) >= limit:
                break

        return results


    async def search_statistics(
        self,
    ) -> dict[str, Any]:
        """
        Export search subsystem statistics.
        """

        return {
            "entries": self.size,
            "capacity": self.capacity,
            "cache_hits": (
                self._statistics.cache_hits
            ),
            "cache_misses": (
                self._statistics.cache_misses
            ),
            "hit_ratio": (
                0.0
                if (
                    self._statistics.cache_hits
                    + self._statistics.cache_misses
                ) == 0
                else (
                    self._statistics.cache_hits
                    / (
                        self._statistics.cache_hits
                        + self._statistics.cache_misses
                    )
                )
            ),
        }
        # ----------------------------------------------------------
    # Batch Operations
    # ----------------------------------------------------------

    async def put_many(
        self,
        entries: Iterable[MemoryEntry],
        *,
        ttl: int | None = None,
    ) -> int:
        """
        Store multiple entries.
        """

        stored = 0

        for entry in entries:
            await self.put(
                entry,
                ttl=ttl,
            )
            stored += 1

        return stored


    async def get_many(
        self,
        keys: Iterable[str],
    ) -> dict[str, MemoryEntry]:
        """
        Retrieve multiple entries.
        """

        result: dict[
            str,
            MemoryEntry,
        ] = {}

        for key in keys:

            entry = await self.get(
                key,
            )

            if entry is not None:
                result[key] = entry

        return result


    async def update_many(
        self,
        entries: Iterable[MemoryEntry],
    ) -> int:
        """
        Update multiple entries.
        """

        updated = 0

        for entry in entries:

            await self.update(
                entry,
            )

            updated += 1

        return updated


    async def delete_many(
        self,
        keys: Iterable[str],
    ) -> int:
        """
        Delete multiple entries.
        """

        deleted = 0

        for key in keys:

            if await self.delete(
                key,
            ):
                deleted += 1

        return deleted


    async def exists_many(
        self,
        keys: Iterable[str],
    ) -> dict[str, bool]:
        """
        Check existence of multiple keys.
        """

        result: dict[
            str,
            bool,
        ] = {}

        for key in keys:

            result[key] = await self.contains(
                key,
            )

        return result


    async def batch_touch(
        self,
        keys: Iterable[str],
        *,
        ttl: int | None = None,
    ) -> int:
        """
        Refresh TTL for multiple entries.
        """

        refreshed = 0

        for key in keys:

            if await self.touch(
                key,
                ttl=ttl,
            ):
                refreshed += 1

        return refreshed


    async def batch_expire(
        self,
        keys: Iterable[str],
    ) -> int:
        """
        Expire multiple entries.
        """

        expired = 0

        for key in keys:

            if await self.expire(
                key,
            ):
                expired += 1

        return expired


    async def batch_filter(
        self,
        predicate: Callable[
            [MemoryEntry],
            bool,
        ],
    ) -> list[MemoryEntry]:
        """
        Filter entries in batch mode.
        """

        return await self.filter(
            predicate,
        )


    async def batch_statistics(
        self,
    ) -> dict[str, Any]:
        """
        Export batch subsystem statistics.
        """

        return {
            "entries": self.size,
            "capacity": self.capacity,
            "available_capacity": (
                self.available_capacity()
            ),
            "writes": (
                self._statistics.writes
            ),
            "reads": (
                self._statistics.reads
            ),
            "updates": (
                self._statistics.updates
            ),
            "deletions": (
                self._statistics.deletions
            ),
        }
        # ----------------------------------------------------------
    # Statistics & Metrics
    # ----------------------------------------------------------

    def statistics_snapshot(
        self,
    ) -> dict[str, Any]:
        """
        Return runtime statistics.
        """

        stats = self._statistics

        return {
            "writes": stats.writes,
            "reads": stats.reads,
            "updates": stats.updates,
            "deletions": stats.deletions,
            "evictions": stats.evictions,
            "expirations": stats.expirations,
            "cache_hits": stats.cache_hits,
            "cache_misses": stats.cache_misses,
            "cleanup_runs": stats.cleanup_runs,
            "created_at": (
                stats.created_at.isoformat()
            ),
        }


    def cache_hit_ratio(
        self,
    ) -> float:
        """
        Return cache hit ratio.
        """

        total = (
            self._statistics.cache_hits
            + self._statistics.cache_misses
        )

        if total == 0:
            return 0.0

        return (
            self._statistics.cache_hits
            / total
        )


    def utilization_ratio(
        self,
    ) -> float:
        """
        Return memory utilization.
        """

        if self.capacity == 0:
            return 0.0

        return (
            self.size
            / self.capacity
        )


    def metrics(
        self,
    ) -> dict[str, Any]:
        """
        Export metrics.
        """

        return {
            "namespace": self.namespace,
            "state": self._state.value,
            "size": self.size,
            "capacity": self.capacity,
            "available_capacity": (
                self.available_capacity()
            ),
            "utilization": (
                self.utilization_ratio()
            ),
            "cache_hit_ratio": (
                self.cache_hit_ratio()
            ),
            "statistics": (
                self.statistics_snapshot()
            ),
        }


    def reset_statistics(
        self,
    ) -> None:
        """
        Reset runtime statistics.
        """

        created_at = (
            self._statistics.created_at
        )

        self._statistics = (
            MemoryStatistics()
        )

        self._statistics.created_at = (
            created_at
        )


    def increment_metric(
        self,
        name: str,
        value: int = 1,
    ) -> None:
        """
        Increment a runtime counter.
        """

        if hasattr(
            self._statistics,
            name,
        ):
            current = getattr(
                self._statistics,
                name,
            )

            setattr(
                self._statistics,
                name,
                current + value,
            )


    def export_metrics(
        self,
    ) -> dict[str, Any]:
        """
        Export complete metrics payload.
        """

        return {
            "memory": self.metrics(),
            "timestamp": (
                datetime.now(UTC).isoformat()
            ),
        }


    async def collect_metrics(
        self,
    ) -> dict[str, Any]:
        """
        Collect runtime metrics.
        """

        return self.export_metrics()


    async def metrics_report(
        self,
    ) -> dict[str, Any]:
        """
        Produce a metrics report.
        """

        return {
            "summary": self.metrics(),
            "expiration": (
                await self.expiration_statistics()
            ),
            "eviction": (
                await self.eviction_statistics()
            ),
            "search": (
                await self.search_statistics()
            ),
            "batch": (
                await self.batch_statistics()
            ),
        }
        # ----------------------------------------------------------
    # Health Monitoring
    # ----------------------------------------------------------

    async def health_check(
        self,
    ) -> dict[str, Any]:
        """
        Execute a runtime health check.
        """

        expiration = (
            await self.expiration_statistics()
        )

        utilization = (
            self.utilization_ratio()
        )

        cache_ratio = (
            self.cache_hit_ratio()
        )

        issues: list[str] = []

        status = "healthy"

        if utilization >= 0.95:
            status = "critical"
            issues.append(
                "memory capacity almost exhausted"
            )

        elif utilization >= 0.80:
            status = "warning"
            issues.append(
                "high memory utilization"
            )

        if expiration["expired"] > 0:
            issues.append(
                "expired entries pending cleanup"
            )

        return {
            "status": status,
            "state": self._state.value,
            "namespace": self.namespace,
            "size": self.size,
            "capacity": self.capacity,
            "utilization": utilization,
            "cache_hit_ratio": cache_ratio,
            "expired_entries": (
                expiration["expired"]
            ),
            "issues": issues,
        }


    async def is_healthy(
        self,
    ) -> bool:
        """
        Return True when the memory
        subsystem is healthy.
        """

        report = await self.health_check()

        return report["status"] == "healthy"


    async def readiness_check(
        self,
    ) -> bool:
        """
        Verify the subsystem is ready
        to serve requests.
        """

        return (
            self._state
            in (
                MemoryState.READY,
                MemoryState.RUNNING,
            )
        )


    async def liveness_check(
        self,
    ) -> bool:
        """
        Verify the subsystem is alive.
        """

        return (
            self._state
            != MemoryState.CLOSED
        )


    async def diagnose(
        self,
    ) -> dict[str, Any]:
        """
        Produce a diagnostic report.
        """

        return {
            "health": (
                await self.health_check()
            ),
            "metrics": (
                self.metrics()
            ),
            "expiration": (
                await self.expiration_statistics()
            ),
            "eviction": (
                await self.eviction_statistics()
            ),
        }


    async def health_summary(
        self,
    ) -> dict[str, Any]:
        """
        Export a compact health summary.
        """

        report = await self.health_check()

        return {
            "healthy": (
                report["status"]
                == "healthy"
            ),
            "status": (
                report["status"]
            ),
            "utilization": (
                report["utilization"]
            ),
            "entries": self.size,
            "capacity": self.capacity,
        }


    async def auto_recover(
        self,
    ) -> bool:
        """
        Attempt automatic recovery.
        """

        report = await self.health_check()

        if report["status"] == "healthy":
            return True

        await self.cleanup_if_needed()

        if self.is_full():
            await self.shrink_to_fit()

        return await self.is_healthy()
        # ----------------------------------------------------------
    # Serialization
    # ----------------------------------------------------------

    SERIALIZATION_VERSION = 1

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """
        Export the complete memory state
        as a dictionary.
        """

        entries: list[dict[str, Any]] = []

        for runtime in self._entries.values():

            record = runtime.record

            entries.append(
                {
                    "key": record.key,
                    "value": record.value,
                    "created_at": runtime.created_at,
                    "updated_at": runtime.updated_at,
                    "expires_at": runtime.expires_at,
                    "last_access": runtime.last_access,
                    "access_count": runtime.access_count,
                    "state": runtime.state.value,
                }
            )

        return {
            "schema_version": (
                self.SERIALIZATION_VERSION
            ),
            "namespace": self.namespace,
            "state": self._state.value,
            "capacity": self.capacity,
            "entries": entries,
            "statistics": (
                self.statistics_snapshot()
            ),
            "metadata": dict(
                self._metadata
            ),
        }


    def to_json(
        self,
    ) -> str:
        """
        Export memory as JSON.
        """

        import json

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            default=str,
        )


    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ShortTermMemory":
        """
        Create a memory instance
        from serialized data.
        """

        config = ShortTermMemoryConfig(
            capacity=int(
                data.get(
                    "capacity",
                    DEFAULT_CAPACITY,
                )
            ),
            namespace=str(
                data.get(
                    "namespace",
                    DEFAULT_NAMESPACE,
                )
            ),
        )

        memory = cls(
            config=config,
        )

        memory._metadata.update(
            dict(
                data.get(
                    "metadata",
                    {},
                )
            )
        )

        return memory


    @classmethod
    def from_json(
        cls,
        payload: str,
    ) -> "ShortTermMemory":
        """
        Restore memory from JSON.
        """

        import json

        return cls.from_dict(
            json.loads(
                payload,
            )
        )


    def export_snapshot(
        self,
    ) -> dict[str, Any]:
        """
        Export a snapshot payload.
        """

        return self.to_dict()


    @classmethod
    def import_snapshot(
        cls,
        snapshot: Mapping[str, Any],
    ) -> "ShortTermMemory":
        """
        Import a snapshot.
        """

        return cls.from_dict(
            snapshot,
        )


    def serialization_metadata(
        self,
    ) -> dict[str, Any]:
        """
        Return serialization metadata.
        """

        return {
            "schema_version": (
                self.SERIALIZATION_VERSION
            ),
            "namespace": self.namespace,
            "entry_count": self.size,
            "capacity": self.capacity,
        }


    def supports_version(
        self,
        version: int,
    ) -> bool:
        """
        Verify schema compatibility.
        """

        return (
            version
            == self.SERIALIZATION_VERSION
        )


    def clone(
        self,
    ) -> "ShortTermMemory":
        """
        Clone the current memory.
        """

        return self.from_dict(
            self.to_dict(),
        )
        # ----------------------------------------------------------
    # Synchronization
    # ----------------------------------------------------------

    async def synchronize(
        self,
    ) -> dict[str, Any]:
        """
        Synchronize the runtime state.
        """

        async with self._lock:

            removed = await self.cleanup_if_needed()

            return {
                "synchronized": True,
                "removed": removed,
                "entries": self.size,
                "timestamp": self._current_time(),
            }


    async def acquire_lock(
        self,
    ) -> None:
        """
        Acquire the internal lock.
        """

        await self._lock.acquire()


    def release_lock(
        self,
    ) -> None:
        """
        Release the internal lock.
        """

        if self._lock.locked():
            self._lock.release()


    async def locked(
        self,
    ) -> bool:
        """
        Return lock state.
        """

        return self._lock.locked()


    async def synchronize_metadata(
        self,
        metadata: Mapping[str, Any],
    ) -> None:
        """
        Merge runtime metadata.
        """

        async with self._lock:

            self._metadata.update(
                dict(metadata)
            )


    async def synchronize_entries(
        self,
        entries: Iterable[MemoryEntry],
    ) -> int:
        """
        Merge multiple entries.
        """

        count = 0

        async with self._lock:

            for entry in entries:

                runtime = (
                    self._make_runtime_entry(
                        entry,
                    )
                )

                self._entries[
                    entry.key
                ] = runtime

                count += 1

        return count


    async def export_state(
        self,
    ) -> dict[str, Any]:
        """
        Export synchronized state.
        """

        async with self._lock:

            return {
                "namespace": self.namespace,
                "state": self._state.value,
                "entries": self.size,
                "statistics": (
                    self.statistics_snapshot()
                ),
                "metadata": dict(
                    self._metadata
                ),
            }


    async def import_state(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        """
        Import synchronized metadata.
        """

        async with self._lock:

            self._metadata.update(
                dict(
                    payload.get(
                        "metadata",
                        {},
                    )
                )
            )


    async def synchronize_with(
        self,
        other: "ShortTermMemory",
    ) -> int:
        """
        Synchronize with another
        ShortTermMemory instance.
        """

        entries = await other.values()

        return await self.synchronize_entries(
            entries,
        )


    async def synchronization_report(
        self,
    ) -> dict[str, Any]:
        """
        Return synchronization status.
        """

        return {
            "locked": self._lock.locked(),
            "entries": self.size,
            "namespace": self.namespace,
            "last_cleanup": (
                self._last_cleanup
            ),
            "state": self._state.value,
        }
        # ----------------------------------------------------------
    # Maintenance
    # ----------------------------------------------------------

    async def perform_maintenance(
        self,
    ) -> dict[str, Any]:
        """
        Execute all maintenance routines.
        """

        expired = await self.cleanup_expired()

        evicted = await self.shrink_to_fit()

        return {
            "expired_removed": expired,
            "evicted": evicted,
            "entries": self.size,
            "timestamp": self._current_time(),
        }


    async def optimize(
        self,
    ) -> dict[str, Any]:
        """
        Optimize the runtime state.
        """

        removed = await self.cleanup_if_needed()

        if self.is_full():
            await self.shrink_to_fit()

        return {
            "optimized": True,
            "removed": removed,
            "entries": self.size,
        }


    async def purge(
        self,
    ) -> int:
        """
        Remove expired and invalid entries.
        """

        return await self.cleanup_expired()


    async def compact(
        self,
    ) -> int:
        """
        Compact internal storage.
        """

        async with self._lock:

            self._entries = OrderedDict(
                self._entries.items()
            )

        return self.size


    async def vacuum(
        self,
    ) -> dict[str, Any]:
        """
        Execute a full maintenance cycle.
        """

        expired = await self.cleanup_expired()

        await self.compact()

        return {
            "expired_removed": expired,
            "entries": self.size,
        }


    async def maintenance_report(
        self,
    ) -> dict[str, Any]:
        """
        Export maintenance status.
        """

        return {
            "entries": self.size,
            "capacity": self.capacity,
            "cleanup_runs": (
                self._statistics.cleanup_runs
            ),
            "last_cleanup": (
                self._last_cleanup
            ),
            "utilization": (
                self.utilization_ratio()
            ),
        }


    async def reset(
        self,
    ) -> None:
        """
        Reset the runtime state.
        """

        async with self._lock:

            self._entries.clear()

            self._metadata.clear()

            self._tags.clear()

            self.reset_statistics()

            self._last_cleanup = (
                self._current_time()
            )


    async def trim(
        self,
        target_size: int,
    ) -> int:
        """
        Reduce memory until the
        requested size is reached.
        """

        if target_size < 0:
            raise ValueError(
                "target_size must be non-negative."
            )

        removed = 0

        while self.size > target_size:

            if not await self._evict_one():
                break

            removed += 1

        return removed


    async def remove_expired_and_optimize(
        self,
    ) -> dict[str, Any]:
        """
        Combined cleanup operation.
        """

        expired = await self.cleanup_expired()

        optimized = await self.optimize()

        return {
            "expired": expired,
            "optimization": optimized,
        }


    async def maintenance_cycle(
        self,
    ) -> dict[str, Any]:
        """
        Execute a complete maintenance cycle.
        """

        report = await self.perform_maintenance()

        report["health"] = (
            await self.health_summary()
        )

        return report
        # ----------------------------------------------------------
    # Async Lifecycle
    # ----------------------------------------------------------

    async def start(
        self,
    ) -> None:
        """
        Start the short-term memory engine.
        """

        if self._running:
            return

        self._running = True

        self._state = MemoryState.RUNNING

        if (
            self._config.auto_cleanup
            and self._cleanup_task is None
        ):
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop(),
                name="short_term_memory_cleanup",
            )


    async def stop(
        self,
    ) -> None:
        """
        Stop the memory engine.
        """

        self._running = False

        if self._cleanup_task is not None:

            self._cleanup_task.cancel()

            try:
                await self._cleanup_task

            except asyncio.CancelledError:
                pass

            finally:
                self._cleanup_task = None

        self._state = MemoryState.STOPPED


    async def close(
        self,
    ) -> None:
        """
        Gracefully close the memory engine.
        """

        await self.stop()

        await self.perform_maintenance()

        self._state = MemoryState.CLOSED


    async def restart(
        self,
    ) -> None:
        """
        Restart the memory engine.
        """

        await self.stop()

        await self.start()


    async def _cleanup_loop(
        self,
    ) -> None:
        """
        Background cleanup worker.
        """

        try:

            while self._running:

                await asyncio.sleep(
                    self._config.cleanup_interval,
                )

                await self.cleanup_if_needed()

        except asyncio.CancelledError:
            raise

        finally:

            self._last_cleanup = (
                self._current_time()
            )


    async def wait_until_ready(
        self,
    ) -> None:
        """
        Wait until the memory engine
        becomes ready.
        """

        while (
            self._state
            != MemoryState.RUNNING
        ):
            await asyncio.sleep(
                0.05,
            )


    async def lifecycle_status(
        self,
    ) -> dict[str, Any]:
        """
        Return lifecycle information.
        """

        return {
            "running": self._running,
            "state": self._state.value,
            "cleanup_task": (
                self._cleanup_task
                is not None
            ),
            "namespace": self.namespace,
            "entries": self.size,
        }


    async def __aenter__(
        self,
    ) -> "ShortTermMemory":
        """
        Async context manager entry.
        """

        await self.start()

        return self


    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        """
        Async context manager exit.
        """

        await self.close()
            # ----------------------------------------------------------
    # Events & Hooks
    # ----------------------------------------------------------

    def register_hook(
        self,
        event: str,
        callback: Callable[..., Any],
    ) -> None:
        """
        Register an event callback.
        """

        self._hooks.setdefault(
            event,
            [],
        ).append(
            callback,
        )


    def unregister_hook(
        self,
        event: str,
        callback: Callable[..., Any],
    ) -> bool:
        """
        Remove an event callback.
        """

        callbacks = self._hooks.get(
            event,
        )

        if callbacks is None:
            return False

        try:
            callbacks.remove(
                callback,
            )
        except ValueError:
            return False

        if not callbacks:
            self._hooks.pop(
                event,
                None,
            )

        return True


    def registered_events(
        self,
    ) -> list[str]:
        """
        Return registered event names.
        """

        return sorted(
            self._hooks.keys(),
        )


    async def emit(
        self,
        event: str,
        **payload: Any,
    ) -> None:
        """
        Emit an event.
        """

        callbacks = list(
            self._hooks.get(
                event,
                [],
            )
        )

        for callback in callbacks:

            if asyncio.iscoroutinefunction(
                callback,
            ):
                await callback(
                    **payload,
                )
            else:
                callback(
                    **payload,
                )


    async def emit_before_put(
        self,
        entry: MemoryEntry,
    ) -> None:
        """
        Emit before-put hook.
        """

        await self.emit(
            "before_put",
            memory=self,
            entry=entry,
        )


    async def emit_after_put(
        self,
        entry: MemoryEntry,
    ) -> None:
        """
        Emit after-put hook.
        """

        await self.emit(
            "after_put",
            memory=self,
            entry=entry,
        )


    async def emit_before_delete(
        self,
        key: str,
    ) -> None:
        """
        Emit before-delete hook.
        """

        await self.emit(
            "before_delete",
            memory=self,
            key=key,
        )


    async def emit_after_delete(
        self,
        key: str,
    ) -> None:
        """
        Emit after-delete hook.
        """

        await self.emit(
            "after_delete",
            memory=self,
            key=key,
        )


    async def emit_lifecycle_event(
        self,
        event: str,
    ) -> None:
        """
        Emit lifecycle event.
        """

        await self.emit(
            event,
            memory=self,
            state=self._state.value,
        )


    async def clear_hooks(
        self,
    ) -> int:
        """
        Remove every registered hook.
        """

        count = sum(
            len(callbacks)
            for callbacks in self._hooks.values()
        )

        self._hooks.clear()

        return count


    def hook_statistics(
        self,
    ) -> dict[str, Any]:
        """
        Return hook registry statistics.
        """

        return {
            "events": len(
                self._hooks,
            ),
            "callbacks": sum(
                len(callbacks)
                for callbacks
                in self._hooks.values()
            ),
            "registered": (
                self.registered_events()
            ),
        }
        # ----------------------------------------------------------
    # Final Utilities & Validation
    # ----------------------------------------------------------

    def validate_configuration(
        self,
    ) -> bool:
        """
        Validate runtime configuration.
        """

        self._validate_configuration()

        return True


    async def validate_runtime(
        self,
    ) -> dict[str, Any]:
        """
        Validate runtime state.
        """

        issues: list[str] = []

        if self.size > self.capacity:
            issues.append(
                "memory exceeds configured capacity"
            )

        if self._cleanup_task is not None:

            if self._cleanup_task.done():

                exception = (
                    self._cleanup_task.exception()
                )

                if exception is not None:
                    issues.append(
                        "cleanup task terminated with exception"
                    )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }


    async def self_test(
        self,
    ) -> dict[str, Any]:
        """
        Execute internal diagnostics.
        """

        runtime = await self.validate_runtime()

        health = await self.health_check()

        return {
            "runtime": runtime,
            "health": health,
            "passed": (
                runtime["valid"]
                and health["status"] != "critical"
            ),
        }


    def debug_information(
        self,
    ) -> dict[str, Any]:
        """
        Export debug information.
        """

        return {
            "namespace": self.namespace,
            "state": self._state.value,
            "running": self._running,
            "entries": self.size,
            "capacity": self.capacity,
            "cleanup_task": (
                self._cleanup_task
                is not None
            ),
            "statistics": (
                self.statistics_snapshot()
            ),
        }


    async def validate(
        self,
    ) -> bool:
        """
        Execute complete validation.
        """

        report = await self.self_test()

        return report["passed"]


    async def diagnostics(
        self,
    ) -> dict[str, Any]:
        """
        Export complete diagnostics.
        """

        return {
            "debug": (
                self.debug_information()
            ),
            "metrics": (
                self.metrics()
            ),
            "health": (
                await self.health_check()
            ),
            "maintenance": (
                await self.maintenance_report()
            ),
            "validation": (
                await self.validate_runtime()
            ),
        }


    def __len__(
        self,
    ) -> int:
        """
        Number of active entries.
        """

        return self.size


    def __contains__(
        self,
        key: str,
    ) -> bool:
        """
        Membership test.
        """

        return key in self._entries


    def __repr__(
        self,
    ) -> str:
        """
        Developer representation.
        """

        return (
            f"{self.__class__.__name__}("
            f"namespace={self.namespace!r}, "
            f"size={self.size}, "
            f"capacity={self.capacity}, "
            f"state={self._state.value!r})"
        )


    __str__ = __repr__