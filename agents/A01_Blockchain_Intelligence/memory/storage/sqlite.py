"""
SQLite Storage

SQLite-backed persistent storage backend for memory entries using
aiosqlite. Provides schema management, atomic writes, and indexed
retrieval over serialized entry payloads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import aiosqlite

from memory.base.memory import MemoryEntry
from memory.storage.repository import (
    StorageBackend,
    StorageConnectionError,
    StorageError,
    dumps_entry,
    entry_payload_matches,
    loads_entry,
)

DEFAULT_DB_PATH = "memory.db"
SCHEMA_VERSION = 1


class SqliteStorage:
    """
    SQLite persistence backend for memory.

    Responsibilities:
        * Schema creation and migrations
        * Atomic reads and writes
        * Indexed retrieval
    """

    def __init__(
        self,
        *,
        path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self._path = Path(path)
        self._connection: aiosqlite.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def connection(self) -> aiosqlite.Connection | None:
        return self._connection

    async def connect(self) -> None:
        # Idempotent. A second connect would reassign self._connection and
        # orphan the live one -- aiosqlite then reports it deleted-before-closed
        # at GC. A caller that connects the storage and then the repository
        # wrapping it (repo.connect() connects its backend) hits exactly that,
        # so the second call is a no-op rather than a leak.
        if self._connection is not None:
            return
        connection: aiosqlite.Connection | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = await aiosqlite.connect(str(self._path))
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA foreign_keys=ON")
            await self._create_schema(connection)
            self._connection = connection
        except aiosqlite.Error as exc:
            if connection is not None:
                await connection.close()
            raise StorageConnectionError(
                f"SQLite connect failed: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            await connection.close()
        finally:
            self._connection = None

    async def _create_schema(self, connection: aiosqlite.Connection) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_entries (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_key ON memory_entries(key)"
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS storage_schema (
                version INTEGER NOT NULL
            )
            """
        )
        await connection.execute("INSERT OR IGNORE INTO storage_schema (version) VALUES (?)", (SCHEMA_VERSION,))
        await connection.commit()

    async def save(self, entry: MemoryEntry[Any]) -> None:
        payload = dumps_entry(entry)
        try:
            await self._require_connection().execute(
                "INSERT INTO memory_entries (key, payload) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload",
                (entry.key, payload),
            )
            await self._require_connection().commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"SQLite save failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            await self._require_connection().execute(
                "DELETE FROM memory_entries WHERE key = ?",
                (key,),
            )
            await self._require_connection().commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"SQLite delete failed: {exc}") from exc

    async def load(self, key: str) -> MemoryEntry[Any] | None:
        try:
            cursor = await self._require_connection().execute(
                "SELECT payload FROM memory_entries WHERE key = ?",
                (key,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        except aiosqlite.Error as exc:
            raise StorageError(f"SQLite load failed: {exc}") from exc
        if row is None:
            return None
        return loads_entry(row["payload"])

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        try:
            cursor = await self._require_connection().execute(
                "SELECT payload FROM memory_entries ORDER BY key ASC"
            )
            rows = await cursor.fetchall()
            await cursor.close()
        except aiosqlite.Error as exc:
            raise StorageError(f"SQLite search failed: {exc}") from exc
        results: list[MemoryEntry[Any]] = []
        for row in rows:
            entry = loads_entry(row["payload"])
            if entry_payload_matches(entry, query):
                results.append(entry)
        return results[:limit]

    async def keys(self) -> Sequence[str]:
        try:
            cursor = await self._require_connection().execute(
                "SELECT key FROM memory_entries ORDER BY key ASC"
            )
            rows = await cursor.fetchall()
            await cursor.close()
        except aiosqlite.Error as exc:
            raise StorageError(f"SQLite keys failed: {exc}") from exc
        return [row["key"] for row in rows]

    async def clear(self) -> None:
        try:
            await self._require_connection().execute("DELETE FROM memory_entries")
            await self._require_connection().commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"SQLite clear failed: {exc}") from exc

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise StorageConnectionError("SQLite storage is not connected.")
        return self._connection
