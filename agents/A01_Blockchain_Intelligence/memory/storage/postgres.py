"""
Postgres Storage

PostgreSQL-backed persistent storage backend for production memory
using asyncpg. Provides async connection management, schema/index
management, and transactional writes.
"""

from __future__ import annotations

from typing import Any, Sequence

from memory.base.memory import MemoryEntry
from memory.storage.repository import (
    StorageConnectionError,
    StorageError,
    dumps_entry,
    entry_payload_matches,
    loads_entry,
)
from memory.utils.retry import retry

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "memory"
DEFAULT_TABLE = "memory_entries"


class PostgresStorage:
    """
    PostgreSQL persistence backend for memory.

    Responsibilities:
        * Async connection management
        * Schema and index management
        * Transactional writes
    """

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        database: str = DEFAULT_DATABASE,
        user: str = "postgres",
        password: str | None = None,
        table: str = DEFAULT_TABLE,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._table = table
        self._pool: Any = None

    @property
    def table(self) -> str:
        return self._table

    @property
    def pool(self) -> Any:
        return self._pool

    async def connect(self) -> None:
        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:
            raise StorageConnectionError(
                "asyncpg is not installed; pip install asyncpg"
            ) from exc
        try:
            await retry(self._open_pool, attempts=3, base_delay=0.2, max_delay=2.0)
        except Exception as exc:
            self._pool = None
            raise StorageConnectionError(
                f"Postgres connect failed: {exc}"
            ) from exc

    async def _open_pool(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(
            host=self._host,
            port=self._port,
            database=self._database,
            user=self._user,
            password=self._password,
        )
        try:
            await self._create_schema()
        except Exception:
            await self._pool.close()
            self._pool = None
            raise

    async def disconnect(self) -> None:
        if self._pool is not None:
            try:
                await self._pool.close()
            finally:
                self._pool = None

    async def _create_schema(self) -> None:
        async with self._require_pool().acquire() as connection:
            await connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            await connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self._table}_key ON {self._table}(key)"
            )

    async def save(self, entry: MemoryEntry[Any]) -> None:
        payload = dumps_entry(entry)
        try:
            async with self._require_pool().acquire() as connection:
                await connection.execute(
                    f"""
                    INSERT INTO {self._table} (key, payload)
                    VALUES ($1, $2)
                    ON CONFLICT (key) DO UPDATE SET payload = excluded.payload
                    """,
                    entry.key,
                    payload,
                )
        except Exception as exc:
            raise StorageError(f"Postgres save failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            async with self._require_pool().acquire() as connection:
                await connection.execute(
                    f"DELETE FROM {self._table} WHERE key = $1",
                    key,
                )
        except Exception as exc:
            raise StorageError(f"Postgres delete failed: {exc}") from exc

    async def load(self, key: str) -> MemoryEntry[Any] | None:
        try:
            async with self._require_pool().acquire() as connection:
                row = await connection.fetchrow(
                    f"SELECT payload FROM {self._table} WHERE key = $1",
                    key,
                )
        except Exception as exc:
            raise StorageError(f"Postgres load failed: {exc}") from exc
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
            async with self._require_pool().acquire() as connection:
                rows = await connection.fetch(
                    f"SELECT payload FROM {self._table} ORDER BY key ASC"
                )
        except Exception as exc:
            raise StorageError(f"Postgres search failed: {exc}") from exc
        results: list[MemoryEntry[Any]] = []
        for row in rows:
            entry = loads_entry(row["payload"])
            if entry_payload_matches(entry, query):
                results.append(entry)
        return results[:limit]

    async def keys(self) -> Sequence[str]:
        try:
            async with self._require_pool().acquire() as connection:
                rows = await connection.fetch(
                    f"SELECT key FROM {self._table} ORDER BY key ASC"
                )
        except Exception as exc:
            raise StorageError(f"Postgres keys failed: {exc}") from exc
        return [row["key"] for row in rows]

    async def clear(self) -> None:
        try:
            async with self._require_pool().acquire() as connection:
                await connection.execute(f"DELETE FROM {self._table}")
        except Exception as exc:
            raise StorageError(f"Postgres clear failed: {exc}") from exc

    def _require_pool(self) -> Any:
        if self._pool is None:
            raise StorageConnectionError("Postgres storage is not connected.")
        return self._pool
