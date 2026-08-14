"""
Backup Service

Persists storage snapshots to disk with naming, rotation, and optional
gzip compression. Coordinates with ``SnapshotManager`` to produce
restore-ready backup files.
"""

from __future__ import annotations

import gzip
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory.storage.repository import StorageBackend
from memory.storage.snapshots import Snapshot, SnapshotManager

DEFAULT_BACKUP_DIR = "memory_backups"
DEFAULT_RETENTION = 7
COMPRESS_EXTENSION = ".gz"


class BackupError(Exception):
    """
    Raised when a backup cannot be written or listed.
    """


class BackupService:
    """
    Writes and manages on-disk backups of storage snapshots.

    Responsibilities:
        * Create timestamped backup files
        * Apply retention-based rotation
        * Load backups for restore
    """

    def __init__(
        self,
        backend: StorageBackend,
        *,
        directory: str | Path = DEFAULT_BACKUP_DIR,
        retention: int = DEFAULT_RETENTION,
        compress: bool = False,
    ) -> None:
        self._snapshots = SnapshotManager(backend)
        self._directory = Path(directory)
        self._retention = retention
        self._compress = compress

    @property
    def backend(self) -> StorageBackend:
        return self._snapshots.backend

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def retention(self) -> int:
        return self._retention

    def _extension(self) -> str:
        return f".json{COMPRESS_EXTENSION if self._compress else ''}"

    async def create_backup(
        self,
        *,
        label: str = "backup",
    ) -> Path:
        """
        Snapshot the backend and write it to a timestamped file.
        """
        snapshot = await self._snapshots.create(label=label)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = self._directory / f"{label}_{timestamp}{self._extension()}"
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            content = snapshot.to_json().encode("utf-8")
            if self._compress:
                with gzip.open(path, "wb") as handle:
                    handle.write(content)
            else:
                path.write_bytes(content)
        except OSError as exc:
            raise BackupError(f"Backup write failed: {exc}") from exc
        await self.prune()
        return path

    def list_backups(self) -> list[Path]:
        """
        Return backup files sorted newest-first.
        """
        pattern = f"*{self._extension()}"
        backups = [
            path for path in self._directory.glob(pattern) if path.is_file()
        ]
        backups.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return backups

    async def prune(self) -> int:
        """
        Remove backups beyond the retention limit.
        """
        backups = self.list_backups()
        removed = 0
        for path in backups[self._retention:]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    async def load_snapshot(self, path: str | Path) -> Snapshot:
        """
        Read a backup file back into a Snapshot.
        """
        target = Path(path)
        try:
            if target.name.endswith(COMPRESS_EXTENSION):
                with gzip.open(target, "rb") as handle:
                    content = handle.read()
            else:
                content = target.read_bytes()
        except OSError as exc:
            raise BackupError(f"Backup read failed: {exc}") from exc
        return SnapshotManager.deserialize(content.decode("utf-8"))

    async def restore(self, path: str | Path, *, replace: bool = False) -> int:
        """
        Restore a backup file into the backend.
        """
        snapshot = await self.load_snapshot(path)
        return await self._snapshots.restore(snapshot, replace=replace)

    def health(self) -> dict[str, Any]:
        return {
            "directory": str(self._directory),
            "retention": self._retention,
            "compress": self._compress,
            "backups": len(self.list_backups()),
        }
