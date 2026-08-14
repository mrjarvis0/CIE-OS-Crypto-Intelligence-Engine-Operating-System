"""
Memory Synchronization Operations

Low-level synchronization helpers: lock guards, state transfer, entry
merge, and metadata merge over ``ShortTermMemory``-like sources.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

LockSource = Any
SyncSource = Any
EntrySource = Any
MetaSource = Any


class LockError(Exception):
    pass


class SyncLock:
    """
    Async lock guard over a lockable memory source.

    Responsibilities:
        * Acquire / release the underlying memory lock
        * Report lock state
        * Provide an async context-manager style
    """

    def __init__(self, source: LockSource) -> None:
        self._source = source
        self._acquired = False

    @property
    def source(self) -> LockSource:
        return self._source

    def supported(self) -> bool:
        return callable(getattr(self._source, "acquire_lock", None))

    async def acquire(self) -> bool:
        acquire = getattr(self._source, "acquire_lock", None)
        if not callable(acquire):
            raise LockError("source must expose acquire_lock()")
        result = acquire()
        if hasattr(result, "__await__"):
            await result
        self._acquired = True
        return True

    async def release(self) -> bool:
        release = getattr(self._source, "release_lock", None)
        if not callable(release):
            raise LockError("source must expose release_lock()")
        result = release()
        if hasattr(result, "__await__"):
            await result
        self._acquired = False
        return True

    async def locked(self) -> bool:
        locked = getattr(self._source, "locked", None)
        if not callable(locked):
            return self._acquired
        result = locked()
        if hasattr(result, "__await__"):
            return bool(await result)
        return bool(result)

    async def __aenter__(self) -> "SyncLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.release()

    def describe(self) -> dict[str, Any]:
        return {
            "supported": self.supported(),
            "acquired": self._acquired,
            "source": type(self._source).__name__,
        }


class StateSyncError(Exception):
    pass


class StateSynchronizer:
    """
    Transfer full state between memory sources.

    Responsibilities:
        * Export a source's state payload
        * Import a payload into a target
        * Transfer state directly between two sources
    """

    def __init__(self) -> None:
        pass

    async def export(self, source: SyncSource) -> dict[str, Any]:
        export_state = getattr(source, "export_state", None)
        if not callable(export_state):
            raise StateSyncError("source must expose export_state()")
        result = export_state()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if not isinstance(payload, dict):
            raise StateSyncError("export_state() must return a dict.")
        return payload

    async def import_state(
        self,
        target: SyncSource,
        payload: dict[str, Any],
    ) -> bool:
        import_state = getattr(target, "import_state", None)
        if not callable(import_state):
            raise StateSyncError("target must expose import_state()")
        result = import_state(payload)
        if hasattr(result, "__await__"):
            await result
        return True

    async def transfer(
        self,
        source: SyncSource,
        target: SyncSource,
    ) -> dict[str, Any]:
        payload = await self.export(source)
        await self.import_state(target, payload)
        return payload

    async def describe(
        self,
        source: SyncSource,
    ) -> dict[str, Any]:
        payload = await self.export(source)
        return {
            "namespace": payload.get("namespace"),
            "state": payload.get("state"),
            "entries": payload.get("entries"),
            "metadata_keys": sorted(
                (payload.get("metadata") or {}).keys()
            ),
        }


class EntrySyncError(Exception):
    pass


class EntrySynchronizer:
    """
    Push / merge memory entries between sources.

    Responsibilities:
        * Merge a batch of entries into a target
        * Synchronize one source against another
        * Merge from many sources into a single target
    """

    def __init__(self) -> None:
        pass

    async def synchronize_entries(
        self,
        target: EntrySource,
        entries: Iterable[Any],
    ) -> int:
        method = getattr(target, "synchronize_entries", None)
        if not callable(method):
            raise EntrySyncError(
                "target must expose synchronize_entries()"
            )
        result = method(entries)
        count = await result if hasattr(result, "__await__") else result
        return int(count)

    async def synchronize_with(
        self,
        target: EntrySource,
        other: EntrySource,
    ) -> int:
        method = getattr(target, "synchronize_with", None)
        if not callable(method):
            raise EntrySyncError(
                "target must expose synchronize_with()"
            )
        result = method(other)
        count = await result if hasattr(result, "__await__") else result
        return int(count)

    async def merge(
        self,
        target: EntrySource,
        sources: Iterable[EntrySource],
    ) -> int:
        total = 0
        for source in sources:
            total += await self.synchronize_with(target, source)
        return total


class MetadataSyncError(Exception):
    pass


class MetadataSynchronizer:
    """
    Merge runtime metadata across memory sources.

    Responsibilities:
        * Merge a metadata mapping into a target
        * Diff metadata between two sources
    """

    def __init__(self) -> None:
        pass

    async def synchronize_metadata(
        self,
        target: MetaSource,
        metadata: Mapping[str, Any],
    ) -> bool:
        method = getattr(target, "synchronize_metadata", None)
        if not callable(method):
            raise MetadataSyncError(
                "target must expose synchronize_metadata()"
            )
        result = method(metadata)
        if hasattr(result, "__await__"):
            await result
        return True

    async def merge(
        self,
        target: MetaSource,
        mappings: Iterable[Mapping[str, Any]],
    ) -> int:
        count = 0
        for mapping in mappings:
            await self.synchronize_metadata(target, mapping)
            count += len(mapping)
        return count

    async def diff(
        self,
        source_a: MetaSource,
        source_b: MetaSource,
    ) -> dict[str, Any]:
        payload_a = await self._export_metadata(source_a)
        payload_b = await self._export_metadata(source_b)
        keys_a = set(payload_a)
        keys_b = set(payload_b)
        return {
            "only_in_a": sorted(keys_a - keys_b),
            "only_in_b": sorted(keys_b - keys_a),
            "shared": sorted(keys_a & keys_b),
        }

    async def _export_metadata(
        self,
        source: MetaSource,
    ) -> dict[str, Any]:
        export_state = getattr(source, "export_state", None)
        if not callable(export_state):
            raise MetadataSyncError(
                "source must expose export_state()"
            )
        result = export_state()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        metadata = payload.get("metadata") or {}
        return dict(metadata)
