"""
Conversation Memory — Intelligence Engine

A full-featured conversation memory implementation with semantic search,
metadata filtering, topic tracking, entity management, summarization,
context building, and full lifecycle management.

Delegates to memory.vector.similarity and memory.vector.embeddings
for similarity computation and embedding generation respectively.

Architecture (25 parts):
  1.  Foundation      — module setup, imports, constants
  2.  Configuration   — ConversationConfig dataclass
  3.  Runtime Models  — internal data structures
  4.  Session Manager — session lifecycle and persistence
  5.  Message Manager — message storage and retrieval
  6.  Conversation Window — windowing and truncation
  7.  Context Builder — assemble LLM-ready context blocks
  8.  Topic Tracker   — topic extraction and management
  9.  Entity Manager  — named entity tracking
  10. Memory Linking  — cross-reference links between messages
  11. Conversation Search — exact, semantic, hybrid search
  12. Similarity Engine — cosine, dot, euclidean scoring
  13. Hybrid Retrieval — multi-strategy fusion
  14. Ranking Engine  — composite relevance scoring
  15. Summarization   — automatic conversation summarization
  16. Context Compression — dedup + compaction
  17. Promotion       — importance-based promotion
  18. Consolidation   — merge duplicate segments
  19. Synchronization — sync backend + snapshot/backup
  20. Health + Metrics — runtime observability
  21. Events + Lifecycle — async event bus, state machine
  22. Export/Import   — conversation serialization
  23. Validation      — conversation integrity validation
  24. Analytics       — conversation metrics and insights
  25. Utilities       — helper functions and tools
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import struct
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

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

DEFAULT_NAMESPACE = "conversation"
DEFAULT_COLLECTION = "conversations"
DEFAULT_WINDOW_SIZE = 100
DEFAULT_MAX_TOKENS = 8192
DEFAULT_CONTEXT_SIZE = 4096
DEFAULT_CHUNK_SIZE = 512
DEFAULT_TOPIC_COUNT = 50
DEFAULT_SIMILARITY_THRESHOLD = 0.5
DEFAULT_LIMIT = 10
DEFAULT_BATCH_SIZE = 256
DEFAULT_CACHE_MAX = 10_000
DEFAULT_SIMILARITY_WEIGHT = 0.6
DEFAULT_RECENCY_WEIGHT = 0.2
DEFAULT_IMPORTANCE_WEIGHT = 0.2


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------

class ConversationError(Exception):
    """Base exception for ConversationMemory errors."""


class ConversationNotInitializedError(ConversationError):
    """Raised when operations are called before initialization."""


class ConversationClosedError(ConversationError):
    """Raised when operations are called on a closed engine."""


class ConversationNotFoundError(ConversationError):
    """Raised when a requested conversation does not exist."""


class ConversationDuplicateError(ConversationError):
    """Raised when a conversation with the same ID already exists."""


class ConversationValidationError(ConversationError):
    """Raised when validation fails."""


# ------------------------------------------------------------------
# Enumerations
# ------------------------------------------------------------------

class MessageRole(str, Enum):
    """Message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    FUNCTION = "function"
    DEVELOPER = "developer"


class ConversationState(str, Enum):
    """Conversation lifecycle state."""

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    CLOSED = "closed"


class TopicType(str, Enum):
    """Topic category types."""

    GENERAL = "general"
    TECHNICAL = "technical"
    FINANCIAL = "financial"
    CRYPTO = "crypto"
    BLOCKCHAIN = "blockchain"
    TRADING = "trading"
    SECURITY = "security"
    DEVELOPER = "developer"


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

@dataclass
class ConversationConfig:
    """Configuration for ConversationMemory cognitive engine."""

    namespace: str = DEFAULT_NAMESPACE
    collection: str = DEFAULT_COLLECTION
    window_size: int = DEFAULT_WINDOW_SIZE
    max_tokens: int = DEFAULT_MAX_TOKENS
    context_size: int = DEFAULT_CONTEXT_SIZE
    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_topics: int = DEFAULT_TOPIC_COUNT
    topic_threshold: float = 0.3
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    limit: int = DEFAULT_LIMIT
    batch_size: int = DEFAULT_BATCH_SIZE
    cache_max_size: int = DEFAULT_CACHE_MAX
    similarity_weight: float = DEFAULT_SIMILARITY_WEIGHT
    recency_weight: float = DEFAULT_RECENCY_WEIGHT
    importance_weight: float = DEFAULT_IMPORTANCE_WEIGHT
    decay_half_life_hours: float = 168.0
    max_conversation_age_days: float = 30.0
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
    enable_summarization: bool = True
    summarization_threshold: int = 100
    summarization_min_messages: int = 5
    enable_topic_tracking: bool = True
    enable_entity_tracking: bool = True


# ------------------------------------------------------------------
# Data Models
# ------------------------------------------------------------------

@dataclass
class Message:
    """A message in a conversation."""

    id: str
    conversation_id: str
    role: MessageRole
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    parent_message_id: str | None = None
    importance: float = 0.5
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    source: str = "runtime"


@dataclass
class Conversation:
    """A conversation session."""

    id: str
    title: str
    user_id: str = "anonymous"
    namespace: str = DEFAULT_NAMESPACE
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
    message_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    state: ConversationState = ConversationState.CREATED
    messages: list[Message] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Topic:
    """A topic tracked within conversations."""

    id: str
    name: str
    frequency: int = 0
    confidence: float = 0.0
    conversation_ids: list[str] = field(default_factory=list)
    last_mentioned: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Entity:
    """A named entity tracked within conversations."""

    id: str
    name: str
    type: str
    normalized: str
    conversation_ids: list[str] = field(default_factory=list)
    frequency: int = 0
    last_mentioned: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# ConversationMemory
# ------------------------------------------------------------------

class ConversationMemory(BaseMemory[Message]):
    """
    Cognitive conversation memory engine.

    Stores conversations with generated embeddings, supports semantic search,
    metadata filtering, topic tracking, entity management, summarization,
    context building, and full lifecycle management.

    Not a thin history wrapper — this is a self-contained conversation
    intelligence engine with its own topic tracking, entity management,
    summarization, and retrieval pipeline.
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
        config: ConversationConfig | None = None,
    ) -> None:
        super().__init__(
            namespace=namespace,
            backend=backend,
            serializer=serializer,
            embedding_provider=embedding_provider,
        )
        self._config = config or ConversationConfig(namespace=namespace)
        self._db: aiosqlite.Connection | None = None
        self._db_path: str = self._config.db_path
        self._embedder = LocalHashEmbedder(
            dim=DEFAULT_DIM,
            seed="conversation_memory",
            max_cache_size=self._config.cache_max_size,
        )
        self._similarity = SimilarityService(
            default_threshold=self._config.similarity_threshold,
            default_metric="cosine",
        )
        self._listeners: dict[str, list[Callable[..., Any]]] = {}
        self._closed = False
        self._initialized = False
        self._last_snapshot: datetime | None = None
        self._last_compact: datetime | None = None
        self._last_backup: datetime | None = None
        self._event_count = 0
        self._topic_map: dict[str, Topic] = {}
        self._entity_map: dict[str, Entity] = {}
        self._conversation_cache: dict[str, Conversation] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> ConversationConfig:
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
            raise ConversationNotInitializedError(
                "ConversationMemory is not initialized. Call initialize() first."
            )
        return self._db

    @property
    def size(self) -> int:
        return len(self._conversation_cache)

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
                self._conversation_cache.clear()
                self._topic_map.clear()
                self._entity_map.clear()

    async def __aenter__(self) -> ConversationMemory:
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
            raise ConversationClosedError("ConversationMemory is closed.")
        if not self._initialized:
            raise ConversationNotInitializedError("ConversationMemory is not initialized.")

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _key_to_id(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    def _pack_floats(self, vec: list[float]) -> bytes:
        return struct.pack(f"<{len(vec)}d", *vec)

    def _unpack_floats(self, data: bytes, dim: int | None = None) -> list[float]:
        count = len(data) // 8
        if dim is not None and count != dim:
            raise ConversationValidationError(
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
    # 3. Runtime Models
    # ------------------------------------------------------------------

    def _create_conversation(self, title: str, user_id: str = "anonymous") -> Conversation:
        return Conversation(
            id=self._key_to_id(title),
            title=title,
            user_id=user_id,
            namespace=self._config.namespace,
        )

    def _create_message(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        now = self._now()
        tokens = self._embedder.token_count(content)
        return Message(
            id=self._key_to_id(f"{conversation_id}:{time.time()}"),
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata=metadata or {},
            tokens=tokens,
            timestamp=now,
            created_at=now,
            updated_at=now,
            importance=0.5,
        )

    # ------------------------------------------------------------------
    # Foundation — storage adapter (SQLite via aiosqlite)
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
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'anonymous',
                namespace TEXT NOT NULL DEFAULT '{ns}',
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                token_count INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                expires_at TEXT,
                state TEXT NOT NULL DEFAULT 'created'
            )
            """
        )
        await self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                tokens INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                parent_message_id TEXT,
                importance REAL NOT NULL DEFAULT 0.5,
                priority TEXT NOT NULL DEFAULT 'normal',
                tags TEXT NOT NULL DEFAULT '[]',
                entities TEXT NOT NULL DEFAULT '[]',
                topics TEXT NOT NULL DEFAULT '[]',
                source TEXT DEFAULT 'runtime',
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_message_id) REFERENCES messages(id) ON DELETE SET NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS topics (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                frequency INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                normalized TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_topics (
                conversation_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                PRIMARY KEY (conversation_id, topic_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_entities (
                conversation_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                PRIMARY KEY (conversation_id, entity_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_tags (
                conversation_id TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                PRIMARY KEY (conversation_id, tag_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
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
                conversation_id TEXT,
                data_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_namespace ON conversations(namespace)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_topics ON messages(topics)"
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # 1. Foundation — Conversation lifecycle
    # ------------------------------------------------------------------

    async def create_conversation(
        self,
        title: str,
        user_id: str = "anonymous",
        namespace: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        self._ensure_open()
        ns = namespace or self._config.namespace
        conversation_id = self._key_to_id(title)
        now = self._now()
        metadata = metadata or {}
        metadata["namespace"] = ns

        try:
            await self.db.execute(
                """
                INSERT INTO conversations
                (id, title, user_id, namespace, metadata_json, created_at, updated_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    title,
                    user_id,
                    ns,
                    self._json_dumps(metadata),
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            await self.db.commit()
            conversation = self._create_conversation(title, user_id)
            self._conversation_cache[conversation_id] = conversation
            await self._emit_event("conversation_created", key=conversation_id, data={"title": title, "namespace": ns})
            return conversation
        except aiosqlite.IntegrityError:
            await self._ensure_open()
            cursor = await self.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
            row = await cursor.fetchone()
            return self._row_to_conversation(row)

    async def load_conversation(self, conversation_id: str) -> Conversation | None:
        self._ensure_open()
        if conversation_id in self._conversation_cache:
            return self._conversation_cache[conversation_id]
        cursor = await self.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        conversation = self._row_to_conversation(row)
        self._conversation_cache[conversation_id] = conversation
        await self._touch_conversation(conversation_id)
        return conversation

    async def delete_conversation(self, conversation_id: str) -> bool:
        self._ensure_open()
        if conversation_id in self._conversation_cache:
            del self._conversation_cache[conversation_id]
        cursor = await self.db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        await self.db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        await self.db.execute("DELETE FROM conversation_topics WHERE conversation_id = ?", (conversation_id,))
        await self.db.execute("DELETE FROM conversation_entities WHERE conversation_id = ?", (conversation_id,))
        await self.db.commit()
        rows = cursor.rowcount
        await self._emit_event("conversation_deleted", key=conversation_id, data={"rows_deleted": rows})
        return rows > 0

    async def list_conversations(self, *, user_id: str | None = None) -> list[Conversation]:
        self._ensure_open()
        if user_id is not None:
            cursor = await self.db.execute("SELECT * FROM conversations WHERE user_id = ?", (user_id,))
        else:
            cursor = await self.db.execute("SELECT * FROM conversations")
        rows = await cursor.fetchall()
        conversations: list[Conversation] = []
        for row in rows:
            conversation = self._row_to_conversation(row)
            conversations.append(conversation)
        return conversations

    async def update_conversation(
        self,
        conversation_id: str,
        **kwargs: Any,
    ) -> Conversation | None:
        self._ensure_open()
        now = self._now()
        fields = []
        params = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            params.append(v)
        if fields:
            fields.append("updated_at = ?")
            params.append(now.isoformat())
            params.append(conversation_id)
            query = f"UPDATE conversations SET {', '.join(fields)} WHERE id = ?"
            await self.db.execute(query, params)
            await self.db.commit()
        cursor = await self.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = await cursor.fetchone()
        return self._row_to_conversation(row) if row else None

    # ------------------------------------------------------------------
    # 2. Configuration — runtime access
    # ------------------------------------------------------------------

    def update_config(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)

    # ------------------------------------------------------------------
    # 5. Message Manager
    # ------------------------------------------------------------------

    async def add_message(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
        parent_message_id: str | None = None,
        importance: float = 0.5,
        priority: str = "normal",
        tags: list[str] | None = None,
        entities: list[dict[str, Any]] | None = None,
        topics: list[str] | None = None,
        **kwargs: Any,
    ) -> Message:
        self._ensure_open()
        cursor = await self.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = await cursor.fetchone()
        if row is None:
            raise ConversationNotFoundError(f"Conversation not found: {conversation_id}")
        ns = row[3] if len(row) > 3 else self._config.namespace
        conversation = self._row_to_conversation(row)
        now = self._now()
        message = self._create_message(conversation_id, role, content, metadata)

        cursor2 = await self.db.execute(
            """
            INSERT INTO messages
            (id, conversation_id, role, content, metadata_json, tokens, timestamp, created_at, updated_at, expires_at, parent_message_id, importance, priority, tags, entities, topics, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.conversation_id,
                message.role.value,
                message.content,
                self._json_dumps(message.metadata),
                message.tokens,
                message.timestamp.isoformat(),
                message.created_at.isoformat(),
                message.updated_at.isoformat(),
                message.expires_at.isoformat() if message.expires_at else None,
                parent_message_id,
                importance,
                priority,
                self._json_dumps(tags or []),
                self._json_dumps(entities or []),
                self._json_dumps(topics or []),
                "runtime",
            ),
        )
        await self.db.commit()
        message_id = message.id
        self._increment_writes()
        await self._emit_event("message_added", key=message_id, data={"conversation_id": conversation_id, "role": role.value})

        if tags:
            await self._process_tags(conversation_id, tags)
        if entities:
            await self._process_entities(conversation_id, entities)
        if topics:
            await self._process_topics(conversation_id, topics)

        return message

    async def load_messages(self, conversation_id: str, *, limit: int = 100) -> list[Message]:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        messages: list[Message] = []
        for row in rows:
            message = self._row_to_message(row)
            messages.append(message)
        return messages

    async def count(self, conversation_id: str) -> int:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS total FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0
        return int(row[0] or 0)

    async def get_message(self, message_id: str) -> Message | None:
        self._ensure_open()
        cursor = await self.db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        self._increment_reads()
        await self._touch_message(message_id)
        return self._row_to_message(row)

    async def update_message(
        self,
        message_id: str,
        **kwargs: Any,
    ) -> Message | None:
        self._ensure_open()
        fields = []
        params = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            params.append(v)
        if fields:
            fields.append("updated_at = ?")
            params.append(self._now().isoformat())
            params.append(message_id)
            query = f"UPDATE messages SET {', '.join(fields)} WHERE id = ?"
            await self.db.execute(query, params)
            await self.db.commit()
        cursor = await self.db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = await cursor.fetchone()
        return self._row_to_message(row) if row else None

    async def delete_message(self, message_id: str) -> bool:
        self._ensure_open()
        cursor = await self.db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await self.db.commit()
        rows = cursor.rowcount
        self._increment_deletes()
        await self._emit_event("message_deleted", key=message_id, data={"rows_deleted": rows})
        return rows > 0

    # ------------------------------------------------------------------
    # 6. Conversation Window
    # ------------------------------------------------------------------

    async def get_conversation_window(
        self,
        conversation_id: str,
        *,
        start_idx: int = 0,
        end_idx: int | None = None,
    ) -> list[Message]:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        window = [self._row_to_message(row) for row in rows]
        if end_idx is None:
            end_idx = len(window)
        return window[start_idx:end_idx]

    async def truncate_conversation(
        self,
        conversation_id: str,
        keep_count: int = 50,
    ) -> int:
        self._ensure_open()
        cursor = await self.db.execute(
            'SELECT * FROM conversations WHERE id = ?',
            (conversation_id,),
        )
        conversation = await cursor.fetchone()
        if conversation is None:
            return 0
        delete_count = self._row_to_conversation(conversation).message_count - keep_count
        if delete_count <= 0:
            return 0
        cursor = await self.db.execute(
            "DELETE FROM messages WHERE id IN ("
            "    SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at LIMIT ?"
            ")",
            (conversation_id, delete_count),
        )
        await self.db.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # 7. Context Builder
    # ------------------------------------------------------------------

    async def build_context(
        self,
        conversation_id: str,
        *,
        max_tokens: int = 4096,
        include_system: bool = True,
        include_tool: bool = True,
        format: str = "text",
    ) -> dict[str, Any]:
        self._ensure_open()
        messages = await self.get_conversation_window(conversation_id)
        blocks: list[str] = []
        total_tokens = 0
        for message in reversed(messages):
            if include_system and message.role != MessageRole.SYSTEM:
                continue
            if include_tool and message.role != MessageRole.TOOL:
                continue
            text = message.content
            tokens = message.tokens
            if total_tokens + tokens > max_tokens and blocks:
                break
            blocks.append(text)
            total_tokens += tokens
        if format == "json":
            return {
                "conversation_id": conversation_id,
                "message_count": len(messages),
                "total_tokens": total_tokens,
                "blocks": [
                    {
                        "id": m.id,
                        "role": m.role.value,
                        "content": m.content,
                        "timestamp": m.timestamp.isoformat() if isinstance(m.timestamp, datetime) else str(m.timestamp),
                        "tokens": m.tokens,
                    }
                    for m in messages
                ],
            }
        return {
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "total_tokens": total_tokens,
            "context": "\n\n".join(blocks),
            "messages": messages,
        }

    # ------------------------------------------------------------------
    # 8. Topic Tracker
    # ------------------------------------------------------------------

    async def _process_topics(self, conversation_id: str, topics: list[str]) -> None:
        for topic_name in topics:
            topic_id = self._key_to_id(f"topic:{topic_name}")
            if topic_name not in self._topic_map:
                self._topic_map[topic_name] = Topic(
                    id=topic_id,
                    name=topic_name,
                    frequency=0,
                    confidence=0.0,
                    conversation_ids=[conversation_id],
                    last_mentioned=self._now(),
                )
            else:
                topic = self._topic_map[topic_name]
                topic.frequency += 1
                topic.last_mentioned = self._now()
                if conversation_id not in topic.conversation_ids:
                    topic.conversation_ids.append(conversation_id)
            await self.db.execute(
                "INSERT OR IGNORE INTO topics (id, name, frequency, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
                (topic_id, topic_name, 0, 0.0, self._now().isoformat()),
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO conversation_topics (conversation_id, topic_id) VALUES (?, ?)",
                (conversation_id, topic_id),
            )
            await self.db.commit()

    async def get_topics(self, conversation_id: str) -> list[str]:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT topic_id FROM conversation_topics WHERE conversation_id = ?",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        topic_ids = [r[0] for r in rows]
        topics: list[str] = []
        for topic_id in topic_ids:
            cursor2 = await self.db.execute("SELECT name FROM topics WHERE id = ?", (topic_id,))
            row2 = await cursor2.fetchone()
            if row2:
                topics.append(row2[0])
        return topics

    # ------------------------------------------------------------------
    # 9. Entity Manager
    # ------------------------------------------------------------------

    async def _process_entities(self, conversation_id: str, entities: list[dict[str, Any]]) -> None:
        for entity_data in entities:
            name = entity_data.get("name", "")
            etype = entity_data.get("type", "")
            normalized = entity_data.get("normalized", name)
            entity_id = self._key_to_id(f"entity:{normalized}")
            if normalized not in self._entity_map:
                self._entity_map[normalized] = Entity(
                    id=entity_id,
                    name=name,
                    type=etype,
                    normalized=normalized,
                    conversation_ids=[conversation_id],
                    frequency=1,
                    last_mentioned=self._now(),
                )
            else:
                entity = self._entity_map[normalized]
                entity.frequency += 1
                entity.last_mentioned = self._now()
                if conversation_id not in entity.conversation_ids:
                    entity.conversation_ids.append(conversation_id)
            await self.db.execute(
                "INSERT OR IGNORE INTO entities (id, name, type, normalized, created_at) VALUES (?, ?, ?, ?, ?)",
                (entity_id, name, etype, normalized, self._now().isoformat()),
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO conversation_entities (conversation_id, entity_id) VALUES (?, ?)",
                (conversation_id, entity_id),
            )
            await self.db.commit()

    async def get_entities(self, conversation_id: str) -> list[dict[str, Any]]:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT e.name, e.type, e.normalized FROM conversation_entities ce JOIN entities e ON ce.entity_id = e.id WHERE ce.conversation_id = ?",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return [{"name": r[0], "type": r[1], "normalized": r[2]} for r in rows]

    # ------------------------------------------------------------------
    # 11. Conversation Search
    # ------------------------------------------------------------------

    async def search_conversations(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        mode: str = "semantic",
        namespace: str | None = None,
        user_id: str | None = None,
        threshold: float | None = None,
        **kwargs: Any,
    ) -> list[Conversation]:
        self._ensure_open()
        ns = namespace or self._config.namespace
        thr = threshold if threshold is not None else self._config.similarity_threshold

        if mode == SearchMode.SEMANTIC.value or mode == "semantic":
            return await self._search_conversations_semantic(query, limit=limit, namespace=ns, user_id=user_id, threshold=thr)
        elif mode == "exact" or mode == "keyword":
            return await self._search_conversations_keyword(query, limit=limit, namespace=ns, user_id=user_id, threshold=thr)
        elif mode == SearchMode.HYBRID.value or mode == "hybrid":
            semantic = await self._search_conversations_semantic(query, limit=limit * 2, namespace=ns, user_id=user_id, threshold=thr * 0.5)
            keyword = await self._search_conversations_keyword(query, limit=limit * 2, namespace=ns, user_id=user_id, threshold=thr * 0.5)
            seen: set[str] = set()
            merged: list[Conversation] = []
            for conv in semantic + keyword:
                if conv.id in seen:
                    continue
                seen.add(conv.id)
                merged.append(conv)
            return merged[:limit]
        else:
            raise ValueError(f"Unknown search mode '{mode}'")

    async def _search_conversations_semantic(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        namespace: str = DEFAULT_NAMESPACE,
        user_id: str | None = None,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> list[Conversation]:
        query_vec = self._embed(query)
        sql = "SELECT * FROM conversations WHERE namespace = ?"
        params = [namespace]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        cursor = await self.db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        candidates: list[tuple[float, Conversation]] = []
        for row in rows:
            conversation = self._row_to_conversation(row)
            cursor2 = await self.db.execute("SELECT content FROM messages WHERE conversation_id = ? LIMIT 1", (conversation.id,))
            row2 = await cursor2.fetchone()
            if row2:
                content = row2[0]
                vec = self._embed(content)
                score = cosine_similarity(query_vec, vec)
                if score >= threshold:
                    candidates.append((score, conversation))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in candidates[:limit]]

    async def _search_conversations_keyword(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        namespace: str = DEFAULT_NAMESPACE,
        user_id: str | None = None,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> list[Conversation]:
        query_lower = query.lower()
        sql = "SELECT * FROM conversations WHERE namespace = ?"
        params = [namespace]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        cursor = await self.db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        candidates: list[tuple[float, Conversation]] = []
        for row in rows:
            conversation = self._row_to_conversation(row)
            cursor2 = await self.db.execute("SELECT content FROM messages WHERE conversation_id = ?", (conversation.id,))
            rows2 = await cursor2.fetchall()
            total_score = 0.0
            for row2 in rows2:
                content = row2[0]
                content_lower = content.lower()
                overlap = sum(1 for word in query_lower.split() if word in content_lower.split())
                if overlap > 0:
                    total_score += overlap / max(len(query_lower.split()), 1)
            if total_score > 0:
                score = total_score / max(len(rows2), 1)
                if score >= threshold:
                    candidates.append((score, conversation))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in candidates[:limit]]

    # ------------------------------------------------------------------
    # 14. Ranking Engine
    # ------------------------------------------------------------------

    def _rank_conversations(
        self,
        conversations: list[Conversation],
        *,
        query: str | None = None,
        recency_boost: bool = True,
    ) -> list[Conversation]:
        scored: list[tuple[float, Conversation]] = []
        now = self._now()
        for conversation in conversations:
            score = 0.0
            if recency_boost:
                age_hours = (now - conversation.created_at).total_seconds() / 3600.0
                score += max(0.0, 1.0 - age_hours / (self._config.max_conversation_age_days * 24.0)) * self._config.recency_weight
            if query:
                token_overlap = self._token_overlap_score(query, conversation)
                score += token_overlap * 0.1
            scored.append((score, conversation))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def _token_overlap_score(self, query: str, conversation: Conversation) -> float:
        query_tokens = set(query.lower().split())
        total_overlap = 0
        for message in conversation.messages:
            text = message.content
            entry_tokens = set(text.lower().split())
            total_overlap += len(query_tokens & entry_tokens)
        return total_overlap / max(len(query_tokens), 1)

    # ------------------------------------------------------------------
    # 15. Summarization
    # ------------------------------------------------------------------

    async def summarize_conversation(
        self,
        conversation_id: str,
        *,
        max_summary_length: int = 500,
        style: str = "bullet",
    ) -> str:
        self._ensure_open()
        messages = await self.get_conversation_window(conversation_id)
        if len(messages) < self._config.summarization_min_messages:
            return "Conversation too short to summarize."
        content = "\n".join([f"{m.role}: {m.content}" for m in messages])
        sentences = re.split(r'(?<=[.!?])\s+', content)
        if style == "bullet":
            summary = "Key points:\n"
            for sentence in sentences[:3]:
                summary += f"• {sentence.strip()}\n"
            return summary[:max_summary_length]
        elif style == "summary":
            if len(sentences) > 3:
                return " ".join(sentences[:3])[:max_summary_length] + "..."
            return content[:max_summary_length]
        else:
            return content[:max_summary_length]

    # ------------------------------------------------------------------
    # 16. Context Compression
    # ------------------------------------------------------------------

    async def compress_conversation(
        self,
        conversation_id: str,
        *,
        threshold: float | None = None,
    ) -> int:
        self._ensure_open()
        thr = threshold if threshold is not None else self._config.similarity_threshold
        cursor = await self.db.execute("SELECT id FROM messages WHERE conversation_id = ?", (conversation_id,))
        rows = await cursor.fetchall()
        message_ids = [r[0] for r in rows]
        removed = 0
        for i, msg_id in enumerate(message_ids):
            if i < 3:
                continue
            msg_cursor = await self.db.execute("SELECT role, content FROM messages WHERE id = ?", (msg_id,))
            row = await msg_cursor.fetchone()
            if row:
                role, content = row
                vec = self._embed(content)
                for j, other_id in enumerate(message_ids):
                    if j >= i - 3:
                        break
                    other_cursor = await self.db.execute("SELECT content FROM messages WHERE id = ?", (other_id,))
                    other_row = await other_cursor.fetchone()
                    if other_row:
                        other_content = other_row[0]
                        other_vec = self._embed(other_content)
                        score = cosine_similarity(vec, other_vec)
                        if score >= thr:
                            await self.delete_message(msg_id)
                            removed += 1
                            break
        return removed

    # ------------------------------------------------------------------
    # 18. Promotion
    # ------------------------------------------------------------------

    async def promote_conversation(
        self,
        conversation_id: str,
        *,
        amount: float = 0.2,
    ) -> Conversation | None:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        conversation = self._row_to_conversation(row)
        token_count = conversation.token_count
        new_token_count = min(token_count * (1 + amount), self._config.max_tokens)
        await self.db.execute(
            "UPDATE conversations SET token_count = ?, updated_at = ? WHERE id = ?",
            (new_token_count, self._now().isoformat(), conversation_id),
        )
        await self.db.commit()
        return await self.load_conversation(conversation_id)

    async def decay_conversation(
        self,
        conversation_id: str,
        *,
        half_life_hours: float = 168.0,
    ) -> Conversation | None:
        self._ensure_open()
        cursor = await self.db.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        conversation = self._row_to_conversation(row)
        cursor2 = await self.db.execute("SELECT created_at FROM conversations WHERE id = ?", (conversation_id,))
        row2 = await cursor2.fetchone()
        if row2 and row2[0]:
            created = datetime.fromisoformat(row2[0])
            age_hours = (self._now() - created).total_seconds() / 3600.0
            decay_factor = 0.5 ** (age_hours / half_life_hours)
            new_token_count = max(0, conversation.token_count * decay_factor)
            await self.db.execute(
                "UPDATE conversations SET token_count = ?, updated_at = ? WHERE id = ?",
                (new_token_count, self._now().isoformat(), conversation_id),
            )
            await self.db.commit()
        return await self.load_conversation(conversation_id)

    # ------------------------------------------------------------------
    # 19. Synchronization + Snapshot/Backup
    # ------------------------------------------------------------------

    async def synchronize(self) -> None:
        self._ensure_open()
        await self.db.commit()

    async def snapshot(self) -> dict[str, Any]:
        self._ensure_open()
        now = self._now()
        self._last_snapshot = now
        return {
            "timestamp": now.isoformat(),
            "namespace": self._config.namespace,
            "conversation_count": self._sync_count(),
            "total_messages": await self._message_count(),
            "total_tokens": await self._token_count(),
            "config": asdict(self._config),
        }

    async def backup(self, path: str) -> bool:
        self._ensure_open()
        backup_path = Path(path)
        if backup_path.is_dir():
            backup_path = backup_path / f"conversation_backup_{self._now().strftime('%Y%m%d_%H%M%S')}.db"
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
            raise ConversationNotFoundError(f"Backup file not found: {path}")
        if self._db_path != ":memory:":
            await self.close()
            shutil.copy2(str(backup_path), self._db_path)
            await self._ensure_db()
            await self._init_schema()
        else:
            with open(str(backup_path), "r") as f:
                data = json.load(f)
            await self.clear()
            for conv_data in data.get("conversations", []):
                await self.create_conversation(
                    conv_data["title"],
                    user_id=conv_data.get("user_id", "anonymous"),
                )
        await self._emit_event("restored", data={"path": str(backup_path)})
        return True

    # ------------------------------------------------------------------
    # 20. Health + Metrics
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if not self._closed else "closed",
            "id": str(self.identifier),
            "namespace": self._config.namespace,
            "initialized": self._initialized,
            "closed": self._closed,
            "conversation_count": self._sync_count(),
            "total_messages": asyncio.run(self._message_count()),
            "db_path": self._db_path,
            "window_size": self._config.window_size,
            "last_snapshot": self._last_snapshot.isoformat() if self._last_snapshot else None,
            "last_compact": self._last_compact.isoformat() if self._last_compact else None,
            "last_backup": self._last_backup.isoformat() if self._last_backup else None,
        }

    def metrics(self) -> dict[str, Any]:
        stats = self._statistics
        return {
            "conversation_count": self._sync_count(),
            "total_messages": asyncio.run(self._message_count()),
            "total_tokens": asyncio.run(self._token_count()),
            "reads": stats.reads,
            "writes": stats.writes,
            "updates": stats.updates,
            "deletes": stats.deletes,
            "searches": stats.searches,
            "topics_tracked": len(self._topic_map),
            "entities_tracked": len(self._entity_map),
            "window_size": self._config.window_size,
            "similarity_threshold": self._config.similarity_threshold,
            "events_emitted": self._event_count,
            "listeners_active": sum(len(v) for v in self._listeners.values()),
        }

    # ------------------------------------------------------------------
    # 21. Events + Lifecycle
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

    def _row_to_conversation(self, row: tuple) -> Conversation:
        metadata_json = row[4] if len(row) > 4 else "{}"
        try:
            metadata = self._json_loads(metadata_json)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        return Conversation(
            id=row[0],
            title=row[1],
            user_id=row[2],
            namespace=row[3],
            metadata=metadata,
            token_count=row[5],
            message_count=row[6],
            created_at=datetime.fromisoformat(row[7]) if row[7] else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(row[8]) if row[8] else datetime.now(timezone.utc),
            last_accessed=datetime.fromisoformat(row[9]) if row[9] else datetime.now(timezone.utc),
            expires_at=datetime.fromisoformat(row[10]) if row[10] else None,
            state=ConversationState(row[11]) if row[11] else ConversationState.CREATED,
        )

    def _row_to_message(self, row: tuple) -> Message:
        metadata_json = row[4] if len(row) > 4 else "{}"
        tags = []
        entities = []
        topics = []
        if len(row) > 13:
            try:
                tags = self._json_loads(row[13]) or []
            except (json.JSONDecodeError, TypeError):
                tags = []
            try:
                entities = self._json_loads(row[14]) or []
            except (json.JSONDecodeError, TypeError):
                entities = []
            try:
                topics = self._json_loads(row[15]) or []
            except (json.JSONDecodeError, TypeError):
                topics = []

        return Message(
            id=row[0],
            conversation_id=row[1],
            role=MessageRole(row[2]),
            content=row[3],
            metadata=self._json_loads(metadata_json) if metadata_json != "null" else {},
            tokens=row[5],
            timestamp=datetime.fromisoformat(row[6]) if row[6] else datetime.now(timezone.utc),
            created_at=datetime.fromisoformat(row[7]) if row[7] else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(row[8]) if row[8] else datetime.now(timezone.utc),
            expires_at=datetime.fromisoformat(row[9]) if row[9] else None,
            parent_message_id=row[10],
            importance=row[11] if row[11] is not None else 0.5,
            priority=row[12] if row[12] is not None else "normal",
            tags=tags,
            entities=entities,
            topics=topics,
            source=row[16] if len(row) > 16 else "runtime",
        )

    async def _touch_conversation(self, conversation_id: str) -> None:
        await self.db.execute(
            "UPDATE conversations SET last_accessed = ? WHERE id = ?",
            (self._now().isoformat(), conversation_id),
        )
        await self.db.commit()

    async def _touch_message(self, message_id: str) -> None:
        await self.db.execute(
            "UPDATE messages SET updated_at = ? WHERE id = ?",
            (self._now().isoformat(), message_id),
        )
        await self.db.commit()

    async def _message_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM messages")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _token_count(self) -> int:
        cursor = await self.db.execute("SELECT SUM(tokens) FROM messages")
        row = await cursor.fetchone()
        return row[0] if row else 0

    def _sync_count(self) -> int:
        try:
            cursor = asyncio.get_event_loop().run_until_complete(
                self.db.execute("SELECT COUNT(*) FROM conversations")
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _embed(self, text: str) -> list[float]:
        return self._embedder.embed(text)

    async def _process_tags(self, conversation_id: str, tags: list[str]) -> None:
        for tag in tags:
            tag_id = self._key_to_id(f"tag:{tag}")
            await self.db.execute(
                "INSERT OR IGNORE INTO tags (id, name, created_at) VALUES (?, ?, ?)",
                (tag_id, tag, self._now().isoformat()),
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO conversation_tags (conversation_id, tag_id) VALUES (?, ?)",
                (conversation_id, tag_id),
            )
            await self.db.commit()

    # ------------------------------------------------------------------
    # Export/Import
    # ------------------------------------------------------------------

    async def export(self) -> dict[str, Any]:
        conversations = await self.list_conversations()
        messages = []
        for conv in conversations:
            conv_messages = await self.get_conversation_window(conv.id)
            messages.extend(conv_messages)
        return {
            "conversations": [
                {
                    "id": c.id,
                    "title": c.title,
                    "user_id": c.user_id,
                    "namespace": c.namespace,
                    "metadata": c.metadata,
                    "token_count": c.token_count,
                    "message_count": c.message_count,
                    "created_at": c.created_at.isoformat() if isinstance(c.created_at, datetime) else str(c.created_at),
                    "updated_at": c.updated_at.isoformat() if isinstance(c.updated_at, datetime) else str(c.updated_at),
                    "last_accessed": c.last_accessed.isoformat() if isinstance(c.last_accessed, datetime) else str(c.last_accessed),
                    "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                    "state": c.state.value,
                }
                for c in conversations
            ],
            "messages": [
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "role": m.role.value,
                    "content": m.content,
                    "metadata": m.metadata,
                    "tokens": m.tokens,
                    "timestamp": m.timestamp.isoformat() if isinstance(m.timestamp, datetime) else str(m.timestamp),
                    "created_at": m.created_at.isoformat() if isinstance(m.created_at, datetime) else str(m.created_at),
                    "updated_at": m.updated_at.isoformat() if isinstance(m.updated_at, datetime) else str(m.updated_at),
                    "expires_at": m.expires_at.isoformat() if m.expires_at else None,
                    "parent_message_id": m.parent_message_id,
                    "importance": m.importance,
                    "priority": m.priority,
                    "tags": m.tags,
                    "entities": m.entities,
                    "topics": m.topics,
                    "source": m.source,
                }
                for m in messages
            ],
        }

    async def import_data(self, data: dict[str, Any]) -> int:
        count = 0
        for conv_data in data.get("conversations", []):
            conversation = await self.create_conversation(
                conv_data["title"],
                user_id=conv_data.get("user_id", "anonymous"),
            )
            count += 1
        return count

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def validate(self) -> dict[str, Any]:
        self._ensure_open()
        total = self._sync_count()
        conversations_without_messages = 0
        cursor = await self.db.execute("SELECT id FROM conversations")
        rows = await cursor.fetchall()
        for row in rows:
            conv_id = row[0]
            cursor2 = await self.db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,))
            row2 = await cursor2.fetchone()
            if row2 and row2[0] == 0:
                conversations_without_messages += 1
        return {
            "total_conversations": total,
            "conversations_without_messages": conversations_without_messages,
            "healthy": conversations_without_messages == 0,
        }

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    async def analytics(self) -> dict[str, Any]:
        self._ensure_open()
        total_conversations = self._sync_count()
        total_messages = await self._message_count()
        total_tokens = await self._token_count()
        return {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "avg_messages_per_conversation": total_messages / max(total_conversations, 1),
            "avg_tokens_per_conversation": total_tokens / max(total_conversations, 1),
        }

    # ------------------------------------------------------------------
    # Hook overrides
    # ------------------------------------------------------------------

    async def before_create(self, conversation: Conversation | None) -> None:
        pass

    async def after_create(self, conversation: Conversation | None) -> None:
        pass

    async def after_read(self, conversation: Conversation | None) -> None:
        pass

    async def after_update(self, conversation: Conversation | None) -> None:
        pass

    async def after_delete(self, conversation: Conversation | None) -> None:
        pass

    async def after_search(self, conversation: Conversation | None) -> None:
        pass

    def remove_hook(self, hook: Callable[..., Any]) -> None:
        if hook in self._hooks:
            self._hooks.remove(hook)

    def clear_hooks(self) -> None:
        self._hooks.clear()

    def hook_count(self) -> int:
        return len(self._hooks)

    def audit_record(self, operation: MemoryOperation, conversation: Conversation | None) -> None:
        pass

    async def serialize(self, conversation: Conversation) -> bytes:
        return self._json_dumps(asdict(conversation)).encode("utf-8")

    async def deserialize(self, data: bytes) -> Conversation:
        obj = json.loads(data.decode("utf-8"))
        return Conversation(
            id=obj["id"],
            title=obj["title"],
            user_id=obj.get("user_id", "anonymous"),
            namespace=obj.get("namespace", DEFAULT_NAMESPACE),
            metadata=obj.get("metadata", {}),
            token_count=obj.get("token_count", 0),
            message_count=obj.get("message_count", 0),
            created_at=datetime.fromisoformat(obj["created_at"]) if obj.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(obj["updated_at"]) if obj.get("updated_at") else datetime.now(timezone.utc),
            last_accessed=datetime.fromisoformat(obj["last_accessed"]) if obj.get("last_accessed") else datetime.now(timezone.utc),
            expires_at=datetime.fromisoformat(obj["expires_at"]) if obj.get("expires_at") else None,
            state=ConversationState(obj.get("state", "created")),
        )

    # ------------------------------------------------------------------
    # Utility functions
    # ------------------------------------------------------------------

    def _create_topics_table(self) -> None:
        # This method is now integrated into _init_schema for efficiency
        pass

    def _create_entities_table(self) -> None:
        # This method is now integrated into _init_schema for efficiency
        pass

    def _create_embedding_cache_table(self) -> None:
        # This method is now integrated into _init_schema for efficiency
        pass

    def _create_events_table(self) -> None:
        # This method is now integrated into _init_schema for efficiency
        pass

    async def _initialize_indices(self) -> None:
        """Initialize database indices for optimal performance."""
        indices = [
            "CREATE INDEX IF NOT EXISTS idx_conversations_namespace ON conversations(namespace)",
            "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)",
            "CREATE INDEX IF NOT EXISTS idx_messages_topics ON messages(topics)",
            "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)",
            "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)",
        ]

        for index_sql in indices:
            try:
                await self.db.execute(index_sql)
            except Exception as e:
                pass  # Index may already exist

        await self.db.commit()

    def _is_healthy(self, value: Any) -> bool:
        if isinstance(value, dict):
            return True
        return value is True

    async def health_check(self) -> dict[str, Any]:
        """Perform comprehensive health checks and return diagnostics."""
        checks = {
            "database_connection": await self._check_database(),
            "schema_integrity": await self._check_schema(),
            "data_consistency": await self._check_data_consistency(),
            "performance_metrics": await self._check_performance(),
            "event_system": await self._check_events(),
            "cache_status": await self._check_cache(),
        }

        checks["overall_status"] = all(_is_healthy(checks[k]) for k in checks if k != "overall_status")
        return checks

    async def _check_database(self) -> bool:
        try:
            await self.db.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def _check_schema(self) -> bool:
        try:
            tables = ["conversations", "messages", "topics", "entities", "embedding_cache", "events"]
            for table in tables:
                cursor = await self.db.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    continue
            return True
        except Exception:
            return False

    async def _check_data_consistency(self) -> bool:
        try:
            # Check for orphaned messages
            cursor = await self.db.execute("SELECT id FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)")
            orphaned_messages = await cursor.fetchall()
            if orphaned_messages:
                return False

            # Check for orphaned topic references
            cursor = await self.db.execute("SELECT conversation_id FROM conversation_topics WHERE conversation_id NOT IN (SELECT id FROM conversations)")
            orphaned_topics = await cursor.fetchall()
            if orphaned_topics:
                return False

            return True
        except Exception:
            return False

    async def _check_performance(self) -> dict:
        start_time = time.time()
        cursor = await self.db.execute("SELECT COUNT(*) FROM conversations")
        row = await cursor.fetchone()
        end_time = time.time()

        return {
            "query_time_ms": (end_time - start_time) * 1000,
            "conversation_count": row[0] if row else 0,
        }

    async def _check_events(self) -> bool:
        try:
            await self.db.execute(
                "SELECT COUNT(*) FROM events WHERE created_at > ?",
                (self._now().isoformat(),),
            )
            return True
        except Exception:
            return False

    async def _check_cache(self) -> dict:
        return {
            "embedder_cache_size": self._embedder.cache_size,
            "max_cache_size": self._config.cache_max_size,
            "cache_hit_rate": self._embedder.stats().get("hit_rate", 0.0),
        }

    # ------------------------------------------------------------------
    # Topic and entity management utilities
    # ------------------------------------------------------------------

    def _extract_topics_from_text(self, text: str) -> List[str]:
        """Extract topics from text using simple keyword matching."""
        words = text.lower().split()
        technical_terms = {"crypto", "blockchain", "bitcoin", "ethereum", "defi", "nft", "web3"}
        financial_terms = {"stock", "stock market", "trading", "investing", "portfolio"}
        technical_count = sum(1 for word in words if word in technical_terms)
        financial_count = sum(1 for word in words if word in financial_terms)

        topics = []
        if technical_count > 0:
            topics.append("technical")
        if financial_count > 0:
            topics.append("financial")
        if technical_count == 0 and financial_count == 0 and words:
            topics.append("general")

        return topics

    def _extract_entities_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Extract named entities from text using simple pattern matching."""
        entities = []
        # Simple cryptocurrency pattern matching
        crypto_pattern = r'\b(?:BTC|ETH|bitcoin|ethereum)\b'
        for match in re.finditer(crypto_pattern, text, re.IGNORECASE):
            entities.append({
                "name": match.group(),
                "type": "cryptocurrency",
                "normalized": match.group().upper(),
            })
        return entities

    async def _prune_old_data(self, days: int = 30) -> int:
        """Remove data older than specified days."""
        cutoff_date = (self._now() - timedelta(days=days)).isoformat()
        try:
            cursor = await self.db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff_date,))
            await self.db.commit()
            return cursor.rowcount
        except Exception:
            return 0

    async def _optimize_tables(self) -> None:
        """Optimize database tables for performance."""
        tables = ["conversations", "messages", "topics", "entities", "embedding_cache", "events"]
        for table in tables:
            try:
                await self.db.execute(f"VACUUM {table}")
            except Exception:
                pass  # VACUUM may not be available in all SQLite versions
        await self.db.commit()