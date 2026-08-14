"""
Memory Repository

Defines the storage backend protocol, serialization helpers, and a
high-level repository facade that composes any backend with typed
entry CRUD, namespacing, batch operations, and statistics.
"""

from __future__ import annotations

import json
from dataclasses import is_dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Protocol, Sequence
from uuid import UUID

from memory.base.memory import (
    MemoryEntry,
    MemoryMetadata,
    MemoryPriority,
    MemoryStatistics,
)


class StorageError(Exception):
    """
    Base class for storage-layer failures.
    """


class StorageConnectionError(StorageError):
    """
    Raised when a backend cannot connect or disconnect cleanly.
    """


class StorageKeyError(StorageError):
    """
    Raised on invalid or missing keys.
    """


class StorageSerializationError(StorageError):
    """
    Raised when an entry cannot be serialized or deserialized.
    """


class StorageBackend(Protocol):
    """
    Durable storage backend contract for memory entries.

    Mirrors ``MemoryBackendProtocol`` from ``memory.base.long_term``
    plus lifecycle hooks, so any backend here can be plugged into a
    base memory engine or used standalone via ``MemoryRepository``.
    """

    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        ...

    async def delete(
        self,
        key: str,
    ) -> None:
        ...

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        ...

    async def keys(self) -> Sequence[str]:
        ...

    async def clear(self) -> None:
        ...


def _to_jsonable(value: Any) -> Any:
    """
    Recursively convert common Python values into JSON-safe types.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, set):
        return sorted(_to_jsonable(item) for item in value)
    raise StorageSerializationError(
        f"Cannot serialize value of type {type(value).__name__}."
    )


def entry_to_payload(entry: MemoryEntry[Any]) -> dict[str, Any]:
    """
    Convert a MemoryEntry into a JSON-safe dict payload.
    """
    metadata = entry.metadata
    return {
        "key": entry.key,
        "value": _to_jsonable(entry.value),
        "metadata": {
            "namespace": metadata.namespace,
            "source": metadata.source,
            "tags": list(metadata.tags),
            "confidence": metadata.confidence,
            "priority": metadata.priority.value,
            "created_at": metadata.created_at.isoformat(),
            "updated_at": metadata.updated_at.isoformat(),
            "expires_at": (
                metadata.expires_at.isoformat()
                if metadata.expires_at is not None
                else None
            ),
        },
        "identifier": str(entry.identifier),
    }


def payload_to_entry(payload: dict[str, Any]) -> MemoryEntry[Any]:
    """
    Convert a JSON-safe dict payload back into a MemoryEntry.
    """
    try:
        metadata = payload.get("metadata", {})
        expires = metadata.get("expires_at")
        entry = MemoryEntry(
            key=str(payload["key"]),
            value=payload.get("value"),
            metadata=MemoryMetadata(
                namespace=str(metadata.get("namespace", "default")),
                source=str(metadata.get("source", "runtime")),
                tags=list(metadata.get("tags", [])),
                confidence=float(metadata.get("confidence", 1.0)),
                priority=MemoryPriority(int(metadata.get("priority", MemoryPriority.NORMAL.value))),
                created_at=datetime.fromisoformat(metadata["created_at"]),
                updated_at=datetime.fromisoformat(metadata["updated_at"]),
                expires_at=datetime.fromisoformat(expires) if expires else None,
            ),
            identifier=UUID(payload["identifier"]),
        )
        return entry
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageSerializationError(
            f"Invalid entry payload: {exc}"
        ) from exc


def dumps_entry(entry: MemoryEntry[Any]) -> str:
    """
    Serialize an entry to a compact JSON string.
    """
    return json.dumps(entry_to_payload(entry), sort_keys=True)


def loads_entry(payload: str) -> MemoryEntry[Any]:
    """
    Deserialize an entry from a JSON string.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StorageSerializationError(f"Invalid JSON payload: {exc}") from exc
    return payload_to_entry(data)


def entry_payload_matches(entry: MemoryEntry[Any], query: str) -> bool:
    """
    Return True when the entry's key or string value contains the query.
    """
    needle = query.lower()
    if needle in entry.key.lower():
        return True
    value = entry.value
    if isinstance(value, str) and needle in value.lower():
        return True
    return needle in str(value).lower()


class MemoryRepository:
    """
    High-level facade over any ``StorageBackend``.

    Responsibilities:
        * Compose a backend with typed entry CRUD
        * Enforce namespaces and key validation
        * Provide batch operations and statistics
    """

    def __init__(
        self,
        backend: StorageBackend,
        *,
        namespace: str = "default",
    ) -> None:
        self._backend = backend
        self._namespace = namespace
        self._statistics = MemoryStatistics()
        self._connected = False

    @property
    def backend(self) -> StorageBackend:
        return self._backend

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def statistics(self) -> MemoryStatistics:
        return self._statistics

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await self._backend.connect()
        self._connected = True
        self._statistics.entries = len(await self._backend.keys())

    async def disconnect(self) -> None:
        await self._backend.disconnect()
        self._connected = False

    def _key(self, key: str) -> str:
        if not key or not key.strip():
            raise StorageKeyError("Key must be non-empty.")
        return key

    async def save(self, entry: MemoryEntry[Any]) -> None:
        if entry.metadata.namespace != self._namespace:
            raise StorageKeyError(
                f"Namespace mismatch: {entry.metadata.namespace} != {self._namespace}"
            )
        self._key(entry.key)
        existed = await self._backend.load(entry.key) is not None
        await self._backend.save(entry)
        self._statistics.writes += 1
        if not existed:
            self._statistics.entries += 1

    async def get(self, key: str) -> MemoryEntry[Any] | None:
        entry = await self._backend.load(self._key(key))
        if entry is not None:
            self._statistics.reads += 1
        return entry

    async def require(self, key: str) -> MemoryEntry[Any]:
        entry = await self.get(key)
        if entry is None:
            raise StorageKeyError(f"Key '{key}' was not found.")
        return entry

    async def delete(self, key: str) -> bool:
        before = await self._backend.load(self._key(key))
        if before is None:
            return False
        await self._backend.delete(key)
        self._statistics.deletes += 1
        self._statistics.entries = max(0, self._statistics.entries - 1)
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[MemoryEntry[Any]]:
        self._statistics.searches += 1
        results = await self._backend.search(query, limit=limit)
        return list(results)

    async def keys(self) -> list[str]:
        return list(await self._backend.keys())

    async def list_entries(
        self,
        *,
        limit: int | None = None,
    ) -> list[MemoryEntry[Any]]:
        found: list[MemoryEntry[Any]] = []
        for key in await self._backend.keys():
            entry = await self._backend.load(key)
            if entry is not None:
                found.append(entry)
                if limit is not None and len(found) >= limit:
                    break
        return found

    async def count(self) -> int:
        return len(await self._backend.keys())

    async def exists(self, key: str) -> bool:
        return await self._backend.load(self._key(key)) is not None

    async def save_many(self, entries: Iterable[MemoryEntry[Any]]) -> int:
        count = 0
        for entry in entries:
            await self.save(entry)
            count += 1
        return count

    async def delete_many(self, keys: Iterable[str]) -> int:
        count = 0
        for key in keys:
            if await self.delete(key):
                count += 1
        return count

    async def clear(self) -> int:
        count = len(await self._backend.keys())
        await self._backend.clear()
        self._statistics.deletes += count
        self._statistics.entries = 0
        return count

    def metrics(self) -> dict[str, Any]:
        stats = self._statistics
        return {
            "entries": stats.entries,
            "reads": stats.reads,
            "writes": stats.writes,
            "updates": stats.updates,
            "deletes": stats.deletes,
            "searches": stats.searches,
            "connected": self._connected,
            "namespace": self._namespace,
        }

    def health(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "backend": type(self._backend).__name__,
            "namespace": self._namespace,
            "entries": self._statistics.entries,
        }
