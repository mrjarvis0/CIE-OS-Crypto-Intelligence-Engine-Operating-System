"""
Restore Service

Restores storage backends from backup files or snapshot documents.
Provides dry-run inspection, targeted key restores, and replace-vs-merge
semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from memory.storage.backup import BackupService
from memory.storage.repository import StorageBackend
from memory.storage.snapshots import Snapshot, SnapshotManager


class RestoreError(Exception):
    """
    Raised when a restore operation cannot be completed.
    """


class RestoreService:
    """
    Restores memory backends from backups or snapshots.

    Responsibilities:
        * Load backup files and snapshot documents
        * Inspect restore targets before applying
        * Apply replace or merge restores
    """

    def __init__(
        self,
        backend: StorageBackend,
    ) -> None:
        self._snapshots = SnapshotManager(backend)

    @property
    def backend(self) -> StorageBackend:
        return self._snapshots.backend

    async def inspect(self, path: str | Path) -> dict[str, Any]:
        """
        Return metadata about a backup file without applying it.
        """
        backup_service = BackupService(self.backend)
        snapshot = await backup_service.load_snapshot(path)
        return {
            "label": snapshot.label,
            "version": snapshot.version,
            "created_at": snapshot.created_at,
            "count": snapshot.count,
            "keys": [entry["key"] for entry in snapshot.entries],
        }

    async def restore_file(
        self,
        path: str | Path,
        *,
        replace: bool = False,
        include_keys: Iterable[str] | None = None,
    ) -> int:
        """
        Restore a backup file into the backend.
        """
        backup_service = BackupService(self.backend)
        snapshot = await backup_service.load_snapshot(path)
        return await self._snapshots.restore(
            snapshot,
            replace=replace,
            include_keys=include_keys,
        )

    async def restore_snapshot(
        self,
        snapshot: Snapshot,
        *,
        replace: bool = False,
        include_keys: Iterable[str] | None = None,
    ) -> int:
        """
        Restore an in-memory snapshot into the backend.
        """
        return await self._snapshots.restore(
            snapshot,
            replace=replace,
            include_keys=include_keys,
        )

    async def restore_backup_service(
        self,
        backup_service: BackupService,
        path: str | Path,
        *,
        replace: bool = False,
    ) -> int:
        """
        Restore using a pre-configured BackupService instance.
        """
        snapshot = await backup_service.load_snapshot(path)
        return await self._snapshots.restore(snapshot, replace=replace)
