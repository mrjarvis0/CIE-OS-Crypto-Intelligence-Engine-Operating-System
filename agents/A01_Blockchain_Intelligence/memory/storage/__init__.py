"""
Memory Storage Package

Storage backends: sqlite, postgres, redis, filesystem, and cache,
plus repository, migration, snapshot, backup, and restore services.
"""

from __future__ import annotations

from memory.storage.backup import BackupError, BackupService
from memory.storage.cache import CacheStorage
from memory.storage.filesystem import FileSystemStorage
from memory.storage.migration import (
    MigrationError,
    MigrationRecord,
    MigrationRunner,
    Migrator,
)
from memory.storage.postgres import PostgresStorage
from memory.storage.redis import RedisStorage
from memory.storage.repository import (
    MemoryRepository,
    StorageBackend,
    StorageConnectionError,
    StorageError,
    StorageKeyError,
    StorageSerializationError,
    dumps_entry,
    entry_to_payload,
    loads_entry,
    payload_to_entry,
)
from memory.storage.restore import RestoreError, RestoreService
from memory.storage.snapshots import Snapshot, SnapshotError, SnapshotManager
from memory.storage.sqlite import SqliteStorage

__all__ = [
    "BackupError",
    "BackupService",
    "CacheStorage",
    "FileSystemStorage",
    "MemoryRepository",
    "MigrationError",
    "MigrationRecord",
    "MigrationRunner",
    "Migrator",
    "PostgresStorage",
    "RedisStorage",
    "RestoreError",
    "RestoreService",
    "Snapshot",
    "SnapshotError",
    "SnapshotManager",
    "SqliteStorage",
    "StorageBackend",
    "StorageConnectionError",
    "StorageError",
    "StorageKeyError",
    "StorageSerializationError",
    "dumps_entry",
    "entry_to_payload",
    "loads_entry",
    "payload_to_entry",
]
