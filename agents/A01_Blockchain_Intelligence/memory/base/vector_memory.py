"""
VectorMemory — Cognitive Engine

A full-featured vector memory implementation with semantic search,
metadata filtering, graph relations, deduplication, consolidation,
snapshot/backup, and lifecycle management.

Delegates to memory.vector.similarity and memory.vector.embeddings
for similarity computation and embedding generation respectively.

Architecture (25 parts):
  1. Foundation       — module setup, imports, constants
  2. Configuration    — VectorMemoryConfig dataclass
  3. Runtime Models   — internal data structures
  4. Embedding Engine — LocalHashEmbedder integration
  5. Embedding Cache  — in-memory + SQLite persisted cache
  6. Chunk Manager    — text chunking for large values
  7. Metadata Builder — structured metadata construction
  8. Namespace Manager — isolated namespace handling
  9. Collection Manager — named collection grouping
  10. Index Manager   — search index operations
  11. Storage Adapter — SQLite via aiosqlite
  12. Write Pipeline  — put / put_batch / update / delete / clear
  13. Search Engine   — semantic / exact / hybrid search
  14. Similarity Engine — cosine, dot, euclidean scoring
  15. Hybrid Retrieval — multi-strategy fusion
  16. Ranking Engine  — composite relevance scoring
  17. Memory Linking  — link / unlink between entries
  18. Graph Relations — edge storage and traversal
  19. Context Builder — assemble LLM-ready context blocks
  20. Compression     — dedup + compaction
  21. Promotion       — importance-based promotion
  22. Consolidation   — merge near-duplicate entries
  23. Synchronization — sync backend + snapshot / backup
  24. Health + Metrics — runtime observability
  25. Events + Lifecycle — async event bus, state machine
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import struct
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generic

import aiosqlite

from memory.base.memory import (
    BaseMemory,
    MemoryEntry,
    MemoryMetadata,
    MemorySearchResult,
    MemoryStatistics,
    MemoryState,
    MemoryPriority,
    MemoryOperation,
    SearchMode,
    EmbeddingProvider,
)
from memory.vector.similarity import SimilarityService, cosine_similarity
from memory.vector.embeddings import LocalHashEmbedder, DEFAULT_DIM


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

DEFAULT_VECTOR_DIM = DEFAULT_DIM
DEFAULT_COLLECTION = "_default"
DEFAULT_NAMESPACE = "default"
DEFAULT_THRESHOLD = 0.5
DEFAULT_LIMIT = 10
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_CACHE_MAX = 10_000
DEFAULT_SIMILARITY_WEIGHT = 0.6
DEFAULT_RECENCY_WEIGHT = 0.2
DEFAULT_IMPORTANCE_WEIGHT = 0.2


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------

class VectorMemoryError(Exception):
    pass


class VectorMemoryNotInitializedError(VectorMemoryError):
    pass


class VectorMemoryClosedError(VectorMemoryError):
    pass


class VectorMemoryNotFoundError(VectorMemoryError):
    pass


class VectorMemoryDuplicateError(VectorMemoryError):
    pass


class VectorMemoryValidationError(VectorMemoryError):
    pass


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

@dataclass
class VectorMemoryConfig:
    namespace: str = DEFAULT_NAMESPACE
    collection: str = DEFAULT_COLLECTION
    dim: int = DEFAULT_VECTOR_DIM
    seed: str = "vector_memory"
    threshold: float = DEFAULT_THRESHOLD
    limit: int = DEFAULT_LIMIT
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    cache_max_size: int = DEFAULT_CACHE_MAX
    similarity_weight: float = DEFAULT_SIMILARITY_WEIGHT
    recency_weight: float = DEFAULT_RECENCY_WEIGHT
    importance_weight: float = DEFAULT_IMPORTANCE_WEIGHT
    decay_half_life_hours: float = 168.0
    max_embedding_age_days: float = 30.0
    enable_dedup: bool = True
    enable_compression: bool = True
    enable_promotion: bool = True
    enable_consolidation: bool = True
    db_path: str = ":memory:"
    db_journal_mode: str = "WAL"
    db_cache_size_kb: int = 64_000
    snapshot_interval_seconds: float = 300.0
    auto_snapshot: bool = True
    auto_compact: bool = True
    enable_events: bool = True
    max_event_listeners: int = 50


# ------------------------------------------------------------------
# VectorMemory
# ------------------------------------------------------------------

class VectorMemory(BaseMemory[Any]):
    """
    Cognitive vector memory engine.

    Stores entries with generated embeddings, supports semantic
    similarity search, namespace isolation, metadata filtering,
    graph relations, deduplication, consolidation, snapshot/backup,
    and full lifecycle management.

    Not a thin Chroma wrapper — this is a self-contained cognitive
    engine with its own embedding, chunking, indexing, ranking,
    and retrieval pipeline.
    """

    # ------------------------------------------------------------------
    # Foundation — lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        backend: Any | None = None,
        serializer: Any | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        config: VectorMemoryConfig | None = None,
    ) -> None:
        super().__init__(
            namespace=namespace,
            backend=backend,
            serializer=serializer,
            embedding_provider=embedding_provider,
        )
        self._config = config or VectorMemoryConfig(namespace=namespace)
        self._db: aiosqlite.Connection | None = None
        self._db_path: str = self._config.db_path
        self._embedder = LocalHashEmbedder(
            dim=self._config.dim,
            seed=self._config.seed,
            max_cache_size=self._config.cache_max_size,
        )
        self._similarity = SimilarityService(
            default_threshold=self._config.threshold,
            default_metric="cosine",
        )
        self._listeners: dict[str, list[Callable[..., Any]]] = {}
        self._closed = False
        self._initialized = False
        self._entry_count = 0
        self._last_snapshot: datetime | None = None
        self._last_compact: datetime | None = None
        self._last_backup: datetime | None = None
        self._event_count = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> VectorMemoryConfig:
        return self._config

    @property
    def embedder(self) -> LocalHashEmbedder:
        return self._embedder

    @property
    def similarity(self) -> SimilarityService:
        return self._similarity

    @property
    def embedding_provider(self) -> EmbeddingProvider | None:
        return self._embedder

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise VectorMemoryNotInitializedError(
                "VectorMemory is not initialized. Call initialize() first."
            )
        return self._db

    @property
    def size(self) -> int:
        return self._entry_count

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
        async with self._lock:
            if self._initialized:
                return
            self._set_state(MemoryState.INITIALIZING)
            try:
                await self._ensure_db()
                await self._init_schema()
                self._set_state(MemoryState.READY)
                self._initialized = True
            except Exception:
                self._set_state(MemoryState.CLOSED)
                raise

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            try:
                if self._db is not None:
                    await self._db.close()
                    self._db = None
            finally:
                self._set_state(MemoryState.CLOSED)
                self._closed = True
                self._initialized = False

    async def __aenter__(self) -> VectorMemory:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        await self.close()

    async def flush(self) -> None:
        if self._db is not None:
            await self._db.commit()

    async def dispose(self) -> None:
        await self.close()

    async def shutdown(self) -> None:
        await self.close()

    async def shutdown_gracefully(self) -> None:
        await self.close()

    async def reset(self) -> None:
        await self.clear()

    # ------------------------------------------------------------------
    # Foundation — internal helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: MemoryState) -> None:
        object.__setattr__(self, "_state", state)

    def _ensure_open(self) -> None:
        if self._closed:
            raise VectorMemoryClosedError("VectorMemory is closed.")
        if not self._initialized:
            raise VectorMemoryNotInitializedError("VectorMemory is not initialized.")

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _key_to_id(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    def _pack_floats(self, vec: list[float]) -> bytes:
        return struct.pack(f"<{len(vec)}d", *vec)

    def _unpack_floats(self, data: bytes, dim: int | None = None) -> list[float]:
        count = len(data) // 8
        if dim is not None and count != dim:
            raise VectorMemoryValidationError(
                f"Vector dimension mismatch: expected {dim}, got {count}"
            )
        return list(struct.unpack(f"<{count}d", data))

    def _json_dumps(self, obj: Any) -> str:
        return json.dumps(obj, default=str, ensure_ascii=False)

    def _json_loads(self, text: str) -> Any:
        return json.loads(text)

    def _increment_reads(self) -> None:
        self._statistics.reads += 1

    def _increment_writes(self) -> None:
        self._statistics.writes += 1

    def _increment_updates(self) -> None:
        self._statistics.updates += 1

    def _increment_deletes(self) -> None:
        self._statistics.deletes += 1

    def _increment_searches(self) -> None:
        self._statistics.searches += 1

    # ------------------------------------------------------------------
    # 11. Storage Adapter (SQLite via aiosqlite)
    # ------------------------------------------------------------------

    async def _ensure_db(self) -> None:
        if self._db is not None:
            return
        is_file = self._db_path != ":memory:" and not self._db_path.startswith(":")
        if is_file:
            parent = Path(self._db_path).parent
            if parent.exists() is False:
                parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(f"PRAGMA cache_size=-{self._config.db_cache_size_kb}")
        await self._db.execute("PRAGMA foreign_keys=OFF")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.commit()

    async def _init_schema(self) -> None:
        ns = self._config.namespace
        coll = self._config.collection
        await self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS collections (
                name TEXT PRIMARY KEY,
                namespace TEXT NOT NULL DEFAULT '{ns}',
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                collection TEXT NOT NULL DEFAULT '{coll}',
                namespace TEXT NOT NULL DEFAULT '{ns}',
                value_text TEXT,
                value_json TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                embedding_blob BLOB,
                importance REAL NOT NULL DEFAULT 0.5,
                priority TEXT NOT NULL DEFAULT 'normal',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed TEXT,
                parent_key TEXT,
                source TEXT DEFAULT 'runtime',
                UNIQUE(key, collection, namespace)
            )
            """
        )
        await self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                from_key TEXT NOT NULL,
                to_key TEXT NOT NULL,
                relation TEXT NOT NULL,
                namespace TEXT NOT NULL DEFAULT '{ns}',
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                text_hash TEXT PRIMARY KEY,
                embedding_blob BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                key TEXT,
                data_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_collection ON entries(collection, namespace)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_namespace ON entries(namespace)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_tags ON entries(tags)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_key)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_key)"
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # 2. Configuration — runtime access
    # ------------------------------------------------------------------

    def update_config(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)

    # ------------------------------------------------------------------
    # 4. Embedding Engine + 5. Embedding Cache
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        return self._embedder.embed(text)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_batch(texts)

    def _get_embedding(self, text: str) -> list[float]:
        cached = self._embedder.get_cached_embedding(text)
        if cached is not None:
            return cached
        vec = self._embed(text)
        return vec

    def _store_embedding_cache(self, text: str, vector: list[float]) -> None:
        self._embedder.cache_embedding(text, vector)

    # ------------------------------------------------------------------
    # 6. Chunk Manager
    # ------------------------------------------------------------------

    def chunk_text(self, text: str, *, max_size: int | None = None, overlap: int | None = None) -> list[str]:
        max_size = max_size or self._config.chunk_size
        overlap = overlap or self._config.chunk_overlap
        if len(text) <= max_size:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_size
            if end >= len(text):
                chunks.append(text[start:])
                break
            split_at = text.rfind(" ", start, end)
            if split_at <= start:
                split_at = end
            chunks.append(text[start:split_at].strip())
            start = split_at - overlap
            if start < 0:
                start = 0
        return chunks

    # ------------------------------------------------------------------
    # 7. Metadata Builder
    # ------------------------------------------------------------------

    def _build_metadata(
        self,
        *,
        namespace: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        confidence: float | None = None,
        source: str | None = None,
        expires_at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> MemoryMetadata:
        now = self._now()
        return MemoryMetadata(
            namespace=namespace or self._config.namespace,
            tags=tags or [],
            priority=priority or MemoryPriority.NORMAL,
            confidence=confidence if confidence is not None else 1.0,
            source=source or "runtime",
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    # ------------------------------------------------------------------
    # 8. Namespace Manager
    # ------------------------------------------------------------------

    async def create_namespace(self, namespace: str) -> bool:
        self._ensure_open()
        await self.db.execute(
            "INSERT OR IGNORE INTO entries (id, key, collection, namespace, value_text, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._key_to_id(f"__ns__{namespace}"),
                f"__namespace__{namespace}",
                "_meta",
                namespace,
                "",
                self._json_dumps({"_namespace": True}),
                self._now().isoformat(),
                self._now().isoformat(),
            ),
        )
        await self.db.commit()
        await self._emit_event("namespace_created", key=f"__namespace__{namespace}", data={"namespace": namespace})
        return True

    async def delete_namespace(self, namespace: str) -> bool:
        self._ensure_open()
        cursor = await self.db.execute("DELETE FROM entries WHERE namespace = ?", (namespace,))
        await self.db.execute("DELETE FROM edges WHERE namespace = ?", (namespace,))
        await self.db.commit()
        rows = cursor.rowcount
        await self._emit_event("namespace_deleted", key=namespace, data={"namespace": namespace, "rows_deleted": rows})
        return rows > 0

    async def list_namespaces(self) -> list[str]:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT DISTINCT namespace FROM entries WHERE namespace != ?",
            (DEFAULT_NAMESPACE,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows if r[0] != DEFAULT_NAMESPACE]

    # ------------------------------------------------------------------
    # 9. Collection Manager
    # ------------------------------------------------------------------

    async def create_collection(self, name: str, *, namespace: str | None = None) -> bool:
        self._ensure_open()
        ns = namespace or self._config.namespace
        await self.db.execute(
            "INSERT OR IGNORE INTO collections (name, namespace, created_at) VALUES (?, ?, ?)",
            (name, ns, self._now().isoformat()),
        )
        await self.db.commit()
        await self._emit_event("collection_created", key=name, data={"collection": name, "namespace": ns})
        return True

    async def drop_collection(self, name: str, *, namespace: str | None = None) -> bool:
        self._ensure_open()
        ns = namespace or self._config.namespace
        cursor = await self.db.execute(
            "DELETE FROM entries WHERE collection = ? AND namespace = ?",
            (name, ns),
        )
        await self.db.commit()
        rows = cursor.rowcount
        await self._emit_event("collection_dropped", key=name, data={"collection": name, "namespace": ns, "rows_deleted": rows})
        return rows > 0

    async def list_collections(self) -> list[str]:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT DISTINCT name FROM collections WHERE namespace = ?",
            (self._config.namespace,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # 10. Index Manager
    # ------------------------------------------------------------------

    async def rebuild_index(self) -> None:
        self._ensure_open()
        cursor = await self.db.execute("SELECT key, value_text FROM entries")
        rows = await cursor.fetchall()
        for key, value_text in rows:
            if value_text:
                self._embed(value_text)
        await self.db.commit()
        await self._emit_event("index_rebuilt", data={"entries_reindexed": len(rows)})

    # ------------------------------------------------------------------
    # 12. Write Pipeline
    # ------------------------------------------------------------------

    async def put(
        self,
        key: str,
        value: Any,
        *,
        namespace: str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        importance: float = 0.5,
        expires_at: datetime | None = None,
        source: str = "runtime",
        embed: bool = True,
        **kwargs: Any,
    ) -> MemoryEntry[Any]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        now = self._now()
        value_text = str(value) if not isinstance(value, str) else value
        value_json = self._json_dumps(value) if not isinstance(value, str) else None
        metadata = self._build_metadata(
            namespace=ns,
            tags=tags,
            priority=priority,
            source=source,
            expires_at=expires_at,
        )
        embedding: list[float] | None = None
        if embed:
            embedding = self._get_embedding(value_text)
        entry_id = self._key_to_id(key)
        try:
            await self.db.execute(
                """
                INSERT INTO entries
                (id, key, collection, namespace, value_text, value_json, metadata_json, embedding_blob, importance, priority, tags, created_at, updated_at, expires_at, access_count, last_accessed, parent_key, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    key,
                    coll,
                    ns,
                    value_text,
                    value_json,
                    self._json_dumps(asdict(metadata)),
                    self._pack_floats(embedding) if embedding else None,
                    importance,
                    metadata.priority.value if isinstance(metadata.priority, MemoryPriority) else str(metadata.priority),
                    self._json_dumps(metadata.tags),
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                    0,
                    None,
                    None,
                    source,
                ),
            )
            await self.db.commit()
            self._increment_writes()
            self._entry_count += 1
            await self._emit_event("put", key=key, data={"namespace": ns, "collection": coll, "importance": importance})
        except aiosqlite.IntegrityError:
            await self.update(
                key,
                value,
                namespace=ns,
                collection=coll,
                tags=tags,
                priority=priority,
                importance=importance,
                expires_at=expires_at,
                source=source,
                embed=embed,
            )
            cursor = await self.db.execute("SELECT * FROM entries WHERE key = ? AND namespace = ? AND collection = ?", (key, ns, coll))
            row = await cursor.fetchone()
            return self._row_to_entry(row)
        cursor = await self.db.execute("SELECT * FROM entries WHERE key = ? AND namespace = ? AND collection = ?", (key, ns, coll))
        row = await cursor.fetchone()
        return self._row_to_entry(row)

    async def put_batch(self, entries: list[tuple[str, Any]], **kwargs: Any) -> list[MemoryEntry[Any]]:
        results: list[MemoryEntry[Any]] = []
        for key, value in entries:
            result = await self.put(key, value, **kwargs)
            results.append(result)
        return results

    async def update(
        self,
        key: str,
        value: Any,
        *,
        namespace: str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        importance: float | None = None,
        expires_at: datetime | None = None,
        source: str = "runtime",
        embed: bool = True,
        **kwargs: Any,
    ) -> MemoryEntry[Any] | None:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        now = self._now()
        value_text = str(value) if not isinstance(value, str) else value
        value_json = self._json_dumps(value) if not isinstance(value, str) else None
        cursor = await self.db.execute(
            "SELECT id FROM entries WHERE key = ? AND namespace = ? AND collection = ?",
            (key, ns, coll),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        metadata = self._build_metadata(
            namespace=ns,
            tags=tags,
            priority=priority,
            source=source,
            expires_at=expires_at,
        )
        embedding: list[float] | None = None
        if embed:
            embedding = self._get_embedding(value_text)
        await self.db.execute(
            """
            UPDATE entries SET
            value_text=?, value_json=?, metadata_json=?, embedding_blob=?, importance=?, priority=?, tags=?, updated_at=?, expires_at=?, source=?
            WHERE key=? AND namespace=? AND collection=?
            """,
            (
                value_text,
                value_json,
                self._json_dumps(asdict(metadata)),
                self._pack_floats(embedding) if embedding else None,
                importance if importance is not None else 0.5,
                metadata.priority.value if isinstance(metadata.priority, MemoryPriority) else str(metadata.priority),
                self._json_dumps(metadata.tags),
                now.isoformat(),
                expires_at.isoformat() if expires_at else None,
                source,
                key,
                ns,
                coll,
            ),
        )
        await self.db.commit()
        self._increment_updates()
        await self._emit_event("update", key=key, data={"namespace": ns, "collection": coll})
        cursor = await self.db.execute("SELECT * FROM entries WHERE key = ? AND namespace = ? AND collection = ?", (key, ns, coll))
        row = await cursor.fetchone()
        return self._row_to_entry(row)

    async def delete(self, key: str, *, namespace: str | None = None, collection: str | None = None) -> bool:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "DELETE FROM entries WHERE key = ? AND namespace = ? AND collection = ?",
            (key, ns, coll),
        )
        await self.db.execute("DELETE FROM edges WHERE from_key = ? OR to_key = ?", (key, key))
        await self.db.commit()
        rows = cursor.rowcount
        self._increment_deletes()
        self._entry_count = max(0, self._entry_count - rows)
        await self._emit_event("delete", key=key, data={"namespace": ns, "collection": coll, "rows_deleted": rows})
        return rows > 0

    async def clear(self, *, namespace: str | None = None, collection: str | None = None) -> None:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        await self.db.execute("DELETE FROM entries WHERE namespace = ? AND collection = ?", (ns, coll))
        await self.db.execute("DELETE FROM edges WHERE namespace = ?", (ns,))
        await self.db.commit()
        self._entry_count = 0
        await self._emit_event("clear", data={"namespace": ns, "collection": coll})

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(self, key: str, *, namespace: str | None = None, collection: str | None = None) -> MemoryEntry[Any] | None:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE key = ? AND namespace = ? AND collection = ?",
            (key, ns, coll),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        self._increment_reads()
        await self._touch(key, ns, coll)
        return self._row_to_entry(row)

    async def get_batch(self, keys: list[str], *, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        results: list[MemoryEntry[Any]] = []
        for key in keys:
            entry = await self.get(key, namespace=namespace, collection=collection)
            if entry is not None:
                results.append(entry)
        return results

    async def exists(self, key: str, *, namespace: str | None = None, collection: str | None = None) -> bool:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT 1 FROM entries WHERE key = ? AND namespace = ? AND collection = ? LIMIT 1",
            (key, ns, coll),
        )
        row = await cursor.fetchone()
        return row is not None

    async def keys(self, *, namespace: str | None = None, collection: str | None = None) -> list[str]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT key FROM entries WHERE namespace = ? AND collection = ?",
            (ns, coll),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def load(self, key: str) -> MemoryEntry[Any] | None:
        return await self.get(key)

    async def load_many(self, keys: list[str]) -> list[MemoryEntry[Any]]:
        return await self.get_batch(keys)

    async def save(self, key: str, value: Any, **kwargs: Any) -> MemoryEntry[Any]:
        return await self.put(key, value, **kwargs)

    async def load_all(self, *, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? ORDER BY created_at DESC",
            (ns, coll),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def delete_many(self, keys: list[str], *, namespace: str | None = None, collection: str | None = None) -> int:
        count = 0
        for key in keys:
            if await self.delete(key, namespace=namespace, collection=collection):
                count += 1
        return count

    async def save_batch(self, entries: list[tuple[str, Any]], **kwargs: Any) -> list[MemoryEntry[Any]]:
        return await self.put_batch(entries, **kwargs)

    # ------------------------------------------------------------------
    # 13. Search Engine + 14. Similarity Engine + 15. Hybrid Retrieval
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        mode: str = "semantic",
        threshold: float | None = None,
        namespace: str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        min_importance: float = 0.0,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        **kwargs: Any,
    ) -> list[MemorySearchResult[Any]]:
        self._ensure_open()
        self._increment_searches()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        thr = threshold if threshold is not None else self._config.threshold

        if mode == SearchMode.SEMANTIC.value or mode == "semantic":
            results = await self._search_semantic(query, limit=limit, namespace=ns, collection=coll, threshold=thr, tags=tags, priority=priority, min_importance=min_importance, time_from=time_from, time_to=time_to)
        elif mode == SearchMode.EXACT.value or mode == "keyword" or mode == "exact":
            results = await self._search_exact(query, limit=limit, namespace=ns, collection=coll, threshold=thr, tags=tags, priority=priority, min_importance=min_importance, time_from=time_from, time_to=time_to)
        elif mode == SearchMode.HYBRID.value or mode == "hybrid":
            results = await self._search_hybrid(query, limit=limit, namespace=ns, collection=coll, threshold=thr, tags=tags, priority=priority, min_importance=min_importance, time_from=time_from, time_to=time_to)
        else:
            raise ValueError(f"Unknown search mode '{mode}'")

        return results

    async def _search_semantic(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        namespace: str = DEFAULT_NAMESPACE,
        collection: str = DEFAULT_COLLECTION,
        threshold: float = DEFAULT_THRESHOLD,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        min_importance: float = 0.0,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> list[MemorySearchResult[Any]]:
        query_vec = self._embed(query)
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? AND embedding_blob IS NOT NULL",
            (namespace, collection),
        )
        rows = await cursor.fetchall()
        candidates: list[tuple[float, MemoryEntry[Any]]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            if not self._passes_filters(entry, tags=tags, priority=priority, min_importance=min_importance, time_from=time_from, time_to=time_to):
                continue
            stored_vec = self._get_embedding_from_row(row)
            if stored_vec is None:
                continue
            score = cosine_similarity(query_vec, stored_vec)
            if score >= threshold:
                candidates.append((score, entry))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [MemorySearchResult(entry=entry, score=score, distance=1.0 - score) for score, entry in candidates[:limit]]

    async def _search_exact(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        namespace: str = DEFAULT_NAMESPACE,
        collection: str = DEFAULT_COLLECTION,
        threshold: float = DEFAULT_THRESHOLD,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        min_importance: float = 0.0,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> list[MemorySearchResult[Any]]:
        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ?",
            (namespace, collection),
        )
        rows = await cursor.fetchall()
        candidates: list[tuple[float, MemoryEntry[Any]]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            if not self._passes_filters(entry, tags=tags, priority=priority, min_importance=min_importance, time_from=time_from, time_to=time_to):
                continue
            text = entry.value if isinstance(entry.value, str) else str(entry.value)
            text_lower = text.lower()
            text_tokens = set(text_lower.split())
            overlap = query_tokens & text_tokens
            if not overlap:
                continue
            score = len(overlap) / max(len(query_tokens), 1)
            if score >= threshold:
                candidates.append((score, entry))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [MemorySearchResult(entry=entry, score=score, distance=1.0 - score) for score, entry in candidates[:limit]]

    async def _search_hybrid(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        namespace: str = DEFAULT_NAMESPACE,
        collection: str = DEFAULT_COLLECTION,
        threshold: float = DEFAULT_THRESHOLD,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        min_importance: float = 0.0,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> list[MemorySearchResult[Any]]:
        semantic_results = await self._search_semantic(
            query,
            limit=limit * 2,
            namespace=namespace,
            collection=collection,
            threshold=threshold * 0.5,
            tags=tags,
            priority=priority,
            min_importance=min_importance,
            time_from=time_from,
            time_to=time_to,
        )
        exact_results = await self._search_exact(
            query,
            limit=limit * 2,
            namespace=namespace,
            collection=collection,
            threshold=threshold * 0.5,
            tags=tags,
            priority=priority,
            min_importance=min_importance,
            time_from=time_from,
            time_to=time_to,
        )
        seen: set[str] = set()
        merged: list[MemorySearchResult[Any]] = []
        for r in semantic_results + exact_results:
            if r.entry.key in seen:
                continue
            seen.add(r.entry.key)
            merged.append(r)
        merged.sort(key=lambda x: x.score, reverse=True)
        return merged[:limit]

    def _get_embedding_from_row(self, row: tuple) -> list[float] | None:
        embedding_blob = row[7] if len(row) > 7 else None
        if embedding_blob is None:
            return None
        return self._unpack_floats(embedding_blob, dim=self._config.dim)

    def _passes_filters(
        self,
        entry: MemoryEntry[Any],
        *,
        tags: list[str] | None = None,
        priority: MemoryPriority | None = None,
        min_importance: float = 0.0,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> bool:
        if tags:
            entry_tags = entry.metadata.tags if entry.metadata else []
            if not any(t in entry_tags for t in tags):
                return False
        if priority is not None:
            entry_priority = entry.metadata.priority if entry.metadata else MemoryPriority.NORMAL
            if entry_priority != priority:
                return False
        if min_importance > 0.0:
            if getattr(entry, "importance", 0.5) < min_importance:
                return False
        if time_from is not None or time_to is not None:
            created = entry.metadata.created_at if entry.metadata else None
            if created is not None:
                if time_from is not None and created < time_from:
                    return False
                if time_to is not None and created > time_to:
                    return False
        return True

    # ------------------------------------------------------------------
    # 16. Ranking Engine
    # ------------------------------------------------------------------

    def _rank_results(
        self,
        results: list[MemorySearchResult[Any]],
        *,
        query: str | None = None,
        recency_boost: bool = True,
    ) -> list[MemorySearchResult[Any]]:
        scored: list[tuple[float, MemorySearchResult[Any]]] = []
        now = self._now()
        for result in results:
            score = result.score
            if recency_boost:
                score += self._recency_score(result.entry.metadata.created_at, now) * self._config.recency_weight
            score += self._importance_score(result.entry) * self._config.importance_weight
            if query:
                token_overlap = self._token_overlap_score(query, result.entry)
                score += token_overlap * 0.1
            scored.append((score, result))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored]

    def _recency_score(self, created_at: datetime | None, now: datetime) -> float:
        if created_at is None:
            return 0.0
        age_hours = (now - created_at).total_seconds() / 3600.0
        return max(0.0, 1.0 - age_hours / (self._config.max_embedding_age_days * 24.0))

    def _importance_score(self, entry: MemoryEntry[Any]) -> float:
        metadata = entry.metadata
        if metadata is None:
            return 0.5
        priority_map = {
            MemoryPriority.LOW: 0.25,
            MemoryPriority.NORMAL: 0.5,
            MemoryPriority.HIGH: 0.75,
            MemoryPriority.CRITICAL: 1.0,
        }
        return priority_map.get(metadata.priority, 0.5)

    def _token_overlap_score(self, query: str, entry: MemoryEntry[Any]) -> float:
        query_tokens = set(query.lower().split())
        text = str(entry.value) if not isinstance(entry.value, str) else entry.value
        entry_tokens = set(text.lower().split())
        if not query_tokens:
            return 0.0
        return len(query_tokens & entry_tokens) / len(query_tokens)

    # ------------------------------------------------------------------
    # 17. Memory Linking + 18. Graph Relations
    # ------------------------------------------------------------------

    async def link(self, from_key: str, to_key: str, relation: str = "related", *, namespace: str | None = None) -> bool:
        self._ensure_open()
        ns = namespace or self._config.namespace
        edge_id = self._key_to_id(f"edge:{from_key}:{to_key}:{relation}")
        now = self._now().isoformat()
        try:
            await self.db.execute(
                "INSERT INTO edges (id, from_key, to_key, relation, namespace, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (edge_id, from_key, to_key, relation, ns, now),
            )
            await self.db.commit()
            await self._emit_event("link_created", key=from_key, data={"from": from_key, "to": to_key, "relation": relation})
            return True
        except aiosqlite.IntegrityError:
            return False

    async def unlink(self, from_key: str, to_key: str, relation: str | None = None, *, namespace: str | None = None) -> bool:
        self._ensure_open()
        ns = namespace or self._config.namespace
        if relation:
            cursor = await self.db.execute(
                "DELETE FROM edges WHERE from_key = ? AND to_key = ? AND relation = ? AND namespace = ?",
                (from_key, to_key, relation, ns),
            )
        else:
            cursor = await self.db.execute(
                "DELETE FROM edges WHERE from_key = ? AND to_key = ? AND namespace = ?",
                (from_key, to_key, ns),
            )
        await self.db.commit()
        return cursor.rowcount > 0

    async def relations_of(self, key: str, *, namespace: str | None = None, direction: str = "both") -> list[dict[str, Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        results: list[dict[str, Any]] = []
        if direction in ("out", "both"):
            cursor = await self.db.execute(
                "SELECT to_key, relation, created_at FROM edges WHERE from_key = ? AND namespace = ?",
                (key, ns),
            )
            rows = await cursor.fetchall()
            for to_key, relation, created_at in rows:
                results.append({"direction": "out", "to_key": to_key, "relation": relation, "created_at": created_at})
        if direction in ("in", "both"):
            cursor = await self.db.execute(
                "SELECT from_key, relation, created_at FROM edges WHERE to_key = ? AND namespace = ?",
                (key, ns),
            )
            rows = await cursor.fetchall()
            for from_key, relation, created_at in rows:
                results.append({"direction": "in", "from_key": from_key, "relation": relation, "created_at": created_at})
        return results

    async def get_linked(self, key: str, *, relation: str | None = None, namespace: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        edges = await self.relations_of(key, namespace=ns)
        linked_keys: set[str] = set()
        for edge in edges:
            if relation is not None and edge["relation"] != relation:
                continue
            if edge["direction"] == "out":
                linked_keys.add(edge["to_key"])
            else:
                linked_keys.add(edge["from_key"])
        entries: list[MemoryEntry[Any]] = []
        for lk in linked_keys:
            entry = await self.get(lk, namespace=ns)
            if entry is not None:
                entries.append(entry)
        return entries

    async def knowledge_graph(self, *, namespace: str | None = None) -> dict[str, list[dict[str, Any]]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        cursor = await self.db.execute(
            "SELECT from_key, to_key, relation, created_at FROM edges WHERE namespace = ?",
            (ns,),
        )
        rows = await cursor.fetchall()
        graph: dict[str, list[dict[str, Any]]] = {}
        for from_key, to_key, relation, created_at in rows:
            if from_key not in graph:
                graph[from_key] = []
            graph[from_key].append({"to_key": to_key, "relation": relation, "created_at": created_at})
        return graph

    # ------------------------------------------------------------------
    # 19. Context Builder
    # ------------------------------------------------------------------

    async def build_context(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        mode: str = "semantic",
        max_tokens: int = 4096,
        namespace: str | None = None,
        collection: str | None = None,
        format: str = "text",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._ensure_open()
        results = await self.search(
            query,
            limit=limit,
            mode=mode,
            namespace=namespace,
            collection=collection,
            **kwargs,
        )
        blocks: list[str] = []
        total_tokens = 0
        for result in results:
            text = str(result.entry.value) if not isinstance(result.entry.value, str) else result.entry.value
            tokens = self._embedder.token_count(text)
            if total_tokens + tokens > max_tokens and blocks:
                break
            blocks.append(text)
            total_tokens += tokens
        if format == "json":
            return {
                "query": query,
                "results_count": len(results),
                "total_tokens": total_tokens,
                "blocks": [
                    {
                        "key": r.entry.key,
                        "value": str(r.entry.value) if not isinstance(r.entry.value, str) else r.entry.value,
                        "score": r.score,
                        "distance": r.distance,
                        "namespace": r.entry.metadata.namespace,
                        "tags": r.entry.metadata.tags,
                        "priority": r.entry.metadata.priority.value if isinstance(r.entry.metadata.priority, MemoryPriority) else str(r.entry.metadata.priority),
                        "created_at": r.entry.metadata.created_at.isoformat() if isinstance(r.entry.metadata.created_at, datetime) else str(r.entry.metadata.created_at),
                    }
                    for r in results
                ],
            }
        return {
            "query": query,
            "results_count": len(results),
            "total_tokens": total_tokens,
            "context": "\n\n".join(blocks),
            "results": results,
        }

    # ------------------------------------------------------------------
    # 20. Compression + Dedup
    # ------------------------------------------------------------------

    async def deduplicate(self, *, threshold: float | None = None, namespace: str | None = None, collection: str | None = None) -> int:
        self._ensure_open()
        thr = threshold if threshold is not None else self._config.threshold
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ?",
            (ns, coll),
        )
        rows = await cursor.fetchall()
        entries = [self._row_to_entry(r) for r in rows]
        removed = 0
        seen_vectors: list[tuple[list[float], str]] = []
        for entry in entries:
            if isinstance(entry.value, str):
                vec = self._get_embedding(str(entry.value))
            else:
                vec = self._embed(str(entry.value))
            is_dup = False
            for seen_vec, seen_key in seen_vectors:
                score = cosine_similarity(vec, seen_vec)
                if score >= thr:
                    await self.delete(entry.key, namespace=ns, collection=coll)
                    removed += 1
                    is_dup = True
                    break
            if not is_dup:
                seen_vectors.append((vec, entry.key))
        return removed

    async def compact(self) -> None:
        self._ensure_open()
        now = self._now()
        cursor = await self.db.execute(
            "DELETE FROM entries WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now.isoformat(),),
        )
        expired = cursor.rowcount
        deduped = 0
        if self._config.enable_dedup:
            deduped = await self.deduplicate()
        await self.db.commit()
        self._last_compact = now
        await self._emit_event("compacted", data={"expired_removed": expired, "dedup_removed": deduped})

    # ------------------------------------------------------------------
    # 21. Promotion + 22. Consolidation
    # ------------------------------------------------------------------

    async def promote(self, key: str, *, amount: float = 0.2, namespace: str | None = None, collection: str | None = None) -> MemoryEntry[Any] | None:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE key = ? AND namespace = ? AND collection = ?",
            (key, ns, coll),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        current_importance = row[8] if len(row) > 8 else 0.5
        new_importance = min(1.0, current_importance + amount)
        await self.db.execute(
            "UPDATE entries SET importance = ?, updated_at = ? WHERE key = ? AND namespace = ? AND collection = ?",
            (new_importance, self._now().isoformat(), key, ns, coll),
        )
        await self.db.commit()
        await self._emit_event("promoted", key=key, data={"importance": new_importance})
        return await self.get(key, namespace=ns, collection=coll)

    async def decay(self, key: str, *, half_life_hours: float | None = None, namespace: str | None = None, collection: str | None = None) -> MemoryEntry[Any] | None:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE key = ? AND namespace = ? AND collection = ?",
            (key, ns, coll),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        current_importance = row[8] if len(row) > 8 else 0.5
        half_life = half_life_hours or self._config.decay_half_life_hours
        cursor2 = await self.db.execute(
            "SELECT created_at FROM entries WHERE key = ? AND namespace = ? AND collection = ?",
            (key, ns, coll),
        )
        row2 = await cursor2.fetchone()
        if row2 and row2[0]:
            created = datetime.fromisoformat(row2[0])
            age_hours = (self._now() - created).total_seconds() / 3600.0
            decay_factor = 0.5 ** (age_hours / half_life)
            new_importance = current_importance * decay_factor
        else:
            new_importance = current_importance * 0.9
        new_importance = max(0.0, min(1.0, new_importance))
        await self.db.execute(
            "UPDATE entries SET importance = ?, updated_at = ? WHERE key = ? AND namespace = ? AND collection = ?",
            (new_importance, self._now().isoformat(), key, ns, coll),
        )
        await self.db.commit()
        await self._emit_event("decayed", key=key, data={"importance": new_importance})
        return await self.get(key, namespace=ns, collection=coll)

    async def consolidate(self, *, threshold: float | None = None, namespace: str | None = None, collection: str | None = None) -> int:
        self._ensure_open()
        thr = threshold if threshold is not None else self._config.threshold
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ?",
            (ns, coll),
        )
        rows = await cursor.fetchall()
        entries = [self._row_to_entry(r) for r in rows]
        merged = 0
        groups: dict[str, list[MemoryEntry[Any]]] = {}
        for entry in entries:
            if isinstance(entry.value, str):
                vec = self._get_embedding(str(entry.value))
            else:
                vec = self._embed(str(entry.value))
            found_group = False
            for group_key, group_entries in groups.items():
                rep_entry = group_entries[0]
                rep_vec = self._get_embedding(str(rep_entry.value)) if isinstance(rep_entry.value, str) else self._embed(str(rep_entry.value))
                score = cosine_similarity(vec, rep_vec)
                if score >= thr:
                    group_entries.append(entry)
                    found_group = True
                    break
            if not found_group:
                groups[entry.key] = [entry]
        for group_key, group_entries in groups.items():
            if len(group_entries) <= 1:
                continue
            representative = max(group_entries, key=lambda e: e.metadata.priority.value if isinstance(e.metadata.priority, MemoryPriority) else 0)
            for duplicate in group_entries:
                if duplicate.key != representative.key:
                    await self.delete(duplicate.key, namespace=ns, collection=coll)
                    merged += 1
        await self._emit_event("consolidated", data={"groups": len(groups), "merged": merged})
        return merged

    # ------------------------------------------------------------------
    # 23. Synchronization + Snapshot/Backup
    # ------------------------------------------------------------------

    async def synchronize(self) -> None:
        self._ensure_open()
        await self.db.commit()
        await self._emit_event("synchronized", data={"timestamp": self._now().isoformat()})

    async def snapshot(self) -> dict[str, Any]:
        self._ensure_open()
        now = self._now()
        self._last_snapshot = now
        return {
            "timestamp": now.isoformat(),
            "namespace": self._config.namespace,
            "collection": self._config.collection,
            "entries_count": self._entry_count,
            "edges_count": await self._edge_count(),
            "embedding_cache_size": self._embedder.cache_size,
            "config": asdict(self._config),
        }

    async def backup(self, path: str) -> bool:
        self._ensure_open()
        backup_path = Path(path)
        if backup_path.is_dir():
            backup_path = backup_path / f"vector_memory_backup_{self._now().strftime('%Y%m%d_%H%M%S')}.db"
        if self._db_path != ":memory:":
            shutil.copy2(self._db_path, str(backup_path))
        else:
            export_data = await self.export()
            with open(str(backup_path), "w") as f:
                json.dump(export_data, f, default=str, indent=2)
        self._last_backup = self._now()
        await self._emit_event("backup_created", data={"path": str(backup_path)})
        return True

    async def restore(self, path: str) -> bool:
        self._ensure_open()
        backup_path = Path(path)
        if not backup_path.exists():
            raise VectorMemoryNotFoundError(f"Backup file not found: {path}")
        if self._db_path != ":memory:":
            await self.close()
            shutil.copy2(str(backup_path), self._db_path)
            await self._ensure_db()
            await self._init_schema()
        else:
            with open(str(backup_path), "r") as f:
                data = json.load(f)
            await self.clear()
            for entry_data in data.get("entries", []):
                await self.put(
                    entry_data["key"],
                    entry_data.get("value_text") or entry_data.get("value_json"),
                    namespace=entry_data.get("namespace", self._config.namespace),
                    collection=entry_data.get("collection", self._config.collection),
                    tags=entry_data.get("tags", []),
                    importance=entry_data.get("importance", 0.5),
                )
        await self._emit_event("restored", data={"path": str(backup_path)})
        return True

    async def export_json(self, path: str) -> bool:
        self._ensure_open()
        data = await self.export()
        with open(path, "w") as f:
            json.dump(data, f, default=str, indent=2)
        return True

    async def import_json(self, path: str) -> int:
        self._ensure_open()
        with open(path, "r") as f:
            data = json.load(f)
        count = 0
        for entry_data in data.get("entries", []):
            await self.put(
                entry_data["key"],
                entry_data.get("value_text") or entry_data.get("value_json"),
                namespace=entry_data.get("namespace", self._config.namespace),
                collection=entry_data.get("collection", self._config.collection),
                tags=entry_data.get("tags", []),
                importance=entry_data.get("importance", 0.5),
            )
            count += 1
        return count

    # ------------------------------------------------------------------
    # Override BaseMemory export/import/snapshot/compact/synchronize
    # ------------------------------------------------------------------

    async def export(self) -> dict[str, Any]:
        entries = await self.load_all()
        edges = await self._get_all_edges()
        return {
            "id": str(self.identifier),
            "namespace": self._config.namespace,
            "collection": self._config.collection,
            "state": self._state.value,
            "entries_count": len(entries),
            "edges_count": len(edges),
            "created_at": self._created_at.isoformat() if isinstance(self._created_at, datetime) else str(self._created_at),
            "last_accessed": self._last_accessed.isoformat() if isinstance(self._last_accessed, datetime) else str(self._last_accessed),
            "entries": [
                {
                    "key": e.key,
                    "value_text": e.value if isinstance(e.value, str) else None,
                    "value_json": self._json_dumps(e.value) if not isinstance(e.value, str) else None,
                    "namespace": e.metadata.namespace,
                    "tags": e.metadata.tags,
                    "priority": e.metadata.priority.value if isinstance(e.metadata.priority, MemoryPriority) else str(e.metadata.priority),
                    "importance": getattr(e, "importance", 0.5),
                    "created_at": e.metadata.created_at.isoformat() if isinstance(e.metadata.created_at, datetime) else str(e.metadata.created_at),
                    "expires_at": e.metadata.expires_at.isoformat() if e.metadata.expires_at else None,
                }
                for e in entries
            ],
            "edges": [
                {
                    "from_key": e["from_key"],
                    "to_key": e["to_key"],
                    "relation": e["relation"],
                }
                for e in edges
            ],
        }

    async def import_data(self, data: dict[str, Any]) -> int:
        count = 0
        for entry_data in data.get("entries", []):
            await self.put(
                entry_data["key"],
                entry_data.get("value_text") or entry_data.get("value_json"),
                namespace=entry_data.get("namespace", self._config.namespace),
                collection=entry_data.get("collection", self._config.collection),
                tags=entry_data.get("tags", []),
                importance=entry_data.get("importance", 0.5),
            )
            count += 1
        return count

    # ------------------------------------------------------------------
    # 24. Health + Metrics
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if not self._closed else "closed",
            "id": str(self.identifier),
            "namespace": self._config.namespace,
            "collection": self._config.collection,
            "initialized": self._initialized,
            "closed": self._closed,
            "entries": self._entry_count,
            "embedding_cache": self._embedder.cache_size,
            "db_path": self._db_path,
            "dim": self._config.dim,
            "threshold": self._config.threshold,
            "last_snapshot": self._last_snapshot.isoformat() if self._last_snapshot else None,
            "last_compact": self._last_compact.isoformat() if self._last_compact else None,
            "last_backup": self._last_backup.isoformat() if self._last_backup else None,
        }

    def metrics(self) -> dict[str, Any]:
        stats = self._statistics
        embed_stats = self._embedder.stats()
        return {
            "entries": self._entry_count,
            "reads": stats.reads,
            "writes": stats.writes,
            "updates": stats.updates,
            "deletes": stats.deletes,
            "searches": stats.searches,
            "cache_hits": embed_stats.get("hits", 0),
            "cache_misses": embed_stats.get("misses", 0),
            "cache_hit_rate": embed_stats.get("hit_rate", 0.0),
            "embedding_dim": self._config.dim,
            "threshold": self._config.threshold,
            "events_emitted": self._event_count,
            "listeners_active": sum(len(v) for v in self._listeners.values()),
        }

    # ------------------------------------------------------------------
    # 25. Events + Lifecycle
    # ------------------------------------------------------------------

    def on(self, event_type: str, listener: Callable[..., Any]) -> None:
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        if len(self._listeners[event_type]) >= self._config.max_event_listeners:
            self._listeners[event_type].pop(0)
        self._listeners[event_type].append(listener)

    def off(self, event_type: str, listener: Callable[..., Any]) -> None:
        if event_type in self._listeners:
            try:
                self._listeners[event_type].remove(listener)
            except ValueError:
                pass

    def off_all(self, event_type: str | None = None) -> None:
        if event_type is None:
            self._listeners.clear()
        elif event_type in self._listeners:
            self._listeners[event_type].clear()

    async def _emit_event(self, event_type: str, *, key: str | None = None, data: dict[str, Any] | None = None) -> None:
        if not self._config.enable_events:
            return
        self._event_count += 1
        if event_type in self._listeners:
            for listener in self._listeners[event_type]:
                try:
                    if asyncio.iscoroutinefunction(listener):
                        await listener(event_type, key=key, data=data)
                    else:
                        listener(event_type, key=key, data=data)
                except Exception:
                    pass
        if self._db is not None:
            try:
                await self.db.execute(
                    "INSERT INTO events (id, event_type, key, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        self._key_to_id(f"evt:{event_type}:{key or ''}:{time.time()}"),
                        event_type,
                        key,
                        self._json_dumps(data) if data else None,
                        self._now().isoformat(),
                    ),
                )
                await self.db.commit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_entry(self, row: tuple) -> MemoryEntry[Any]:
        metadata_json = row[6] if len(row) > 6 else "{}"
        try:
            metadata_dict = self._json_loads(metadata_json)
            metadata = MemoryMetadata(
                namespace=metadata_dict.get("namespace", DEFAULT_NAMESPACE),
                source=metadata_dict.get("source", "runtime"),
                tags=metadata_dict.get("tags", []),
                confidence=metadata_dict.get("confidence", 1.0),
                priority=MemoryPriority(metadata_dict.get("priority", "normal")) if metadata_dict.get("priority") in ("low", "normal", "high", "critical") else MemoryPriority.NORMAL,
                created_at=datetime.fromisoformat(metadata_dict.get("created_at", datetime.now(timezone.utc).isoformat())) if metadata_dict.get("created_at") else datetime.now(timezone.utc),
                updated_at=datetime.fromisoformat(metadata_dict.get("updated_at", datetime.now(timezone.utc).isoformat())) if metadata_dict.get("updated_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(metadata_dict.get("expires_at")) if metadata_dict.get("expires_at") else None,
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            metadata = MemoryMetadata()

        value_text = row[4] if len(row) > 4 else None
        value_json = row[5] if len(row) > 5 else None
        if value_text is not None:
            value: Any = value_text
        elif value_json is not None:
            try:
                value = self._json_loads(value_json)
            except (json.JSONDecodeError, TypeError):
                value = value_json or ""
        else:
            value = ""

        return MemoryEntry(
            key=row[1],
            value=value,
            metadata=metadata,
            identifier=uuid.UUID(row[0]) if len(row) > 0 and row[0] else uuid.uuid4(),
        )

    async def _touch(self, key: str, namespace: str, collection: str) -> None:
        await self.db.execute(
            "UPDATE entries SET access_count = access_count + 1, last_accessed = ? WHERE key = ? AND namespace = ? AND collection = ?",
            (self._now().isoformat(), key, namespace, collection),
        )
        await self.db.commit()

    async def _count_entries(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM entries")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count(self) -> int:
        return await self._count_entries()

    async def _edge_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM edges")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _get_all_edges(self) -> list[dict[str, Any]]:
        cursor = await self.db.execute("SELECT from_key, to_key, relation, created_at FROM edges")
        rows = await cursor.fetchall()
        return [{"from_key": r[0], "to_key": r[1], "relation": r[2], "created_at": r[3]} for r in rows]

    # ------------------------------------------------------------------
    # Additional read operations (BaseMemory contract)
    # ------------------------------------------------------------------

    async def search_by_metadata(self, metadata_filter: dict[str, Any], *, limit: int = DEFAULT_LIMIT, namespace: str | None = None, collection: str | None = None) -> list[MemorySearchResult[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ?",
            (ns, coll),
        )
        rows = await cursor.fetchall()
        results: list[MemorySearchResult[Any]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            match = True
            for k, v in metadata_filter.items():
                entry_metadata = entry.metadata
                if k == "namespace" and entry_metadata.namespace != v:
                    match = False
                    break
                if k == "collection" and entry_metadata.collection != v:
                    match = False
                    break
                if k == "priority" and str(entry_metadata.priority) != str(v):
                    match = False
                    break
                if k == "source" and entry_metadata.source != v:
                    match = False
                    break
                if k == "tags" and not any(t in entry_metadata.tags for t in (v if isinstance(v, list) else [v])):
                    match = False
                    break
            if match:
                results.append(MemorySearchResult(entry=entry, score=1.0, distance=0.0))
        return results[:limit]

    async def entity_search(self, entity_key: str, *, namespace: str | None = None, collection: str | None = None) -> list[MemorySearchResult[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? AND (key LIKE ? OR value_text LIKE ?)",
            (ns, coll, f"%{entity_key}%", f"%{entity_key}%"),
        )
        rows = await cursor.fetchall()
        results: list[MemorySearchResult[Any]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            results.append(MemorySearchResult(entry=entry, score=0.5, distance=None))
        return results

    async def recent_entries(self, *, limit: int = 10, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? ORDER BY created_at DESC LIMIT ?",
            (ns, coll, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def top_entries(self, *, limit: int = 10, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? ORDER BY importance DESC LIMIT ?",
            (ns, coll, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def active_entries(self, *, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        now = self._now().isoformat()
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? AND (expires_at IS NULL OR expires_at > ?)",
            (ns, coll, now),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def expired_entries(self, *, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        now = self._now().isoformat()
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ? AND expires_at IS NOT NULL AND expires_at <= ?",
            (ns, coll, now),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def purge_expired(self, *, namespace: str | None = None, collection: str | None = None) -> int:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        now = self._now().isoformat()
        cursor = await self.db.execute(
            "DELETE FROM entries WHERE namespace = ? AND collection = ? AND expires_at IS NOT NULL AND expires_at <= ?",
            (ns, coll, now),
        )
        await self.db.commit()
        return cursor.rowcount

    async def filter_entries(self, predicate: Callable[[MemoryEntry[Any]], bool], *, namespace: str | None = None, collection: str | None = None) -> list[MemoryEntry[Any]]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        coll = collection or self._config.collection
        cursor = await self.db.execute(
            "SELECT * FROM entries WHERE namespace = ? AND collection = ?",
            (ns, coll),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows if predicate(self._row_to_entry(r))]

    async def _validate_key(self, key: str) -> None:
        if not key or not isinstance(key, str):
            raise VectorMemoryValidationError("Key must be a non-empty string")

    async def _validate_entry(self, entry: MemoryEntry[Any]) -> None:
        if entry.key is None or not isinstance(entry.key, str):
            raise VectorMemoryValidationError("Entry key must be a non-empty string")

    async def validate(self) -> dict[str, Any]:
        self._ensure_open()
        total = self._entry_count
        without_embedding = 0
        without_metadata = 0
        cursor = await self.db.execute("SELECT * FROM entries")
        rows = await cursor.fetchall()
        for row in rows:
            if row[7] is None:
                without_embedding += 1
            metadata_json = row[6] if len(row) > 6 else "{}"
            try:
                meta = self._json_loads(metadata_json)
                if not meta.get("namespace"):
                    without_metadata += 1
            except (json.JSONDecodeError, TypeError):
                without_metadata += 1
        return {
            "total_entries": total,
            "entries_with_embedding": total - without_embedding,
            "entries_without_embedding": without_embedding,
            "entries_with_metadata": total - without_metadata,
            "entries_without_metadata": without_metadata,
            "healthy": without_embedding == 0 and without_metadata == 0,
        }

    async def ping(self) -> bool:
        self._ensure_open()
        cursor = await self.db.execute("SELECT 1")
        row = await cursor.fetchone()
        return row is not None and row[0] == 1

    async def reset_metrics(self) -> None:
        self._statistics = MemoryStatistics()
        self._embedder.clear_cache()
        await self._emit_event("metrics_reset", data={})

    # ------------------------------------------------------------------
    # Hook overrides
    # ------------------------------------------------------------------

    async def before_create(self, entry: MemoryEntry[Any] | None) -> None:
        pass

    async def after_create(self, entry: MemoryEntry[Any] | None) -> None:
        pass

    async def after_read(self, entry: MemoryEntry[Any] | None) -> None:
        pass

    async def after_update(self, entry: MemoryEntry[Any] | None) -> None:
        pass

    async def after_delete(self, entry: MemoryEntry[Any] | None) -> None:
        pass

    async def after_search(self, entry: MemoryEntry[Any] | None) -> None:
        pass

    def remove_hook(self, hook: Callable[..., Any]) -> None:
        if hook in self._hooks:
            self._hooks.remove(hook)

    def clear_hooks(self) -> None:
        self._hooks.clear()

    def hook_count(self) -> int:
        return len(self._hooks)

    def audit_record(self, operation: MemoryOperation, entry: MemoryEntry[Any] | None) -> None:
        pass

    async def serialize(self, entry: MemoryEntry[Any]) -> bytes:
        return self._json_dumps(asdict(entry)).encode("utf-8")

    async def deserialize(self, data: bytes) -> MemoryEntry[Any]:
        obj = json.loads(data.decode("utf-8"))
        return MemoryEntry(
            key=obj["key"],
            value=obj.get("value_text") or obj.get("value_json"),
            metadata=MemoryMetadata(
                namespace=obj.get("namespace", DEFAULT_NAMESPACE),
                source=obj.get("source", "runtime"),
                tags=obj.get("tags", []),
                confidence=obj.get("confidence", 1.0),
                priority=MemoryPriority(obj.get("priority", "normal")) if obj.get("priority") in ("low", "normal", "high", "critical") else MemoryPriority.NORMAL,
                created_at=datetime.fromisoformat(obj["created_at"]) if obj.get("created_at") else datetime.now(timezone.utc),
                updated_at=datetime.fromisoformat(obj["updated_at"]) if obj.get("updated_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(obj["expires_at"]) if obj.get("expires_at") else None,
            ),
        )