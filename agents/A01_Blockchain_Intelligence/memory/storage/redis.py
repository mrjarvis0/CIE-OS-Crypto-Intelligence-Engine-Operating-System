"""
Redis Storage

Redis-backed storage backend for fast, volatile memory and caching.
Uses ``redis.asyncio`` for hash-based entries with optional TTL
expiration.
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
DEFAULT_PORT = 6379
DEFAULT_DB = 0
DEFAULT_PREFIX = "memory"
DEFAULT_TTL_SECONDS = 3600


class RedisStorage:
    """
    Redis persistence backend for memory.

    Responsibilities:
        * Key-value and hash storage
        * TTL-based expiration
        * Cursor and queue support
    """

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        db: int = DEFAULT_DB,
        password: str | None = None,
        prefix: str = DEFAULT_PREFIX,
        ttl_seconds: int | None = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._prefix = prefix
        self._ttl_seconds = ttl_seconds
        self._client: Any = None

    @property
    def prefix(self) -> str:
        return self._prefix

    @property
    def client(self) -> Any:
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def connect(self) -> None:
        try:
            import redis.asyncio as aioredis

            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True,
            )
        except ImportError as exc:
            raise StorageConnectionError(
                "redis is not installed; pip install redis"
            ) from exc
        try:
            await retry(self._client.ping, attempts=3, base_delay=0.1, max_delay=1.0)
        except Exception as exc:
            self._client = None
            raise StorageConnectionError(
                f"Redis connect failed: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    async def save(self, entry: MemoryEntry[Any]) -> None:
        payload = dumps_entry(entry)
        try:
            await self._require_client().set(
                self._full_key(entry.key),
                payload,
                ex=self._ttl_seconds,
            )
        except Exception as exc:
            raise StorageError(f"Redis save failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            await self._require_client().delete(self._full_key(key))
        except Exception as exc:
            raise StorageError(f"Redis delete failed: {exc}") from exc

    async def load(self, key: str) -> MemoryEntry[Any] | None:
        try:
            payload = await self._require_client().get(self._full_key(key))
        except Exception as exc:
            raise StorageError(f"Redis load failed: {exc}") from exc
        if payload is None:
            return None
        return loads_entry(payload)

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        keys = await self.keys()
        results: list[MemoryEntry[Any]] = []
        for key in keys:
            entry = await self.load(key)
            if entry is None:
                continue
            if entry_payload_matches(entry, query):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    async def keys(self) -> Sequence[str]:
        try:
            raw_keys = await self._require_client().keys(f"{self._prefix}:*")
        except Exception as exc:
            raise StorageError(f"Redis keys failed: {exc}") from exc
        prefix_len = len(self._prefix) + 1
        return [key[prefix_len:] for key in raw_keys]

    async def clear(self) -> None:
        try:
            keys = await self._require_client().keys(f"{self._prefix}:*")
            if keys:
                await self._require_client().delete(*keys)
        except Exception as exc:
            raise StorageError(f"Redis clear failed: {exc}") from exc

    def _require_client(self) -> Any:
        if self._client is None:
            raise StorageConnectionError("Redis storage is not connected.")
        return self._client
