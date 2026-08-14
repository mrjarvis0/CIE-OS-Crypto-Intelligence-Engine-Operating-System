from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Generic, Iterable, Mapping, Protocol, TypeVar
from uuid import UUID, uuid4


MemoryValue = TypeVar("MemoryValue")


class MemoryType(str, Enum):
    """
    Supported logical memory categories.
    """

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    VECTOR = "vector"
    CONVERSATION = "conversation"
    SESSION = "session"
    CACHE = "cache"


class MemoryState(str, Enum):
    """
    Current lifecycle state.
    """

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    ACTIVE = "active"
    RUNNING = "running"
    STOPPED = "stopped"
    DEGRADED = "degraded"
    CLOSED = "closed"


class MemoryPriority(int, Enum):
    """
    Relative importance.
    """

    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 100


class MemoryOperation(str, Enum):
    """
    Supported operations.
    """

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    CLEAR = "clear"


class SearchMode(str, Enum):
    """
    Retrieval strategy.
    """

    EXACT = "exact"
    PREFIX = "prefix"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass(slots=True)
class MemoryMetadata:
    """
    Additional metadata attached to every memory entry.
    """

    namespace: str = "default"
    source: str = "runtime"
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    priority: MemoryPriority = MemoryPriority.NORMAL
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


@dataclass(slots=True)
class MemoryEntry(Generic[MemoryValue]):
    """
    Generic memory record.
    """

    key: str
    value: MemoryValue
    metadata: MemoryMetadata = field(default_factory=MemoryMetadata)
    identifier: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class MemorySearchResult(Generic[MemoryValue]):
    """
    Single retrieval result.
    """

    entry: MemoryEntry[MemoryValue]
    score: float
    distance: float | None = None


@dataclass(slots=True)
class MemoryStatistics:
    """
    Runtime statistics.
    """

    entries: int = 0
    reads: int = 0
    writes: int = 0
    updates: int = 0
    deletes: int = 0
    searches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MemoryBackend(Protocol):
    """
    Storage backend contract.
    """

    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...


class EmbeddingProvider(Protocol):
    """
    Embedding provider contract.
    """

    async def embed(
        self,
        text: str,
    ) -> list[float]:
        ...


class MemorySerializer(Protocol):
    """
    Serialization contract.
    """

    def dumps(
        self,
        value: Any,
    ) -> bytes:
        ...

    def loads(
        self,
        payload: bytes,
    ) -> Any:
        ...


class MemoryFilter(Protocol):
    """
    Search filter contract.
    """

    def match(
        self,
        entry: MemoryEntry[Any],
    ) -> bool:
        ...


class MemoryHook(Protocol):
    """
    Lifecycle hook.
    """

    async def __call__(
        self,
        operation: MemoryOperation,
        entry: MemoryEntry[Any] | None,
    ) -> None:
        ...


class BaseMemory(ABC, Generic[MemoryValue]):
    """
    Abstract base class for every memory implementation.

    Concrete implementations include:

    - ShortTermMemory
    - LongTermMemory
    - VectorMemory
    - ConversationMemory
    """

    def __init__(
        self,
        *,
        namespace: str = "default",
        backend: MemoryBackend | None = None,
        serializer: MemorySerializer | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:

        self._id: UUID = uuid4()

        self._namespace = namespace

        self._backend = backend

        self._serializer = serializer

        self._embedding_provider = embedding_provider

        self._state = MemoryState.CREATED

        self._statistics = MemoryStatistics()

        self._entries: dict[
            str,
            MemoryEntry[MemoryValue],
        ] = {}

        self._hooks: list[
            MemoryHook,
        ] = []

        self._lock = asyncio.Lock()

        self._closed = False

        self._initialized = False

        self._created_at = datetime.now(UTC)

        self._last_accessed = self._created_at

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def identifier(self) -> UUID:
        return self._id

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def state(self) -> MemoryState:
        return self._state

    @property
    def statistics(self) -> MemoryStatistics:
        return self._statistics

    @property
    def backend(self) -> MemoryBackend | None:
        return self._backend

    @property
    def serializer(self) -> MemorySerializer | None:
        return self._serializer

    @property
    def embedding_provider(
        self,
    ) -> EmbeddingProvider | None:
        return self._embedding_provider

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Initialize memory backend.
        """

        async with self._lock:

            if self._initialized:
                return

            self._state = MemoryState.INITIALIZING

            if self._backend is not None:
                await self._backend.connect()

            self._state = MemoryState.READY

            self._initialized = True

    async def close(self) -> None:
        """
        Gracefully close memory.
        """

        async with self._lock:

            if self._closed:
                return

            if self._backend is not None:
                await self._backend.disconnect()

            self._state = MemoryState.CLOSED

            self._closed = True

    # ------------------------------------------------------------------
    # Hook Management
    # ------------------------------------------------------------------

    def add_hook(
        self,
        hook: MemoryHook,
    ) -> None:

        self._hooks.append(hook)

    async def _run_hooks(
        self,
        operation: MemoryOperation,
        entry: MemoryEntry[Any] | None,
    ) -> None:

        for hook in self._hooks:
            await hook(
                operation,
                entry,
            )
                # ------------------------------------------------------------------
    # Retrieval Helpers
    # ------------------------------------------------------------------

    def _is_expired(
        self,
        entry: MemoryEntry[Any],
    ) -> bool:
        """
        Return True if the entry has expired.
        """

        expires_at = entry.metadata.expires_at

        if expires_at is None:
            return False

        return expires_at <= datetime.now(UTC)


    def _touch(
        self,
    ) -> None:
        """
        Update last access timestamp.
        """

        self._last_accessed = datetime.now(UTC)


    def _validate_key(
        self,
        key: str,
    ) -> None:
        """
        Validate memory key.
        """

        if not key:
            raise ValueError("Memory key cannot be empty.")

        if not key.strip():
            raise ValueError("Memory key cannot be blank.")


    def _validate_metadata(
        self,
        metadata: MemoryMetadata,
    ) -> None:
        """
        Validate metadata.
        """

        if not 0.0 <= metadata.confidence <= 1.0:
            raise ValueError(
                "Confidence must be between 0 and 1."
            )


    async def filter_entries(
        self,
        predicate: MemoryFilter,
    ) -> list[MemoryEntry[MemoryValue]]:
        """
        Return entries matching a filter.
        """

        results: list[
            MemoryEntry[MemoryValue]
        ] = []

        for entry in self._entries.values():

            if self._is_expired(entry):
                continue

            if predicate.match(entry):
                results.append(entry)

        return results


    async def active_entries(
        self,
    ) -> list[MemoryEntry[MemoryValue]]:
        """
        Return all non-expired entries.
        """

        entries: list[
            MemoryEntry[MemoryValue]
        ] = []

        for entry in self._entries.values():

            if self._is_expired(entry):
                continue

            entries.append(entry)

        return entries


    async def expired_entries(
        self,
    ) -> list[MemoryEntry[MemoryValue]]:
        """
        Return expired entries.
        """

        return [
            entry
            for entry in self._entries.values()
            if self._is_expired(entry)
        ]


    async def purge_expired(
        self,
    ) -> int:
        """
        Remove expired entries.
        """

        removed = 0

        for key, entry in list(self._entries.items()):

            if not self._is_expired(entry):
                continue

            del self._entries[key]

            removed += 1

        self._statistics.deletes += removed

        return removed


    async def metadata_search(
        self,
        *,
        namespace: str | None = None,
        tags: Iterable[str] | None = None,
        minimum_confidence: float = 0.0,
    ) -> list[MemoryEntry[MemoryValue]]:
        """
        Search using metadata only.
        """

        required_tags = (
            set(tags)
            if tags is not None
            else None
        )

        results: list[
            MemoryEntry[MemoryValue]
        ] = []

        for entry in await self.active_entries():

            meta = entry.metadata

            if namespace is not None:

                if meta.namespace != namespace:
                    continue

            if meta.confidence < minimum_confidence:
                continue

            if required_tags is not None:

                if not required_tags.issubset(
                    set(meta.tags)
                ):
                    continue

            results.append(entry)

        return results


    async def top_entries(
        self,
        *,
        limit: int = 10,
    ) -> list[MemoryEntry[MemoryValue]]:
        """
        Return highest priority entries.
        """

        entries = await self.active_entries()

        entries.sort(
            key=lambda item: (
                item.metadata.priority.value,
                item.metadata.updated_at,
            ),
            reverse=True,
        )

        return entries[:limit]
        # ------------------------------------------------------------------
    # Health & Diagnostics
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """
        Return a lightweight health snapshot.
        """

        self._touch()

        expired = sum(
            1
            for entry in self._entries.values()
            if self._is_expired(entry)
        )

        return {
            "id": str(self._id),
            "namespace": self._namespace,
            "state": self._state.value,
            "initialized": self._initialized,
            "closed": self._closed,
            "entries": self.size,
            "expired_entries": expired,
            "backend": (
                type(self._backend).__name__
                if self._backend is not None
                else None
            ),
            "created_at": self._created_at,
            "last_accessed": self._last_accessed,
        }


    def metrics(self) -> dict[str, Any]:
        """
        Export runtime metrics.
        """

        stats = self._statistics

        return {
            "entries": stats.entries,
            "reads": stats.reads,
            "writes": stats.writes,
            "updates": stats.updates,
            "deletes": stats.deletes,
            "searches": stats.searches,
            "cache_hits": stats.cache_hits,
            "cache_misses": stats.cache_misses,
            "uptime_seconds": (
                datetime.now(UTC)
                - stats.started_at
            ).total_seconds(),
        }


    def snapshot(self) -> dict[str, Any]:
        """
        Create an immutable runtime snapshot.
        """

        return {
            "health": self.health(),
            "metrics": self.metrics(),
            "keys": list(self._entries.keys()),
            "timestamp": datetime.now(UTC),
        }


    # ------------------------------------------------------------------
    # Statistics Helpers
    # ------------------------------------------------------------------

    def _increment_reads(self) -> None:
        self._statistics.reads += 1


    def _increment_writes(self) -> None:
        self._statistics.writes += 1
        self._statistics.entries = self.size


    def _increment_updates(self) -> None:
        self._statistics.updates += 1


    def _increment_deletes(self) -> None:
        self._statistics.deletes += 1
        self._statistics.entries = self.size


    def _increment_searches(self) -> None:
        self._statistics.searches += 1


    def _cache_hit(self) -> None:
        self._statistics.cache_hits += 1


    def _cache_miss(self) -> None:
        self._statistics.cache_misses += 1


    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def compact(self) -> int:
        """
        Perform lightweight maintenance.

        Default implementation removes expired entries.
        """

        return await self.purge_expired()


    async def reset_metrics(self) -> None:
        """
        Reset runtime counters while preserving start time.
        """

        started_at = self._statistics.started_at

        self._statistics = MemoryStatistics(
            started_at=started_at,
            entries=self.size,
        )


    async def ping(self) -> bool:
        """
        Verify that the memory instance is operational.
        """

        return (
            self._initialized
            and not self._closed
            and self._state
            in {
                MemoryState.READY,
                MemoryState.ACTIVE,
            }
        )
            # ------------------------------------------------------------------
    # Event & Audit Helpers
    # ------------------------------------------------------------------

    async def emit(
        self,
        operation: MemoryOperation,
        entry: MemoryEntry[Any] | None = None,
    ) -> None:
        """
        Emit a lifecycle event.

        Default implementation forwards the event
        to every registered hook.
        """

        self._touch()

        await self._run_hooks(
            operation,
            entry,
        )


    async def before_create(
        self,
        entry: MemoryEntry[Any],
    ) -> None:

        await self.emit(
            MemoryOperation.CREATE,
            entry,
        )


    async def after_create(
        self,
        entry: MemoryEntry[Any],
    ) -> None:

        self._increment_writes()

        await self.emit(
            MemoryOperation.CREATE,
            entry,
        )


    async def after_read(
        self,
        entry: MemoryEntry[Any] | None,
    ) -> None:

        self._increment_reads()

        await self.emit(
            MemoryOperation.READ,
            entry,
        )


    async def after_update(
        self,
        entry: MemoryEntry[Any],
    ) -> None:

        self._increment_updates()

        await self.emit(
            MemoryOperation.UPDATE,
            entry,
        )


    async def after_delete(
        self,
        entry: MemoryEntry[Any] | None,
    ) -> None:

        self._increment_deletes()

        await self.emit(
            MemoryOperation.DELETE,
            entry,
        )


    async def after_search(
        self,
    ) -> None:

        self._increment_searches()

        await self.emit(
            MemoryOperation.SEARCH,
            None,
        )


    # ------------------------------------------------------------------
    # Hook Management
    # ------------------------------------------------------------------

    def remove_hook(
        self,
        hook: MemoryHook,
    ) -> bool:
        """
        Remove a previously registered hook.
        """

        try:
            self._hooks.remove(hook)
            return True

        except ValueError:
            return False


    def clear_hooks(self) -> None:
        """
        Remove every registered hook.
        """

        self._hooks.clear()


    @property
    def hook_count(self) -> int:
        """
        Number of active hooks.
        """

        return len(self._hooks)


    # ------------------------------------------------------------------
    # Audit Helpers
    # ------------------------------------------------------------------

    def audit_record(self) -> dict[str, Any]:
        """
        Export a lightweight audit snapshot.
        """

        return {
            "memory_id": str(self._id),
            "namespace": self._namespace,
            "state": self._state.value,
            "entries": self.size,
            "statistics": {
                "reads": self._statistics.reads,
                "writes": self._statistics.writes,
                "updates": self._statistics.updates,
                "deletes": self._statistics.deletes,
                "searches": self._statistics.searches,
            },
            "timestamp": datetime.now(UTC),
        }


    async def flush(self) -> None:
        """
        Flush pending runtime work.

        Subclasses may override this method
        when buffered persistence is required.
        """

        return


    async def synchronize(self) -> None:
        """
        Synchronize runtime state with the backend.

        Default implementation only calls flush().
        """

        await self.flush()
            # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    async def export(
        self,
    ) -> dict[str, Any]:
        """
        Export the complete runtime memory state.
        """

        return {
            "id": str(self._id),
            "namespace": self._namespace,
            "state": self._state.value,
            "entries": self._entries,
            "statistics": self.metrics(),
            "created_at": self._created_at,
            "last_accessed": self._last_accessed,
        }


    async def import_data(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        """
        Restore runtime state from exported data.
        """

        entries = payload.get("entries")

        if isinstance(entries, dict):
            self._entries.update(entries)

        self._statistics.entries = self.size

        self._touch()


    async def serialize(
        self,
    ) -> bytes:
        """
        Serialize memory using the configured serializer.
        """

        if self._serializer is None:
            raise RuntimeError(
                "No serializer has been configured."
            )

        payload = await self.export()

        return self._serializer.dumps(
            payload,
        )


    async def deserialize(
        self,
        payload: bytes,
    ) -> None:
        """
        Restore serialized memory.
        """

        if self._serializer is None:
            raise RuntimeError(
                "No serializer has been configured."
            )

        restored = self._serializer.loads(
            payload,
        )

        if not isinstance(restored, Mapping):
            raise TypeError(
                "Serialized payload must produce a mapping."
            )

        await self.import_data(
            restored,
        )


    # ------------------------------------------------------------------
    # Reset Helpers
    # ------------------------------------------------------------------

    async def reset(
        self,
    ) -> None:
        """
        Reset runtime state while keeping configuration.
        """

        self._entries.clear()

        self._statistics = MemoryStatistics()

        self._touch()


    # ------------------------------------------------------------------
    # Async Context Manager
    # ------------------------------------------------------------------

    async def __aenter__(
        self,
    ) -> "BaseMemory[MemoryValue]":

        await self.initialize()

        return self


    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:

        await self.close()


    # ------------------------------------------------------------------
    # Resource Cleanup
    # ------------------------------------------------------------------

    async def dispose(
        self,
    ) -> None:
        """
        Flush pending work and release resources.
        """

        await self.synchronize()

        await self.close()


    async def shutdown(
        self,
    ) -> None:
        """
        Gracefully terminate the memory instance.
        """

        if self._closed:
            return

        await self.dispose()


    async def cleanup(
        self,
    ) -> None:
        """
        Compatibility cleanup alias.
        """

        await self.shutdown()


    # ------------------------------------------------------------------
    # Miscellaneous
    # ------------------------------------------------------------------

    def __len__(
        self,
    ) -> int:

        return self.size


    def __contains__(
        self,
        key: str,
    ) -> bool:

        return key in self._entries


    def __repr__(
        self,
    ) -> str:

        return (
            f"{self.__class__.__name__}("
            f"namespace={self._namespace!r}, "
            f"entries={self.size}, "
            f"state={self._state.value!r})"
        )
            # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Validate the current runtime state.
        """

        if self._closed and self._state != MemoryState.CLOSED:
            raise RuntimeError(
                "Memory state is inconsistent."
            )

        if self._initialized and self._state == MemoryState.CREATED:
            raise RuntimeError(
                "Initialized memory cannot remain in CREATED state."
            )

        for key, entry in self._entries.items():

            self._validate_key(key)

            self._validate_metadata(
                entry.metadata,
            )

            if key != entry.key:
                raise ValueError(
                    f"Entry key mismatch: '{key}' != '{entry.key}'."
                )


    # ------------------------------------------------------------------
    # Iteration Helpers
    # ------------------------------------------------------------------

    def __iter__(self):
        """
        Iterate over loaded memory entries.
        """

        return iter(self._entries.values())


    def __bool__(self) -> bool:
        """
        Return True when memory contains entries.
        """

        return bool(self._entries)


    # ------------------------------------------------------------------
    # Convenience Helpers
    # ------------------------------------------------------------------

    async def get_or_default(
        self,
        key: str,
        default: MemoryValue | None = None,
    ) -> MemoryValue | None:
        """
        Return a value or the provided default.
        """

        entry = await self.get(key)

        if entry is None:
            return default

        return entry.value


    async def require(
        self,
        key: str,
    ) -> MemoryEntry[MemoryValue]:
        """
        Retrieve an entry or raise KeyError.
        """

        entry = await self.get(key)

        if entry is None:
            raise KeyError(
                f"Memory key '{key}' was not found."
            )

        return entry


    async def touch(
        self,
        key: str,
    ) -> bool:
        """
        Refresh the update timestamp of an entry.
        """

        entry = await self.get(key)

        if entry is None:
            return False

        entry.metadata.updated_at = datetime.now(UTC)

        return True


    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize(self) -> None:
        """
        Final maintenance before shutdown.
        """

        self.validate()

        await self.compact()

        await self.synchronize()


    async def shutdown_gracefully(self) -> None:
        """
        Validate, synchronize and close.
        """

        await self.finalize()

        await self.shutdown()
