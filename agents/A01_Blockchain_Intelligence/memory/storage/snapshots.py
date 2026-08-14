"""
Snapshot Manager

Captures point-in-time snapshots of a storage backend's contents as
JSON documents, with optional metadata headers and label-based
retention.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence
from uuid import uuid4

from memory.base.memory import MemoryEntry
from memory.storage.repository import (
    StorageBackend,
    entry_to_payload,
    payload_to_entry,
)

DEFAULT_LABEL = "snapshot"
SNAPSHOT_VERSION = 1


class SnapshotError(Exception):
    """
    Raised when a snapshot cannot be created or read.
    """


class Snapshot:
    """
    Immutable snapshot document.
    """

    def __init__(
        self,
        *,
        label: str,
        created_at: datetime,
        entries: Sequence[dict[str, Any]],
        version: int = SNAPSHOT_VERSION,
    ) -> None:
        self._label = label
        self._created_at = created_at
        self._entries = list(entries)
        self._version = version

    @property
    def label(self) -> str:
        return self._label

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    @property
    def version(self) -> int:
        return self._version

    @property
    def count(self) -> int:
        return len(self._entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "label": self._label,
            "created_at": self._created_at.isoformat(),
            "count": self.count,
            "entries": self._entries,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Snapshot":
        try:
            return cls(
                label=str(payload["label"]),
                created_at=datetime.fromisoformat(payload["created_at"]),
                entries=payload.get("entries", []),
                version=int(payload.get("version", SNAPSHOT_VERSION)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError(f"Invalid snapshot payload: {exc}") from exc


class SnapshotManager:
    """
    Creates and reads storage snapshots.

    Responsibilities:
        * Capture all entries into a Snapshot document
        * Restore a snapshot into a backend
        * Serialize and deserialize snapshot documents
    """

    def __init__(
        self,
        backend: StorageBackend,
        *,
        default_label: str = DEFAULT_LABEL,
    ) -> None:
        self._backend = backend
        self._default_label = default_label

    @property
    def backend(self) -> StorageBackend:
        return self._backend

    async def create(
        self,
        *,
        label: str | None = None,
        keys: Iterable[str] | None = None,
    ) -> Snapshot:
        """
        Capture a snapshot of selected (or all) backend entries.
        """
        if keys is None:
            selected_keys = list(await self._backend.keys())
        else:
            selected_keys = list(keys)
        payloads: list[dict[str, Any]] = []
        for key in selected_keys:
            entry = await self._backend.load(key)
            if entry is not None:
                payloads.append(entry_to_payload(entry))
        payloads.sort(key=lambda item: item["key"])
        return Snapshot(
            label=label or self._default_label,
            created_at=datetime.now(UTC),
            entries=payloads,
        )

    async def restore(
        self,
        snapshot: Snapshot,
        *,
        replace: bool = False,
        include_keys: Iterable[str] | None = None,
    ) -> int:
        """
        Write snapshot entries into the backend.

        With ``replace=True``, clears the backend before restoring.
        ``include_keys`` restricts which snapshot keys are written.
        """
        include = set(include_keys) if include_keys is not None else None
        if replace:
            await self._backend.clear()
        count = 0
        for payload in snapshot.entries:
            key = payload.get("key")
            if key is None:
                continue
            if include is not None and key not in include:
                continue
            entry = payload_to_entry(payload)
            await self._backend.save(entry)
            count += 1
        return count

    @classmethod
    def serialize(cls, snapshot: Snapshot) -> str:
        return snapshot.to_json()

    @classmethod
    def deserialize(cls, payload: str) -> Snapshot:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"Invalid snapshot JSON: {exc}") from exc
        return Snapshot.from_dict(data)
