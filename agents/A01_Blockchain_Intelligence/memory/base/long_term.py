"""
Long-Term Memory Engine for CIE-OS.

Enterprise Long-Term Memory with:
â€¢ Persistent Storage (SQLite / Filesystem / Redis / Postgres / Chroma)
â€¢ Semantic / Episodic / Knowledge / Procedural Memory
â€¢ Hybrid Retrieval
â€¢ Ranking Engine
â€¢ Context Builder
â€¢ Consolidation
â€¢ Promotion & Decay
â€¢ Snapshots, Backup & Sync
â€¢ Events, Metrics & Health
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from memory.base.memory import (
    BaseMemory,
    EmbeddingProvider,
    MemoryEntry,
    MemoryMetadata,
    MemoryPriority,
    MemorySearchResult,
    SearchMode,
)

# ============================================================
# Public Constants
# ============================================================

DEFAULT_NAMESPACE = "global"

DEFAULT_BACKEND = "sqlite"

DEFAULT_COLLECTION = "long_term"

DEFAULT_CAPACITY = 2_000_000

DEFAULT_BATCH_SIZE = 256

DEFAULT_SIMILARITY_THRESHOLD = 0.80

DEFAULT_TOP_K = 10

DEFAULT_DECAY_DAYS = 90

DEFAULT_CONSOLIDATION_INTERVAL = 3600

DEFAULT_EMBED_DIMENSIONS = 128

IMPORTANCE_FLOOR = 0.05

PROMOTE_STEP = 0.2

DECAY_FACTOR = 0.5

SERIALIZATION_VERSION = 2

LOGGER = logging.getLogger(__name__)

# ============================================================
# Enumerations
# ============================================================


class MemoryType(str, Enum):
    """
    Long-term memory category.
    """

    SEMANTIC = "semantic"

    EPISODIC = "episodic"

    KNOWLEDGE = "knowledge"

    PROCEDURAL = "procedural"


class MemoryBackend(str, Enum):
    """
    Supported durable storage backends.
    """

    SQLITE = "sqlite"

    POSTGRES = "postgres"

    REDIS = "redis"

    CHROMA = "chroma"

    FILESYSTEM = "filesystem"


class MemoryState(str, Enum):
    """
    Engine lifecycle state.
    """

    CREATED = "created"

    INITIALIZING = "initializing"

    READY = "ready"

    RUNNING = "running"

    STOPPED = "stopped"

    CLOSED = "closed"


class ConsolidationPolicy(str, Enum):
    """
    When consolidation runs.
    """

    NEVER = "never"

    PERIODIC = "periodic"

    IMMEDIATE = "immediate"


class ForgettingPolicy(str, Enum):
    """
    How forgotten entries are evicted.
    """

    NEVER = "never"

    DECAY = "decay"

    LRU = "lru"

    IMPORTANCE = "importance"


# ============================================================
# Runtime Dataclasses
# ============================================================


@dataclass(slots=False)
class MemoryStatistics:
    """
    Runtime statistics counters.
    """

    writes: int = 0

    reads: int = 0

    updates: int = 0

    deletions: int = 0

    searches: int = 0

    consolidations: int = 0

    promotions: int = 0

    decays: int = 0

    snapshots: int = 0

    imports: int = 0

    exports: int = 0

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    def as_dict(self) -> dict[str, Any]:
        """
        Return a serializable statistics snapshot.
        """

        return {
            "writes": self.writes,
            "reads": self.reads,
            "updates": self.updates,
            "deletions": self.deletions,
            "searches": self.searches,
            "consolidations": self.consolidations,
            "promotions": self.promotions,
            "decays": self.decays,
            "snapshots": self.snapshots,
            "imports": self.imports,
            "exports": self.exports,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=False)
class RuntimeMemory:
    """
    In-memory runtime wrapper around a durable entry.
    """

    record: MemoryEntry[Any]

    created_at: datetime

    updated_at: datetime

    last_access: datetime

    access_count: int = 0

    importance: float = 0.5

    similarity_score: float = 0.0


# ============================================================
# Configuration
# ============================================================


@dataclass(slots=False)
class LongTermMemoryConfig:
    """
    Long-term memory engine configuration.
    """

    namespace: str = DEFAULT_NAMESPACE

    backend: MemoryBackend = MemoryBackend.SQLITE

    collection: str = DEFAULT_COLLECTION

    capacity: int = DEFAULT_CAPACITY

    batch_size: int = DEFAULT_BATCH_SIZE

    similarity_threshold: float = (
        DEFAULT_SIMILARITY_THRESHOLD
    )

    top_k: int = DEFAULT_TOP_K

    decay_days: int = DEFAULT_DECAY_DAYS

    consolidation_interval: int = (
        DEFAULT_CONSOLIDATION_INTERVAL
    )

    consolidation_policy: (
        ConsolidationPolicy
    ) = ConsolidationPolicy.PERIODIC

    forgetting_policy: (
        ForgettingPolicy
    ) = ForgettingPolicy.DECAY

    embedding_provider: (
        EmbeddingProvider | None
    ) = None


# ============================================================
# Backend Protocol
# ============================================================


class MemoryBackendProtocol(
    Protocol,
):
    """
    Durable storage backend contract.
    """

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        ...
        """Persist an entry."""

    async def delete(
        self,
        key: str,
    ) -> None:
        ...
        """Remove an entry by key."""

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        ...
        """Load an entry by key."""

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        ...
        """Search entries by key or payload text."""

    async def keys(
        self,
    ) -> Sequence[str]:
        ...
        """Return all persisted entry keys."""

    async def clear(self) -> None:
        ...
        """Remove every entry."""


# ============================================================
# Module-Level Validation Helpers
# ============================================================


def _validate_key(
    key: str,
) -> str:
    """
    Validate a memory entry key.
    """

    if not isinstance(key, str):
        raise TypeError(
            "key must be a string"
        )

    if not key or len(key) > 257:
        raise ValueError(
            "key must be non-empty and at most "
            "257 characters"
        )

    if any(
        ord(character) < 33
        for character in key
    ):
        raise ValueError(
            "key must not contain control characters"
        )

    return key


def _validate_tags(
    tags: Iterable[str] | None,
) -> list[str]:
    """
    Validate and normalize a tag list.
    """

    if tags is None:
        return []

    normalized = [
        str(tag).strip()
        for tag in tags
    ]

    if any(
        not tag
        for tag in normalized
    ):
        raise ValueError(
            "tags must not contain empty values"
        )

    return normalized


def _memory_type_tag(
    memory_type: MemoryType,
) -> str:
    """
    Encode a memory type into a metadata tag.
    """

    return f"lt:type:{memory_type.value}"


def _parse_memory_type(
    tags: Sequence[str],
) -> MemoryType:
    """
    Decode a memory type from metadata tags.
    """

    for tag in tags:
        if tag.startswith("lt:type:"):
            try:
                return MemoryType(
                    tag.removeprefix("lt:type:")
                )
            except ValueError:
                continue

    return MemoryType.SEMANTIC


def _importance_tag(
    importance: float,
) -> str:
    """
    Encode an importance score into a metadata tag.
    """

    return f"lt:importance:{importance:.4f}"


def _parse_importance(
    tags: Sequence[str],
) -> float:
    """
    Decode an importance score from metadata tags.
    """

    for tag in tags:
        if tag.startswith("lt:importance:"):
            try:
                return float(
                    tag.removeprefix("lt:importance:")
                )
            except ValueError:
                continue

    return 0.5


def _relation_tag(
    object_key: str,
    relation: str,
) -> str:
    """
    Encode a knowledge edge into a metadata tag.
    """

    return "lt:rel:" + json.dumps(
        [
            object_key,
            relation,
        ]
    )


def _parse_relation_tags(
    tags: Sequence[str],
) -> dict[str, list[str]]:
    """
    Decode knowledge edges from metadata tags.

    Returns a mapping of object key to relation names.
    """

    relations: dict[
        str,
        list[str],
    ] = {}

    for tag in tags:
        if not tag.startswith("lt:rel:"):
            continue

        try:
            object_key, relation = json.loads(
                tag.removeprefix("lt:rel:")
            )
        except (
            ValueError,
            TypeError,
        ):
            continue

        if (
            isinstance(object_key, str)
            and isinstance(relation, str)
            and object_key
            and relation
        ):
            relations.setdefault(
                object_key,
                [],
            ).append(relation)

    return relations


def _cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    """
    Cosine similarity between two vectors.
    """

    if (
        not left
        or not right
        or len(left) != len(right)
    ):
        return 0.0

    dot = sum(
        x * y
        for x, y in zip(left, right)
    )

    left_norm = math.sqrt(
        sum(x * x for x in left)
    )

    right_norm = math.sqrt(
        sum(y * y for y in right)
    )

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return dot / (left_norm * right_norm)


def _fallback_embed(
    text: str,
    dimensions: int = DEFAULT_EMBED_DIMENSIONS,
) -> list[float]:
    """
    Deterministic hashing-based embedding used when no
    provider is configured.

    Produces binary (0/1) feature vectors over character
    n-grams and words, so cosine similarities are always
    in [0.0, 1.0].
    """

    vector = [
        0.0
    ] * dimensions

    tokens = text.lower().split()

    if not tokens:
        return vector

    def _set(
        payload: str,
        salt: int,
    ) -> None:
        # Hashing-trick bucket index, not an integrity check.
        # usedforsecurity=False keeps this working under FIPS builds.
        digest = hashlib.md5(
            f"{payload}:{salt}".encode(
                "utf-8"
            ),
            usedforsecurity=False,
        ).digest()

        vector[
            (digest[0] << 8 | digest[1])
            % dimensions
        ] = 1.0

    for token in tokens:
        _set(token, 0)

        for gram_length in (2, 3):
            if len(token) < gram_length:
                continue

            for index in range(
                len(token) - gram_length + 1
            ):
                _set(
                    token[
                        index:index + gram_length
                    ],
                    gram_length,
                )

    return vector


def _entry_text(
    entry: MemoryEntry[Any],
) -> str:
    """
    Build a searchable text representation of an entry.
    """

    parts: list[str] = [
        entry.key,
    ]

    if isinstance(entry.value, str):
        parts.append(entry.value)
    elif isinstance(entry.value, dict):
        parts.append(
            " ".join(
                str(value)
                for value in entry.value.values()
            )
        )

        parts.append(
            " ".join(
                str(key)
                for key in entry.value.keys()
            )
        )
    else:
        parts.append(
            str(entry.value)
        )

    parts.extend(entry.metadata.tags)

    return " ".join(
        parts
    )


def _entry_value_text(
    entry: MemoryEntry[Any],
) -> str:
    """
    Build a searchable text representation of an entry's
    value only (metadata excluded).
    """

    value = entry.value

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return " ".join(
            [
                *[
                    str(item)
                    for item in value.values()
                ],
                *[
                    str(key)
                    for key in value.keys()
                ],
            ]
        )

    if isinstance(value, list):
        return " ".join(
            str(item)
            for item in value
        )

    return str(value)


def _token_similarity(
    a: str,
    b: str,
    *,
    prefix: bool = True,
) -> float:
    """
    Normalized token-overlap similarity in [0.0, 1.0].

    Each token of the shorter side counts as a hit when it
    equals or prefix-matches a token on the other side.
    """

    tokens_a = [
        token
        for token in a.lower().split()
        if token
    ]

    tokens_b = [
        token
        for token in b.lower().split()
        if token
    ]

    if not tokens_a or not tokens_b:
        return 0.0

    shorter = (
        tokens_a
        if len(tokens_a) <= len(tokens_b)
        else tokens_b
    )

    longer = (
        tokens_b
        if len(tokens_a) <= len(tokens_b)
        else tokens_a
    )

    hits = 0

    for token in shorter:
        matched = False

        for other in longer:
            if token == other:
                matched = True
                break

            if (
                prefix
                and (
                    other.startswith(token)
                    or token.startswith(other)
                )
            ):
                matched = True
                break

        if matched:
            hits += 1

    return hits / len(shorter)


def _encode_entry(
    entry: MemoryEntry[Any],
) -> str:
    """
    Serialize a full entry (value + metadata) to JSON.
    """

    metadata = entry.metadata

    payload: dict[str, Any] = {
        "version": SERIALIZATION_VERSION,
        "key": entry.key,
        "identifier": str(entry.identifier),
        "metadata": {
            "namespace": metadata.namespace,
            "source": metadata.source,
            "tags": list(metadata.tags),
            "confidence": metadata.confidence,
            "priority": (
                metadata.priority.value
                if isinstance(
                    metadata.priority,
                    Enum,
                )
                else str(metadata.priority)
            ),
            "created_at": (
                metadata.created_at.isoformat()
                if metadata.created_at
                else None
            ),
            "updated_at": (
                metadata.updated_at.isoformat()
                if metadata.updated_at
                else None
            ),
            "expires_at": (
                metadata.expires_at.isoformat()
                if metadata.expires_at
                else None
            ),
        },
        "value": entry.value,
    }

    return json.dumps(
        payload,
        default=str,
        sort_keys=False,
    )


def _decode_entry(
    payload: str,
    *,
    namespace: str = DEFAULT_NAMESPACE,
) -> MemoryEntry[Any]:
    """
    Deserialize a JSON payload into a full memory entry.
    """

    data: dict[str, Any] = json.loads(
        payload
    )

    metadata_data: dict[str, Any] = data.get(
        "metadata",
        {},
    )

    metadata = MemoryMetadata(
        namespace=metadata_data.get(
            "namespace",
            namespace,
        ),
        source=metadata_data.get(
            "source",
            "runtime",
        ),
        tags=list(
            metadata_data.get(
                "tags",
                [],
            )
        ),
        confidence=float(
            metadata_data.get(
                "confidence",
                1.0,
            )
        ),
        priority=(
            MemoryPriority(
                metadata_data["priority"]
            )
            if metadata_data.get("priority")
            else MemoryPriority.NORMAL
        ),
        created_at=(
            datetime.fromisoformat(
                metadata_data["created_at"]
            )
            if metadata_data.get("created_at")
            else datetime.now(timezone.utc)
        ),
        updated_at=(
            datetime.fromisoformat(
                metadata_data["updated_at"]
            )
            if metadata_data.get("updated_at")
            else datetime.now(timezone.utc)
        ),
        expires_at=(
            datetime.fromisoformat(
                metadata_data["expires_at"]
            )
            if metadata_data.get("expires_at")
            else None
        ),
    )

    return MemoryEntry(
        key=data.get("key", ""),
        value=data.get("value"),
        metadata=metadata,
        identifier=(
            uuid.UUID(data["identifier"])
            if data.get("identifier")
            else uuid.uuid5(uuid.NAMESPACE_DNS, "")
        ),
    )


# ============================================================
# Long-Term Memory Engine
# ============================================================


class LongTermMemory(
    BaseMemory,
):
    """
    Enterprise Long-Term Memory
    for CIE-OS.

    Features

    * Persistent Storage
    * Semantic Memory
    * Episodic Memory
    * Knowledge Memory
    * Procedural Memory
    * Hybrid Retrieval
    * Ranking Engine
    * Context Builder
    * Consolidation
    * Promotion
    * Memory Decay
    * Forgetting Policies
    * Snapshots, Backup & Sync
    * Events, Metrics & Health
    """

    # ============================================================
    # Constructor & Configuration
    # ============================================================

    def __init__(
        self,
        config: LongTermMemoryConfig | None = None,
    ) -> None:
        """
        Initialize the long-term memory engine.

        Parameters
        ----------
        config:
            Engine configuration. Defaults are used when omitted.
        """

        super().__init__(
            namespace=(
                config.namespace
                if config is not None
                else DEFAULT_NAMESPACE
            ),
        )

        self._config = (
            config
            or LongTermMemoryConfig()
        )

        self._validate_configuration()

        self._lt_state: MemoryState = MemoryState.CREATED

        self._statistics = MemoryStatistics()

        self._backends: dict[
            str,
            MemoryBackendProtocol,
        ] = {}

        self._active_backend: (
            MemoryBackendProtocol | None
        ) = None

        self._runtime: dict[
            str,
            RuntimeMemory,
        ] = {}

        self._semantic_index: dict[
            str,
            list[float],
        ] = {}

        self._episodic_index: dict[
            str,
            datetime,
        ] = {}

        self._knowledge_index: dict[
            str,
            dict[str, Any],
        ] = {}

        self._procedural_index: dict[
            str,
            str,
        ] = {}

        self._listeners: dict[
            str,
            list[Callable[..., Any]],
        ] = defaultdict(list)

        self._consolidation_task: (
            asyncio.Task[Any] | None
        ) = None

        self._decay_task: (
            asyncio.Task[Any] | None
        ) = None

        self._created_at: datetime = datetime.now(
            timezone.utc
        )

        self._last_snapshot: datetime | None = None

    # ------------------------------------------------------------------
    # Configuration Access
    # ------------------------------------------------------------------

    @property
    def configuration(self) -> LongTermMemoryConfig:
        """
        Return the active engine configuration.
        """

        return self._config

    @property
    def state(self) -> MemoryState:
        """
        Return the current lifecycle state.
        """

        return self._lt_state

    @property
    def statistics(self) -> MemoryStatistics:
        """
        Return the runtime statistics counters.
        """

        return self._statistics

    @property
    def is_ready(self) -> bool:
        """
        True when the engine is ready or running.
        """

        return self._lt_state in (
            MemoryState.READY,
            MemoryState.RUNNING,
        )

    @property
    def is_closed(self) -> bool:
        """
        True when the engine has been closed.
        """

        return self._lt_state == MemoryState.CLOSED

    @property
    def active_backend(self) -> MemoryBackendProtocol | None:
        """
        Return the active storage backend.
        """

        return self._active_backend

    @property
    def memory_count(self) -> int:
        """
        Return the number of runtime entries.
        """

        return len(self._runtime)

    @property
    def backend_names(self) -> list[str]:
        """
        Return the registered backend names.
        """

        return sorted(self._backends)

    @property
    def created_at(self) -> datetime:
        """
        Return the engine creation timestamp.
        """

        return self._created_at

    # ------------------------------------------------------------------
    # Configuration Validation
    # ------------------------------------------------------------------

    def _validate_configuration(self) -> None:
        """
        Validate the active configuration values.
        """

        config = self._config

        if not config.namespace:
            raise ValueError(
                "namespace must not be empty"
            )

        if not isinstance(config.capacity, int) or config.capacity <= 0:
            raise ValueError(
                "capacity must be a positive integer"
            )

        if not isinstance(config.batch_size, int) or config.batch_size <= 0:
            raise ValueError(
                "batch_size must be a positive integer"
            )

        if not 0.0 <= config.similarity_threshold <= 1.0:
            raise ValueError(
                "similarity_threshold must be "
                "between 0.0 and 1.0"
            )

        if config.top_k <= 0:
            raise ValueError(
                "top_k must be positive"
            )

        if config.decay_days <= 0:
            raise ValueError(
                "decay_days must be positive"
            )

        if config.consolidation_interval <= 0:
            raise ValueError(
                "consolidation_interval must be positive"
            )

    def configuration_snapshot(self) -> dict[str, Any]:
        """
        Return a serializable configuration snapshot.
        """

        config = self._config

        return {
            "namespace": config.namespace,
            "backend": config.backend.value,
            "collection": config.collection,
            "capacity": config.capacity,
            "batch_size": config.batch_size,
            "similarity_threshold": (
                config.similarity_threshold
            ),
            "top_k": config.top_k,
            "decay_days": config.decay_days,
            "consolidation_interval": (
                config.consolidation_interval
            ),
            "consolidation_policy": (
                config.consolidation_policy.value
            ),
            "forgetting_policy": (
                config.forgetting_policy.value
            ),
            "embedding_provider": (
                config.embedding_provider is not None
            ),
        }

    # ============================================================
    # Serialization Helpers
    # ============================================================

    def _serialize_entry(
        self,
        entry: MemoryEntry[Any],
    ) -> str:
        """
        Serialize an entry into a JSON payload string.
        """

        return _encode_entry(entry)

    def _deserialize_entry(
        self,
        payload: str,
    ) -> MemoryEntry[Any]:
        """
        Deserialize a JSON payload into a memory entry.
        """

        return _decode_entry(
            payload,
            namespace=self._config.namespace,
        )

    # ============================================================
    # Storage Engine â€” Backend Registry
    # ============================================================

    def register_backend(
        self,
        name: str,
        backend: MemoryBackendProtocol,
    ) -> None:
        """
        Register a storage backend under a name.
        """

        if not name:
            raise ValueError(
                "backend name must not be empty"
            )

        self._backends[name] = backend

        LOGGER.debug(
            "registered backend '%s'",
            name,
        )

    def unregister_backend(
        self,
        name: str,
    ) -> bool:
        """
        Remove a registered backend.

        Returns:
            True if a backend was removed.
        """

        if name not in self._backends:
            return False

        del self._backends[name]

        if self._active_backend is self._backends.get(name):
            self._active_backend = None

        return True

    def has_backend(
        self,
        name: str,
    ) -> bool:
        """
        True when a backend is registered under the name.
        """

        return name in self._backends

    def backend(
        self,
        name: str,
    ) -> MemoryBackendProtocol:
        """
        Return the backend registered under the name.
        """

        if name not in self._backends:
            raise KeyError(
                f"backend not registered: {name}"
            )

        return self._backends[name]

    def set_active_backend(
        self,
        name: str,
    ) -> None:
        """
        Select the active storage backend by name.
        """

        self._active_backend = self.backend(name)

        LOGGER.info(
            "active backend set to '%s'",
            name,
        )

    def _build_default_backend(
        self,
    ) -> MemoryBackendProtocol:
        """
        Construct the default backend from configuration.
        """

        config = self._config

        if config.backend == MemoryBackend.SQLITE:
            return _SqliteBackend(
                path=Path.cwd()
                / "data"
                / f"{config.collection}_{config.namespace}.db",
            )

        if config.backend == MemoryBackend.FILESYSTEM:
            return _FileSystemBackend(
                directory=Path.cwd()
                / "data"
                / config.collection,
            )

        if config.backend == MemoryBackend.REDIS:
            return _RedisBackend(
                collection=config.collection,
            )

        if config.backend == MemoryBackend.POSTGRES:
            return _PostgresBackend(
                collection=config.collection,
            )

        if config.backend == MemoryBackend.CHROMA:
            return _ChromaBackend(
                collection=config.collection,
            )

        raise ValueError(
            f"unsupported backend: {config.backend}"
        )

    async def _connect_backends(
        self,
    ) -> None:
        """
        Connect all registered backends.
        """

        for name, backend in self._backends.items():
            connect = getattr(
                backend,
                "connect",
                None,
            )
            if connect is not None:
                await connect()

            LOGGER.debug(
                "connected backend '%s'",
                name,
            )

    async def _disconnect_backends(
        self,
    ) -> None:
        """
        Disconnect all registered backends.
        """

        for name, backend in self._backends.items():
            disconnect = getattr(
                backend,
                "disconnect",
                None,
            )
            if disconnect is not None:
                await disconnect()

            LOGGER.debug(
                "disconnected backend '%s'",
                name,
            )

    # ============================================================
    # Lifecycle
    # ============================================================

    async def initialize(self) -> None:
        """
        Initialize the engine, connect its storage backends
        and start background maintenance tasks.
        """

        if self._lt_state == MemoryState.READY:
            return

        self._lt_state = MemoryState.INITIALIZING

        try:
            if not self._backends:
                default = self._build_default_backend()

                self.register_backend(
                    str(self._config.backend.value),
                    default,
                )

                self.set_active_backend(
                    str(self._config.backend.value),
                )

            await self._connect_backends()

            try:
                await self.synchronize()
            except Exception:
                LOGGER.exception(
                    "initial synchronize failed"
                )

            await self._start_background_tasks()
        except Exception:
            self._lt_state = MemoryState.CREATED
            raise

        self._lt_state = MemoryState.READY

    async def close(self) -> None:
        """
        Stop background tasks and close all storage backends.
        """

        if self._lt_state == MemoryState.CLOSED:
            return

        await self._stop_background_tasks()

        await self._disconnect_backends()

        self._lt_state = MemoryState.CLOSED

    async def _start_background_tasks(
        self,
    ) -> None:
        """
        Launch periodic consolidation and decay loops.
        """

        if (
            self._consolidation_task is None
            and self._config.consolidation_policy
            == ConsolidationPolicy.PERIODIC
        ):
            self._consolidation_task = (
                asyncio.create_task(
                    self._consolidation_loop()
                )
            )

        if (
            self._decay_task is None
            and self._config.forgetting_policy
            != ForgettingPolicy.NEVER
        ):
            self._decay_task = asyncio.create_task(
                self._decay_loop()
            )

    async def _stop_background_tasks(
        self,
    ) -> None:
        """
        Cancel and await background maintenance tasks.
        """

        for task in (
            self._consolidation_task,
            self._decay_task,
        ):
            if task is None:
                continue

            task.cancel()

        for task in (
            self._consolidation_task,
            self._decay_task,
        ):
            if task is None:
                continue

            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception(
                    "background task error"
                )

        self._consolidation_task = None
        self._decay_task = None

    async def __aenter__(
        self,
    ) -> LongTermMemory:
        """
        Context manager entry: initialize the engine.
        """

        await self.initialize()

        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        """
        Context manager exit: close the engine.
        """

        await self.close()

    # ============================================================
    # Events & Metrics
    # ============================================================

    def on(
        self,
        event: str,
        listener: Callable[..., Any],
    ) -> None:
        """
        Register a listener for an event.

        Arguments:
            event: Event name to listen for.
            listener: Callable invoked as
                ``listener(event, **kwargs)``.
        """

        if not callable(listener):
            raise TypeError(
                "listener must be callable"
            )

        self._listeners[event].append(listener)

    def off(
        self,
        event: str,
        listener: Callable[..., Any],
    ) -> bool:
        """
        Remove a listener for an event.

        Returns:
            True if the listener was removed.
        """

        listeners = self._listeners[event]

        if listener not in listeners:
            return False

        listeners.remove(listener)

        return True

    def clear_listeners(
        self,
        event: str | None = None,
    ) -> None:
        """
        Remove every listener, or every listener
        registered for a single event.
        """

        if event is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event, None)

    def listener_count(
        self,
        event: str | None = None,
    ) -> int:
        """
        Count registered listeners.
        """

        if event is None:
            return sum(
                len(value)
                for value in self._listeners.values()
            )

        return len(self._listeners[event])

    async def emit(
        self,
        event: str,
        **kwargs: Any,
    ) -> None:
        """
        Dispatch an event to every registered listener.

        Listeners returning an awaitable are awaited.
        Listener errors are logged, never raised.
        """

        for listener in self._listeners[event]:
            try:
                result = listener(
                    event,
                    **kwargs,
                )

                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception(
                    "listener error on event '%s'",
                    event,
                )

    # ============================================================
    # Core Helpers
    # ============================================================

    def _require_backend(
        self,
    ) -> MemoryBackendProtocol:
        """
        Return the active backend or raise.
        """

        if self._active_backend is None:
            raise RuntimeError(
                "no active backend; "
                "initialize the engine first"
            )

        return self._active_backend

    def _new_runtime(
        self,
        entry: MemoryEntry[Any],
        *,
        importance: float = 0.5,
    ) -> RuntimeMemory:
        """
        Wrap an entry in a runtime record.
        """

        now = datetime.now(
            timezone.utc
        )

        return RuntimeMemory(
            record=entry,
            created_at=now,
            updated_at=now,
            last_access=now,
            access_count=0,
            importance=importance,
        )

    def _touch(
        self,
        record: RuntimeMemory,
    ) -> None:
        """
        Mark a runtime record as accessed.
        """

        record.last_access = datetime.now(
            timezone.utc
        )

        record.access_count += 1

    def _index_memory_type(
        self,
        key: str,
        memory_type: MemoryType,
        *,
        occurred_at: datetime | None = None,
        tags: Sequence[str] | None = None,
    ) -> None:
        """
        Maintain the per-type index.
        """

        if memory_type == MemoryType.SEMANTIC:
            self._semantic_index.setdefault(
                key,
                [],
            )

        elif memory_type == MemoryType.EPISODIC:
            self._episodic_index[key] = (
                occurred_at
                or datetime.now(
                    timezone.utc
                )
            )

        elif memory_type == MemoryType.KNOWLEDGE:
            node = self._knowledge_index.get(
                key,
            )

            if node is None:
                node = {
                    "subject": key,
                    "object": None,
                    "relations": {},
                }

                self._knowledge_index[key] = node

            if tags:
                relations = node.setdefault(
                    "relations",
                    {},
                )

                for (
                    object_key,
                    names,
                ) in _parse_relation_tags(
                    tags
                ).items():
                    bucket = relations.setdefault(
                        object_key,
                        [],
                    )

                    for name in names:
                        if name not in bucket:
                            bucket.append(name)

        elif memory_type == MemoryType.PROCEDURAL:
            self._procedural_index.setdefault(
                key,
                "",
            )

    async def _embed(
        self,
        text: str,
    ) -> list[float]:
        """
        Embed text with the configured provider, falling
        back to a deterministic hashing embedding.
        """

        provider = self._config.embedding_provider

        if provider is not None:
            result = provider.embed(text)

            if inspect.isawaitable(result):
                result = await result

            if isinstance(result, Sequence):
                return list(result)

        return _fallback_embed(text)

    def set_embedding_provider(
        self,
        provider: EmbeddingProvider | None,
    ) -> None:
        """
        Replace the active embedding provider.
        """

        self._config.embedding_provider = provider

        LOGGER.info(
            "embedding provider updated"
        )

    # ============================================================
    # Core CRUD
    # ============================================================

    async def save(
        self,
        key: str,
        value: Any,
        *,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        importance: float = 0.5,
        source: str = "runtime",
        tags: Iterable[str] | None = None,
        confidence: float = 1.0,
        expires_at: datetime | None = None,
        ttl_days: int | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeMemory:
        """
        Persist a memory entry.

        Parameters
        ----------
        key:
            Unique entry identifier.
        value:
            Serializable value to store.
        memory_type:
            Long-term memory category.
        importance:
            Retention importance in [0.0, 1.0].
        source:
            Origin of the entry.
        tags:
            Additional metadata tags.
        confidence:
            Confidence score in [0.0, 1.0].
        expires_at:
            Explicit expiry timestamp.
        ttl_days:
            Days until the entry expires.
        occurred_at:
            Episodic timestamp of the event.
        """

        backend = self._require_backend()

        key = _validate_key(key)

        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)

        if not 0.0 <= importance <= 1.0:
            raise ValueError(
                "importance must be between 0.0 and 1.0"
            )

        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0.0 and 1.0"
            )

        normalized_tags = _validate_tags(tags)

        now = (
            occurred_at
            or datetime.now(
                timezone.utc
            )
        )

        expiry = expires_at

        if ttl_days is not None:
            expiry = now + timedelta(
                days=ttl_days
            )

        metadata = MemoryMetadata(
            namespace=self._config.namespace,
            source=source,
            tags=[
                _memory_type_tag(memory_type),
                _importance_tag(importance),
                *normalized_tags,
            ],
            confidence=confidence,
            priority=MemoryPriority.NORMAL,
            created_at=now,
            updated_at=now,
            expires_at=expiry,
        )

        entry = MemoryEntry(
            key=key,
            value=value,
            metadata=metadata,
        )

        await backend.save(entry)

        record = RuntimeMemory(
            record=entry,
            created_at=now,
            updated_at=now,
            last_access=now,
            access_count=1,
            importance=importance,
        )

        self._runtime[key] = record

        self._index_memory_type(
            key,
            memory_type,
            occurred_at=now,
            tags=metadata.tags,
        )

        if memory_type == MemoryType.SEMANTIC:
            self._semantic_index[key] = (
                await self._embed(
                    _entry_value_text(entry)
                )
            )

        self._statistics.writes += 1

        await self.emit(
            "entry_saved",
            key=key,
            memory_type=memory_type,
        )

        if (
            self._config.consolidation_policy
            == ConsolidationPolicy.IMMEDIATE
        ):
            await self.consolidate()

        return record

    async def load(
        self,
        key: str,
    ) -> RuntimeMemory | None:
        """
        Load a memory entry by key.
        """

        backend = self._require_backend()

        key = _validate_key(key)

        cached = self._runtime.get(key)

        if cached is not None:
            self._touch(cached)
            self._statistics.reads += 1
            return cached

        entry = await backend.load(key)

        if entry is None:
            return None

        importance = _parse_importance(
            entry.metadata.tags
        )

        memory_type = _parse_memory_type(
            entry.metadata.tags
        )

        record = self._new_runtime(
            entry,
            importance=importance,
        )

        self._runtime[key] = record

        self._index_memory_type(
            key,
            memory_type,
            occurred_at=(
                entry.metadata.created_at
            ),
            tags=entry.metadata.tags,
        )

        if memory_type == MemoryType.SEMANTIC:
            self._semantic_index[key] = (
                await self._embed(
                    _entry_value_text(entry)
                )
            )

        self._touch(record)

        self._statistics.reads += 1

        return record

    async def exists(
        self,
        key: str,
    ) -> bool:
        """
        True when an entry exists under the key.
        """

        backend = self._require_backend()

        key = _validate_key(key)

        if key in self._runtime:
            return True

        return (
            await backend.load(key)
        ) is not None

    async def delete(
        self,
        key: str,
    ) -> bool:
        """
        Delete an entry by key.

        Returns:
            True if the entry existed.
        """

        backend = self._require_backend()

        key = _validate_key(key)

        existed = (
            key in self._runtime
            or (await backend.load(key)) is not None
        )

        await backend.delete(key)

        self._runtime.pop(
            key,
            None,
        )

        self._semantic_index.pop(
            key,
            None,
        )

        self._episodic_index.pop(
            key,
            None,
        )

        self._knowledge_index.pop(
            key,
            None,
        )

        self._procedural_index.pop(
            key,
            None,
        )

        affected_subjects: list[str] = []

        for node_key, node in self._knowledge_index.items():
            relations = node.get(
                "relations",
                {},
            )

            if key in relations:
                del relations[key]
                affected_subjects.append(node_key)

        for subject_key in affected_subjects:
            await self._persist_relations(
                subject_key
            )

        if existed:
            self._statistics.deletions += 1

        await self.emit(
            "entry_deleted",
            key=key,
        )

        return existed

    async def update(
        self,
        key: str,
        value: Any,
        *,
        importance: float | None = None,
        tags: Iterable[str] | None = None,
        confidence: float | None = None,
    ) -> RuntimeMemory:
        """
        Update the value and optional metadata of an entry.

        Internal tags (type, importance, relations) are
        preserved automatically.
        """

        backend = self._require_backend()

        key = _validate_key(key)

        existing = await self.load(key)

        if existing is None:
            raise KeyError(
                f"entry not found: {key}"
            )

        entry = existing.record

        metadata = entry.metadata

        rel_tags = [
            tag
            for tag in metadata.tags
            if tag.startswith("lt:rel:")
        ]

        if tags is not None:
            normalized = _validate_tags(tags)

            provided_lt = {
                tag
                for tag in normalized
                if tag.startswith("lt:")
            }

            if any(
                tag.startswith("lt:type:")
                for tag in normalized
            ):
                metadata.tags = [
                    *normalized,
                    *[
                        tag
                        for tag in rel_tags
                        if tag not in provided_lt
                    ],
                ]
            else:
                memory_type = _parse_memory_type(
                    entry.metadata.tags
                )

                metadata.tags = [
                    _memory_type_tag(memory_type),
                    _importance_tag(
                        existing.importance
                    ),
                    *[
                        tag
                        for tag in normalized
                        if not tag.startswith("lt:")
                    ],
                    *[
                        tag
                        for tag in rel_tags
                        if tag not in provided_lt
                    ],
                ]

        if confidence is not None:
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(
                    "confidence must be between 0.0 and 1.0"
                )

            metadata.confidence = confidence

        if importance is not None:
            if not 0.0 <= importance <= 1.0:
                raise ValueError(
                    "importance must be between 0.0 and 1.0"
                )

            metadata.tags = [
                _importance_tag(importance)
                if tag.startswith(
                    "lt:importance:"
                )
                else tag
                for tag in metadata.tags
            ]

        metadata.updated_at = datetime.now(
            timezone.utc
        )

        updated_entry = MemoryEntry(
            key=entry.key,
            value=value,
            metadata=metadata,
            identifier=entry.identifier,
        )

        await backend.save(updated_entry)

        now = datetime.now(
            timezone.utc
        )

        existing.record = updated_entry
        existing.updated_at = now
        existing.last_access = now

        if importance is not None:
            existing.importance = importance

        self._runtime[key] = existing

        memory_type = _parse_memory_type(
            metadata.tags
        )

        self._index_memory_type(
            key,
            memory_type,
            occurred_at=self._episodic_index.get(
                key,
            ),
            tags=metadata.tags,
        )

        if memory_type == MemoryType.SEMANTIC:
            self._semantic_index[key] = (
                await self._embed(
                    _entry_value_text(updated_entry)
                )
            )

        self._statistics.updates += 1

        await self.emit(
            "entry_updated",
            key=key,
        )

        return existing

    async def save_batch(
        self,
        entries: Iterable[
            tuple[
                str,
                Any,
            ]
        ],
        *,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        importance: float = 0.5,
    ) -> int:
        """
        Persist multiple entries.

        Returns:
            The number of saved entries.
        """

        count = 0

        items: Iterable[
            tuple[str, Any]
        ] = (
            entries.items()
            if isinstance(entries, Mapping)
            else entries
        )

        for key, value in items:
            await self.save(
                key,
                value,
                memory_type=memory_type,
                importance=importance,
            )

            count += 1

            if (
                count % self._config.batch_size
                == 0
            ):
                await self.synchronize()

        return count

    async def load_many(
        self,
        keys: Iterable[str],
    ) -> list[RuntimeMemory]:
        """
        Load multiple entries by key.
        """

        records: list[RuntimeMemory] = []

        for key in keys:
            record = await self.load(key)
            if record is not None:
                records.append(record)

        return records

    async def delete_many(
        self,
        keys: Iterable[str],
    ) -> int:
        """
        Delete multiple entries.

        Returns:
            The number of deleted entries.
        """

        count = 0

        for key in keys:
            if await self.delete(key):
                count += 1

        return count

    async def count(
        self,
    ) -> int:
        """
        Return the number of persisted entries.
        """

        return len(
            await self.keys()
        )

    async def keys(
        self,
    ) -> list[str]:
        """
        Return all persisted entry keys.
        """

        backend = self._require_backend()

        return sorted(
            set(await backend.keys())
        )

    # ============================================================
    # Semantic Memory
    # ============================================================

    async def semantic_search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Search semantic memory by embedding similarity.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of results. Defaults to
            configuration when omitted.
        threshold:
            Minimum similarity in [0.0, 1.0]. Defaults to
            configuration when omitted.
        """

        if not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        self._require_backend()

        limit = (
            top_k
            if top_k is not None
            else self._config.top_k
        )

        cutoff = (
            threshold
            if threshold is not None
            else self._config.similarity_threshold
        )

        scored: list[
            tuple[float, str]
        ] = []

        for key in self._semantic_index:
            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await self._require_backend().load(
                    key
                )
            )

            if entry is None:
                continue

            similarity = _token_similarity(
                query,
                _entry_value_text(entry),
            )

            if similarity >= cutoff:
                scored.append(
                    (
                        similarity,
                        key,
                    )
                )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        scored = scored[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for similarity, key in scored:
            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await self._require_backend().load(
                    key
                )
            )

            if entry is None:
                continue

            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=similarity,
                    distance=1.0 - similarity,
                )
            )

        self._statistics.searches += 1

        return results

    # ============================================================
    # Episodic Memory
    # ============================================================

    async def timeline(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        ascending: bool = False,
    ) -> list[MemorySearchResult[Any]]:
        """
        Return episodic entries in chronological order.

        Parameters
        ----------
        since:
            Only entries at or after this timestamp.
        until:
            Only entries at or before this timestamp.
        limit:
            Maximum number of results.
        ascending:
            True for oldest-first ordering.
        """

        self._require_backend()

        pairs = list(
            self._episodic_index.items()
        )

        filtered: list[
            tuple[datetime, str]
        ] = []

        for key, occurred_at in pairs:
            if (
                since is not None
                and occurred_at < since
            ):
                continue

            if (
                until is not None
                and occurred_at > until
            ):
                continue

            filtered.append(
                (
                    occurred_at,
                    key,
                )
            )

        filtered.sort(
            key=lambda item: item[0],
            reverse=not ascending,
        )

        if limit is not None:
            filtered = filtered[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for occurred_at, key in filtered:
            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await self._require_backend().load(
                    key
                )
            )

            if entry is None:
                continue

            similarity = (
                occurred_at.timestamp()
                - datetime.fromtimestamp(0, tz=timezone.utc).timestamp()
            ) / max(
                occurred_at.timestamp(),
                1.0,
            )

            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=similarity,
                    distance=1.0 - similarity,
                )
            )

        self._statistics.searches += 1

        return results

    async def episodic_search(
        self,
        query: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Keyword-search episodic memory with an optional
        time window.
        """

        if not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        self._require_backend()

        needle = query.lower()

        ranked: list[
            tuple[int, datetime, str]
        ] = []

        for key in self._episodic_index:
            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await self._require_backend().load(
                    key
                )
            )

            if entry is None:
                continue

            text = _entry_text(entry).lower()

            if needle not in text:
                continue

            occurred_at = self._episodic_index[key]

            if (
                since is not None
                and occurred_at < since
            ):
                continue

            if (
                until is not None
                and occurred_at > until
            ):
                continue

            ranked.append(
                (
                    text.count(needle),
                    occurred_at,
                    key,
                )
            )

        ranked.sort(
            key=lambda item: (
                item[0],
                item[1].timestamp(),
            ),
            reverse=True,
        )

        if limit is not None:
            ranked = ranked[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for hits, occurred_at, key in ranked:
            record = self._runtime[key]

            results.append(
                MemorySearchResult(
                    entry=record.record,
                    score=1.0 / (1.0 + hits),
                    distance=hits / (1.0 + hits),
                )
            )

        self._statistics.searches += 1

        return results

    async def recent_episodes(
        self,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Return the most recent episodic entries.
        """

        return await self.timeline(
            limit=limit,
            ascending=False,
        )

    # ============================================================
    # Knowledge Memory
    # ============================================================

    def _knowledge_node(
        self,
        key: str,
    ) -> dict[str, Any]:
        """
        Return or create the knowledge node for a key.
        """

        node = self._knowledge_index.get(
            key
        )

        if node is None:
            node = {
                "subject": key,
                "object": None,
                "relations": {},
            }

            self._knowledge_index[key] = node

        return node

    async def _persist_relations(
        self,
        subject_key: str,
    ) -> None:
        """
        Persist a subject's knowledge edges as metadata tags.
        """

        node = self._knowledge_index.get(
            subject_key
        )

        if node is None:
            return

        relations = node.get(
            "relations",
            {},
        )

        edge_tags = [
            _relation_tag(
                object_key,
                relation,
            )
            for object_key, names in relations.items()
            for relation in names
        ]

        backend = self._require_backend()

        record = self._runtime.get(
            subject_key
        )

        entry = (
            record.record
            if record is not None
            else await backend.load(subject_key)
        )

        if entry is None:
            return

        entry.metadata.tags = [
            *[
                tag
                for tag in entry.metadata.tags
                if not tag.startswith("lt:rel:")
            ],
            *edge_tags,
        ]

        await backend.save(entry)

    async def link(
        self,
        subject_key: str,
        relation: str,
        object_key: str,
    ) -> None:
        """
        Add a subject -> relation -> object edge in the
        knowledge graph. Edges are persisted as metadata
        tags and survive restarts.
        """

        subject_key = _validate_key(
            subject_key
        )

        object_key = _validate_key(
            object_key
        )

        if not relation.strip():
            raise ValueError(
                "relation must not be empty"
            )

        if subject_key not in self._knowledge_index:
            raise KeyError(
                f"knowledge entry not found: {subject_key}"
            )

        if object_key not in self._knowledge_index:
            raise KeyError(
                f"knowledge entry not found: {object_key}"
            )

        node = self._knowledge_node(
            subject_key
        )

        relations = node.setdefault(
            "relations",
            {},
        )

        bucket = relations.setdefault(
            object_key,
            [],
        )

        if relation not in bucket:
            bucket.append(relation)

        await self._persist_relations(
            subject_key
        )

    async def unlink(
        self,
        subject_key: str,
        relation: str,
        object_key: str,
    ) -> bool:
        """
        Remove a subject -> relation -> object edge.

        Returns:
            True when the edge existed.
        """

        subject_key = _validate_key(
            subject_key
        )

        object_key = _validate_key(
            object_key
        )

        node = self._knowledge_index.get(
            subject_key
        )

        if node is None:
            return False

        relations = node.get(
            "relations",
            {},
        )

        bucket = relations.get(
            object_key,
            [],
        )

        if relation not in bucket:
            return False

        bucket.remove(relation)

        if not bucket:
            relations.pop(
                object_key,
                None,
            )

        await self._persist_relations(
            subject_key
        )

        return True

    async def knowledge_search(
        self,
        query: str,
        *,
        subject: str | None = None,
        relation: str | None = None,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Keyword-search knowledge entries with optional
        subject and relation filters.
        """

        if not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        backend = self._require_backend()

        needle = query.lower()

        scored: list[
            tuple[int, str]
        ] = []

        for key, node in self._knowledge_index.items():
            if (
                subject is not None
                and key != subject
            ):
                continue

            if relation is not None:
                names = [
                    name
                    for names in node.get(
                        "relations",
                        {},
                    ).values()
                    for name in names
                ]

                if relation not in names:
                    continue

            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await backend.load(key)
            )

            if entry is None:
                continue

            text = _entry_text(entry).lower()

            if needle not in text:
                continue

            scored.append(
                (
                    text.count(needle),
                    key,
                )
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if limit is not None:
            scored = scored[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for hits, key in scored:
            record = self._runtime[key]

            results.append(
                MemorySearchResult(
                    entry=record.record,
                    score=1.0 / (1.0 + hits),
                    distance=hits / (1.0 + hits),
                )
            )

        self._statistics.searches += 1

        return results

    def knowledge_graph(
        self,
    ) -> list[tuple[str, str, str]]:
        """
        Return every (subject, relation, object) triple.
        """

        triples: list[
            tuple[str, str, str]
        ] = []

        for subject, node in sorted(
            self._knowledge_index.items()
        ):
            for (
                object_key,
                names,
            ) in node.get(
                "relations",
                {},
            ).items():
                for name in names:
                    triples.append(
                        (
                            subject,
                            name,
                            object_key,
                        )
                    )

        return triples

    def entities(
        self,
    ) -> list[str]:
        """
        Return the sorted knowledge entity keys.
        """

        return sorted(
            self._knowledge_index
        )

    def relations_of(
        self,
        subject_key: str,
    ) -> list[tuple[str, str]]:
        """
        Return (object, relation) pairs for a subject.
        """

        subject_key = _validate_key(
            subject_key
        )

        node = self._knowledge_index.get(
            subject_key
        )

        if node is None:
            return []

        relations = node.get(
            "relations",
            {},
        )

        return [
            (
                object_key,
                relation,
            )
            for object_key, names in relations.items()
            for relation in names
        ]

    # ============================================================
    # Procedural Memory
    # ============================================================

    async def procedural_search(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Keyword-search procedural entries.
        """

        if not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        backend = self._require_backend()

        needle = query.lower()

        scored: list[
            tuple[int, str]
        ] = []

        for key in self._procedural_index:
            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await backend.load(key)
            )

            if entry is None:
                continue

            text = _entry_text(entry).lower()

            if needle not in text:
                continue

            scored.append(
                (
                    text.count(needle),
                    key,
                )
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if limit is not None:
            scored = scored[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for hits, key in scored:
            record = self._runtime[key]

            results.append(
                MemorySearchResult(
                    entry=record.record,
                    score=1.0 / (1.0 + hits),
                    distance=hits / (1.0 + hits),
                )
            )

        self._statistics.searches += 1

        return results

    def procedure_steps(
        self,
        key: str,
    ) -> list[str]:
        """
        Return the ordered steps of a stored procedure.
        """

        key = _validate_key(key)

        if key not in self._procedural_index:
            raise KeyError(
                f"procedural entry not found: {key}"
            )

        record = self._runtime.get(key)

        if record is None:
            raise KeyError(
                f"procedural entry not loaded: {key}"
            )

        value = record.record.value

        if not isinstance(value, list):
            raise TypeError(
                "procedural entry value must be a list of steps"
            )

        return list(value)

    def procedures(
        self,
    ) -> list[str]:
        """
        Return the sorted procedural entry keys.
        """

        return sorted(
            self._procedural_index
        )

    # ============================================================
    # Retrieval
    # ============================================================

    def _matches_filters(
        self,
        entry: MemoryEntry[Any],
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
        priority: MemoryPriority | None = None,
        importance_min: float | None = None,
        importance_max: float | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> bool:
        """
        Return True when an entry satisfies every filter.
        """

        metadata = entry.metadata

        if (
            memory_type is not None
            and _parse_memory_type(metadata.tags) != memory_type
        ):
            return False

        if tags is not None and not all(
            tag in metadata.tags
            for tag in tags
        ):
            return False

        if (
            namespace is not None
            and metadata.namespace != namespace
        ):
            return False

        if (
            priority is not None
            and metadata.priority != priority
        ):
            return False

        importance = _parse_importance(
            metadata.tags
        )

        if (
            importance_min is not None
            and importance < importance_min
        ):
            return False

        if (
            importance_max is not None
            and importance > importance_max
        ):
            return False

        if (
            created_after is not None
            and metadata.created_at < created_after
        ):
            return False

        if (
            created_before is not None
            and metadata.created_at > created_before
        ):
            return False

        return True

    async def _all_keys(
        self,
    ) -> set[str]:
        """
        Return the union of known entry keys.
        """

        keys: set[str] = set(
            self._runtime
        )

        try:
            keys.update(
                await self._require_backend().keys()
            )
        except NotImplementedError:
            pass

        return keys

    async def _load_for_search(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        """
        Load an entry into the runtime cache, returning
        None when it no longer exists.
        """

        record = self._runtime.get(key)

        if record is not None:
            return record.record

        entry = await self._require_backend().load(
            key
        )

        if entry is None:
            return None

        memory_type = _parse_memory_type(
            entry.metadata.tags
        )

        self._index_memory_type(
            key,
            memory_type,
            occurred_at=(
                entry.metadata.created_at
            ),
            tags=entry.metadata.tags,
        )

        return entry

    async def search(
        self,
        query: str,
        *,
        mode: SearchMode = SearchMode.SEMANTIC,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
        priority: MemoryPriority | None = None,
        importance_min: float | None = None,
        importance_max: float | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = DEFAULT_TOP_K,
        threshold: float | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Multi-mode retrieval across all memory types with
        metadata filters.
        """

        if not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        backend = self._require_backend()

        if mode == SearchMode.EXACT:
            results = await self._exact_prefix_search(
                query,
                exact=True,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
                limit=limit,
            )

            self._statistics.searches += 1

            return results

        if mode == SearchMode.PREFIX:
            results = await self._exact_prefix_search(
                query,
                exact=False,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
                limit=limit,
            )

            self._statistics.searches += 1

            return results

        if mode == SearchMode.SEMANTIC:
            results = await self._semantic_search_all(
                query,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
                limit=limit,
                threshold=threshold,
            )

            self._statistics.searches += 1

            return results

        # HYBRID: exact/prefix hits first, then semantic fill
        keyword_results = await self._exact_prefix_search(
            query,
            exact=False,
            memory_type=memory_type,
            tags=tags,
            namespace=namespace,
            priority=priority,
            importance_min=importance_min,
            importance_max=importance_max,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )

        seen: set[str] = {
            result.entry.key
            for result in keyword_results
        }

        remaining = limit - len(keyword_results)

        if remaining > 0:
            semantic_results = await self._semantic_search_all(
                query,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
                limit=remaining,
                threshold=threshold,
            )

            keyword_results.extend(
                result
                for result in semantic_results
                if result.entry.key not in seen
            )

        self._statistics.searches += 1

        return keyword_results

    async def _exact_prefix_search(
        self,
        query: str,
        *,
        exact: bool,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
        priority: MemoryPriority | None = None,
        importance_min: float | None = None,
        importance_max: float | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int,
    ) -> list[MemorySearchResult[Any]]:
        """
        Exact or prefix keyword matching over entry text.
        """

        needle = query.lower()

        matches: list[
            tuple[MemoryEntry[Any], str]
        ] = []

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            if not self._matches_filters(
                entry,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
            ):
                continue

            text = _entry_value_text(entry)

            haystack = text.lower()

            if exact:
                matched = haystack == needle
            else:
                matched = needle in haystack

            if matched:
                matches.append((entry, text))

        matches.sort(
            key=lambda item: item[1].lower(),
        )

        results: list[
            MemorySearchResult[Any]
        ] = []

        for entry, _text in matches[:limit]:
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=1.0,
                    distance=0.0,
                )
            )

        return results

    async def _semantic_search_all(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
        priority: MemoryPriority | None = None,
        importance_min: float | None = None,
        importance_max: float | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int,
        threshold: float | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Embedding-based search across every entry.
        """

        effective_threshold = (
            threshold
            if threshold is not None
            else DEFAULT_SIMILARITY_THRESHOLD
        )

        candidates: list[
            tuple[float, MemoryEntry[Any]]
        ] = []

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            if not self._matches_filters(
                entry,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
            ):
                continue

            similarity = _token_similarity(
                query,
                _entry_value_text(entry),
            )

            if similarity < effective_threshold:
                continue

            candidates.append(
                (
                    similarity,
                    entry,
                )
            )

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        results: list[
            MemorySearchResult[Any]
        ] = []

        for similarity, entry in candidates[:limit]:
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=similarity,
                    distance=1.0 - similarity,
                )
            )

        return results

    async def search_by_metadata(
        self,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
        priority: MemoryPriority | None = None,
        importance_min: float | None = None,
        importance_max: float | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Return entries matching metadata filters, ordered by
        access count descending.
        """

        matches: list[
            tuple[int, MemoryEntry[Any]]
        ] = []

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            if not self._matches_filters(
                entry,
                memory_type=memory_type,
                tags=tags,
                namespace=namespace,
                priority=priority,
                importance_min=importance_min,
                importance_max=importance_max,
                created_after=created_after,
                created_before=created_before,
            ):
                continue

            record = self._runtime[key]

            matches.append(
                (
                    record.access_count,
                    entry,
                )
            )

        matches.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if limit is not None:
            matches = matches[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for _access_count, entry in matches:
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=1.0,
                    distance=0.0,
                )
            )

        return results

    async def entity_search(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Search knowledge entities by name or key.
        """

        if not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        backend = self._require_backend()

        needle = query.lower()

        scored: list[
            tuple[int, MemoryEntry[Any]]
        ] = []

        for key in self._knowledge_index:
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            text = _entry_text(entry).lower()

            if needle not in text:
                continue

            scored.append(
                (
                    text.count(needle),
                    entry,
                )
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if limit is not None:
            scored = scored[:limit]

        results: list[
            MemorySearchResult[Any]
        ] = []

        for hits, entry in scored:
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=1.0 / (1.0 + hits),
                    distance=hits / (1.0 + hits),
                )
            )

        return results

    # ============================================================
    # Ranking
    # ============================================================

    def _recency_score(
        self,
        entry: MemoryEntry[Any],
        *,
        now: datetime | None = None,
        half_life_days: float = DEFAULT_DECAY_DAYS,
    ) -> float:
        """
        Exponential recency score in [0.0, 1.0]. Entries
        updated recently approach 1.0.
        """

        now = (
            now
            or datetime.now(timezone.utc)
        )

        reference = (
            entry.metadata.updated_at
            or entry.metadata.created_at
        )

        age_days = max(
            0.0,
            (now - reference).total_seconds()
            / 86400.0,
        )

        return 0.5 ** (
            age_days
            / max(1.0, half_life_days)
        )

    async def rank_results(
        self,
        query: str,
        results: Sequence[MemorySearchResult[Any]],
        *,
        weights: dict[str, float] | None = None,
        top_k: int | None = None,
        now: datetime | None = None,
    ) -> list[MemorySearchResult[Any]]:
        """
        Re-rank results by a weighted blend of their
        existing (semantic) score and recency.
        """

        weights = weights or {
            "semantic": 1.0,
            "recency": 0.5,
        }

        semantic_weight = weights.get(
            "semantic",
            1.0,
        )

        recency_weight = weights.get(
            "recency",
            0.0,
        )

        divisor = (
            semantic_weight + recency_weight
            if (
                semantic_weight + recency_weight
            )
            > 0.0
            else 1.0
        )

        scored: list[
            tuple[float, MemorySearchResult[Any]]
        ] = []

        for result in results:
            recency = self._recency_score(
                result.entry,
                now=now,
            )

            combined = (
                semantic_weight * result.score
                + recency_weight * recency
            ) / divisor

            scored.append(
                (
                    combined,
                    result,
                )
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        ranked = [
            result
            for _combined, result in scored
        ]

        if top_k is not None:
            ranked = ranked[:top_k]

        return ranked

    # ============================================================
    # Context Building
    # ============================================================

    async def build_context(
        self,
        query: str | None = None,
        *,
        limit: int = DEFAULT_TOP_K,
        include_types: Sequence[MemoryType] | None = None,
        threshold: float | None = None,
    ) -> str:
        """
        Build a formatted context block for an agent prompt.

        With a query, context is drawn from semantic
        retrieval; otherwise recent memories are used.
        """

        if limit <= 0:
            raise ValueError(
                "limit must be positive"
            )

        if query is not None and not query.strip():
            raise ValueError(
                "query must not be empty"
            )

        if query is not None:
            results = await self.search(
                query,
                mode=SearchMode.SEMANTIC,
                limit=limit,
                threshold=threshold,
            )
        else:
            results = await self.recent_entries(
                limit
            )

        type_filter = (
            set(include_types)
            if include_types is not None
            else None
        )

        lines: list[str] = []

        lines.append(
            f"# Context: {query or 'recent'}"
        )

        for result in results:
            entry = result.entry

            memory_type = _parse_memory_type(
                entry.metadata.tags
            )

            if (
                type_filter is not None
                and memory_type not in type_filter
            ):
                continue

            lines.append(
                f"- [{entry.key}] "
                f"({memory_type.value}, "
                f"score={result.score:.3f}) "
                f"{_entry_value_text(entry)}"
            )

        return "\n".join(lines)

    async def recent_entries(
        self,
        limit: int = DEFAULT_TOP_K,
    ) -> list[MemorySearchResult[Any]]:
        """
        Return the most recently updated entries.
        """

        if limit <= 0:
            raise ValueError(
                "limit must be positive"
            )

        backend = self._require_backend()

        loaded: list[
            tuple[datetime, MemoryEntry[Any]]
        ] = []

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            loaded.append(
                (
                    entry.metadata.updated_at,
                    entry,
                )
            )

        loaded.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        results: list[
            MemorySearchResult[Any]
        ] = []

        for _updated_at, entry in loaded[:limit]:
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=1.0,
                    distance=0.0,
                )
            )

        return results

    # ============================================================
    # Maintenance, Sync & Snapshots
    # ============================================================

    async def synchronize(
        self,
    ) -> int:
        """
        Rebuild in-memory indexes from the backend.
        Returns the number of entries indexed.
        """

        backend = self._require_backend()

        try:
            keys = await backend.keys()
        except NotImplementedError:
            keys = list(self._runtime)

        count = 0

        for key in sorted(keys):
            if key in self._runtime:
                continue

            entry = await backend.load(key)

            if entry is None:
                continue

            memory_type = _parse_memory_type(
                entry.metadata.tags
            )

            self._index_memory_type(
                key,
                memory_type,
                occurred_at=entry.metadata.created_at,
                tags=entry.metadata.tags,
            )

            self._runtime[key] = self._new_runtime(
                entry,
                importance=_parse_importance(
                    entry.metadata.tags
                ),
            )

            if memory_type == MemoryType.SEMANTIC:
                self._semantic_index[key] = (
                    await self._embed(
                        _entry_value_text(entry)
                    )
                )

            count += 1

        return count

    async def compact(
        self,
    ) -> int:
        """
        Remove expired entries and release backend storage.
        Returns the number of entries removed.
        """

        backend = self._require_backend()

        now = datetime.now(timezone.utc)

        removed = 0

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            expires_at = entry.metadata.expires_at

            if (
                expires_at is not None
                and expires_at <= now
            ):
                await self.delete(key)
                removed += 1

        try:
            await backend.compact()
        except NotImplementedError:
            pass

        return removed

    async def export(
        self,
    ) -> dict[str, Any]:
        """
        Export the complete long-term memory state.
        """

        payload: dict[str, Any] = {
            "version": SERIALIZATION_VERSION,
            "engine": "long_term",
            "namespace": self._config.namespace,
            "collection": self._config.collection,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "entries": [],
            "statistics": self._statistics.as_dict(),
        }

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            payload["entries"].append(
                _encode_entry(entry)
            )

        return payload

    async def import_data(
        self,
        payload: Mapping[str, Any],
    ) -> int:
        """
        Restore entries from an exported payload.
        Returns the number of entries imported.
        """

        backend = self._require_backend()

        entries = payload.get("entries", [])

        if not isinstance(entries, list):
            raise ValueError(
                "payload 'entries' must be a list"
            )

        imported = 0

        for encoded in entries:
            try:
                entry = _decode_entry(encoded)
            except Exception:
                continue

            await backend.save(entry)

            self._index_memory_type(
                entry.key,
                _parse_memory_type(
                    entry.metadata.tags
                ),
                occurred_at=entry.metadata.created_at,
                tags=entry.metadata.tags,
            )

            self._runtime[entry.key] = self._new_runtime(
                entry,
                importance=_parse_importance(
                    entry.metadata.tags
                ),
            )

            if _parse_memory_type(
                entry.metadata.tags
            ) == MemoryType.SEMANTIC:
                self._semantic_index[entry.key] = (
                    await self._embed(
                        _entry_value_text(entry)
                    )
                )

            imported += 1

        self._statistics.imports += 1

        return imported

    async def export_json(
        self,
        path: str | Path,
    ) -> dict[str, Any]:
        """
        Export state to a JSON file.
        """

        payload = await self.export()

        target = Path(path)

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            json.dumps(
                payload,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._statistics.exports += 1

        return payload

    async def import_json(
        self,
        path: str | Path,
    ) -> int:
        """
        Import entries from a JSON file.
        """

        payload = json.loads(
            Path(path).read_text(
                encoding="utf-8"
            )
        )

        return await self.import_data(payload)

    async def snapshot(
        self,
        path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Capture a durable snapshot of the current state.
        Writes to ``data/snapshot_<collection>.json`` when
        no path is given.
        """

        payload = await self.export()

        target = (
            Path(path)
            if path is not None
            else Path("data")
            / f"snapshot_{self._config.collection}.json"
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            json.dumps(
                payload,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._statistics.snapshots += 1

        await self.emit(
            "snapshot_created",
            path=str(target),
            entries=len(payload["entries"]),
        )

        return payload

    async def backup(
        self,
        path: str | Path,
    ) -> dict[str, Any]:
        """
        Create a full backup at the given path.
        """

        payload = await self.export()

        target = Path(path)

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            json.dumps(
                payload,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._statistics.exports += 1

        await self.emit(
            "backup_created",
            path=str(target),
            entries=len(payload["entries"]),
        )

        return payload

    async def restore(
        self,
        path: str | Path,
    ) -> int:
        """
        Restore entries from a backup file.
        """

        return await self.import_json(path)

    def health(
        self,
    ) -> dict[str, Any]:
        """
        Report engine health status.
        """

        backend_ready = (
            self._active_backend is not None
        )

        return {
            "healthy": (
                self._lt_state == MemoryState.READY
                and backend_ready
            ),
            "state": self._lt_state.value,
            "backend_ready": backend_ready,
            "entries": len(self._runtime),
            "indexes": {
                "semantic": len(self._semantic_index),
                "episodic": len(self._episodic_index),
                "knowledge": len(self._knowledge_index),
                "procedural": len(self._procedural_index),
            },
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    def metrics(
        self,
    ) -> dict[str, Any]:
        """
        Return the statistics snapshot.
        """

        return self._statistics.as_dict()

    # ============================================================
    # Consolidation & Decay
    # ============================================================

    async def consolidate(
        self,
        *,
        threshold: float | None = None,
    ) -> int:
        """
        Merge similar semantic entries into the strongest
        representative. Returns the number of merged entries.
        """

        backend = self._require_backend()

        cutoff = (
            threshold
            if threshold is not None
            else DEFAULT_SIMILARITY_THRESHOLD
        )

        entries: list[
            tuple[str, list[float], MemoryEntry[Any]]
        ] = []

        for key, vector in list(
            self._semantic_index.items()
        ):
            record = self._runtime.get(key)

            entry = (
                record.record
                if record is not None
                else await backend.load(key)
            )

            if entry is None:
                continue

            entries.append(
                (
                    key,
                    vector,
                    entry,
                )
            )

        merged_total = 0

        while entries:
            (
                rep_key,
                rep_vector,
                rep_entry,
            ) = entries.pop(0)

            rep_importance = _parse_importance(
                rep_entry.metadata.tags
            )

            merged_group: list[
                tuple[str, list[float], MemoryEntry[Any]]
            ] = []

            for candidate in list(entries):
                (
                    cand_key,
                    cand_vector,
                    cand_entry,
                ) = candidate

                similarity = _cosine_similarity(
                    rep_vector,
                    cand_vector,
                )

                if similarity < cutoff:
                    continue

                entries.remove(candidate)

                cand_importance = _parse_importance(
                    cand_entry.metadata.tags
                )

                if cand_importance > rep_importance:
                    merged_group.append(
                        (
                            rep_key,
                            rep_vector,
                            rep_entry,
                        )
                    )

                    (
                        rep_key,
                        rep_vector,
                        rep_entry,
                    ) = candidate

                    rep_importance = cand_importance
                else:
                    merged_group.append(candidate)

            if not merged_group:
                continue

            for key, _vector, candidate_entry in merged_group:
                rep_entry.metadata.tags = list(
                    dict.fromkeys(
                        [
                            *rep_entry.metadata.tags,
                            *candidate_entry.metadata.tags,
                        ]
                    )
                )

                await backend.delete(key)

                self._runtime.pop(
                    key,
                    None,
                )

                self._semantic_index.pop(
                    key,
                    None,
                )

            rep_entry.metadata.updated_at = datetime.now(
                timezone.utc
            )

            await backend.save(rep_entry)

            self._semantic_index[rep_key] = (
                await self._embed(
                    _entry_value_text(rep_entry)
                )
            )

            self._statistics.consolidations += 1

            merged_total += len(merged_group)

            await self.emit(
                "consolidated",
                key=rep_key,
                merged=len(merged_group),
            )

        return merged_total

    async def promote(
        self,
        key: str,
        *,
        reason: str = "user",
    ) -> MemoryEntry[Any]:
        """
        Increase an entry's importance.
        """

        key = _validate_key(key)

        backend = self._require_backend()

        record = self._runtime.get(key)

        entry = (
            record.record
            if record is not None
            else await backend.load(key)
        )

        if entry is None:
            raise KeyError(
                f"entry not found: {key}"
            )

        importance = _parse_importance(
            entry.metadata.tags
        )

        new_importance = min(
            1.0,
            importance + PROMOTE_STEP,
        )

        entry.metadata.tags = [
            tag
            for tag in entry.metadata.tags
            if not tag.startswith("lt:importance:")
        ]

        entry.metadata.tags.append(
            _importance_tag(new_importance)
        )

        entry.metadata.updated_at = datetime.now(
            timezone.utc
        )

        await backend.save(entry)

        self._index_memory_type(
            key,
            _parse_memory_type(
                entry.metadata.tags
            ),
            occurred_at=self._episodic_index.get(key),
            tags=entry.metadata.tags,
        )

        if _parse_memory_type(
            entry.metadata.tags
        ) == MemoryType.SEMANTIC:
            self._semantic_index[key] = (
                await self._embed(
                    _entry_value_text(entry)
                )
            )

        self._statistics.promotions += 1

        await self.emit(
            "entry_promoted",
            key=key,
            importance=new_importance,
            reason=reason,
        )

        return entry

    async def decay(
        self,
        *,
        force: bool = False,
        days: float | None = None,
    ) -> int:
        """
        Halve the importance of entries untouched for the
        decay period. Returns the number of decayed entries.
        """

        self._require_backend()

        cutoff_days = (
            days
            if days is not None
            else DEFAULT_DECAY_DAYS
        )

        now = datetime.now(timezone.utc)

        count = 0

        for key in await self._all_keys():
            entry = await self._load_for_search(key)

            if entry is None:
                continue

            importance = _parse_importance(
                entry.metadata.tags
            )

            if importance <= IMPORTANCE_FLOOR:
                continue

            if not force:
                last_touched = (
                    entry.metadata.updated_at
                    or entry.metadata.created_at
                )

                age_days = max(
                    0.0,
                    (now - last_touched).total_seconds()
                    / 86400.0,
                )

                if age_days < cutoff_days:
                    continue

            new_importance = max(
                IMPORTANCE_FLOOR,
                importance * DECAY_FACTOR,
            )

            entry.metadata.tags = [
                tag
                for tag in entry.metadata.tags
                if not tag.startswith("lt:importance:")
            ]

            entry.metadata.tags.append(
                _importance_tag(new_importance)
            )

            entry.metadata.updated_at = now

            await self._require_backend().save(entry)

            self._index_memory_type(
                key,
                _parse_memory_type(
                    entry.metadata.tags
                ),
                occurred_at=self._episodic_index.get(key),
                tags=entry.metadata.tags,
            )

            if _parse_memory_type(
                entry.metadata.tags
            ) == MemoryType.SEMANTIC:
                self._semantic_index[key] = (
                    await self._embed(
                        _entry_value_text(entry)
                    )
                )

            self._statistics.decays += 1

            count += 1

            await self.emit(
                "entry_decayed",
                key=key,
                importance=new_importance,
            )

        return count

    # ============================================================
    # Background Maintenance Loops
    # ============================================================

    async def _consolidation_loop(
        self,
    ) -> None:
        """
        Periodic consolidation background task.
        """

        interval = max(
            self._config.consolidation_interval,
            1,
        )

        while True:
            await asyncio.sleep(interval)

            try:
                await self.consolidate()
            except Exception:
                LOGGER.exception(
                    "periodic consolidation failed"
                )

    async def _decay_loop(
        self,
    ) -> None:
        """
        Periodic decay background task.
        """

        interval = max(
            self._config.consolidation_interval,
            1,
        )

        while True:
            await asyncio.sleep(interval)

            try:
                await self.decay()
            except Exception:
                LOGGER.exception(
                    "periodic decay failed"
                )

# ============================================================
# Storage Backends
# ============================================================


class _SqliteBackend:
    """
    SQLite durable backend (async via aiosqlite).
    """

    def __init__(
        self,
        *,
        path: Path,
    ) -> None:
        self._path = path
        self._connection: Any = None

    async def connect(self) -> None:
        """
        Open the database and ensure the schema exists.
        """

        import aiosqlite

        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._connection = await aiosqlite.connect(
            self._path,
        )

        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS long_term_entries (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        await self._connection.commit()

    async def disconnect(self) -> None:
        """
        Close the database connection.
        """

        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        """
        Upsert an entry.
        """

        await self._connection.execute(
            """
            INSERT OR REPLACE INTO long_term_entries (
                key,
                payload,
                updated_at
            )
            VALUES (?, ?, ?)
            """,
            (
                entry.key,
                _encode_entry(entry),
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        await self._connection.commit()

    async def delete(
        self,
        key: str,
    ) -> None:
        """
        Remove an entry by key.
        """

        await self._connection.execute(
            "DELETE FROM long_term_entries WHERE key = ?",
            (key,),
        )

        await self._connection.commit()

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        """
        Load an entry by key.
        """

        cursor = await self._connection.execute(
            "SELECT payload FROM long_term_entries WHERE key = ?",
            (key,),
        )

        row = await cursor.fetchone()

        if row is None:
            return None

        return _decode_entry(row[0])

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        """
        Search entries by key or payload text.
        """

        pattern = f"%{query}%"

        cursor = await self._connection.execute(
            """
            SELECT key, payload
            FROM long_term_entries
            WHERE key LIKE ? OR payload LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                pattern,
                pattern,
                limit,
            ),
        )

        rows = await cursor.fetchall()

        return [
            _decode_entry(payload)
            for key, payload in rows
        ]

    async def keys(
        self,
    ) -> Sequence[str]:
        """
        Return all persisted entry keys.
        """

        cursor = await self._connection.execute(
            "SELECT key FROM long_term_entries ORDER BY key"
        )

        rows = await cursor.fetchall()

        return [
            row[0]
            for row in rows
        ]

    async def clear(self) -> None:
        """
        Remove all entries.
        """

        await self._connection.execute(
            "DELETE FROM long_term_entries"
        )

        await self._connection.commit()

    async def compact(self) -> None:
        """
        Compact the database file.
        """

        if self._connection is not None:
            await self._connection.execute(
                "VACUUM"
            )


class _FileSystemBackend:
    """
    File-system durable backend (JSON files per key).
    """

    def __init__(
        self,
        *,
        directory: Path,
    ) -> None:
        self._directory = directory

    async def connect(self) -> None:
        """
        Ensure the storage directory exists.
        """

        self._directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    async def disconnect(self) -> None:
        """
        No persistent connection to release.
        """

    def _path_for(
        self,
        key: str,
    ) -> Path:
        """
        Compute the file path for an entry key.
        """

        safe = "".join(
            (
                character
                if character.isalnum()
                or character in "._-"
                else "_"
            )
            for character in key
        )

        return self._directory / f"{safe}.json"

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        """
        Upsert an entry.
        """

        path = self._path_for(entry.key)

        path.write_text(
            _encode_entry(entry),
            encoding="utf-8",
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        """
        Remove an entry by key.
        """

        path = self._path_for(key)

        if path.exists():
            path.unlink()

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        """
        Load an entry by key.
        """

        path = self._path_for(key)

        if not path.exists():
            return None

        return _decode_entry(
            path.read_text(
                encoding="utf-8"
            )
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        """
        Search entries by key or payload text.
        """

        needle = query.lower()

        matched: list[MemoryEntry[Any]] = []

        for path in sorted(
            self._directory.glob("*.json")
        ):
            if len(matched) >= limit:
                break

            try:
                payload = path.read_text(
                    encoding="utf-8"
                )
            except OSError:
                continue

            if needle in payload.lower():
                matched.append(
                    _decode_entry(payload)
                )

        return matched

    async def keys(
        self,
    ) -> Sequence[str]:
        """
        Return all persisted entry keys.
        """

        return sorted(
            path.stem
            for path in self._directory.glob("*.json")
        )

    async def clear(self) -> None:
        """
        Remove all entries.
        """

        for path in self._directory.glob("*.json"):
            path.unlink()


class _RedisBackend:
    """
    Redis durable backend (async via redis.asyncio).
    """

    def __init__(
        self,
        *,
        collection: str,
    ) -> None:
        self._collection = collection
        self._client: Any = None
        self._hash_key = f"lt:{collection}"

    async def connect(self) -> None:
        """
        Open the Redis client.
        """

        import redis.asyncio as aioredis

        self._client = aioredis.from_url(
            "redis://localhost:6379/0"
        )

        await self._client.ping()

    async def disconnect(self) -> None:
        """
        Close the Redis client.
        """

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        """
        Upsert an entry.
        """

        await self._client.hset(
            self._hash_key,
            entry.key,
            _encode_entry(entry),
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        """
        Remove an entry by key.
        """

        await self._client.hdel(
            self._hash_key,
            key,
        )

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        """
        Load an entry by key.
        """

        payload = await self._client.hget(
            self._hash_key,
            key,
        )

        if payload is None:
            return None

        return _decode_entry(payload)

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        """
        Search entries by key or payload text.
        """

        needle = query.lower()

        items = await self._client.hgetall(
            self._hash_key
        )

        matched: list[MemoryEntry[Any]] = []

        for key, payload in items.items():
            if len(matched) >= limit:
                break

            if (
                needle in key.decode().lower()
                or needle in payload.decode().lower()
            ):
                matched.append(
                    _decode_entry(payload)
                )

        return matched

    async def keys(
        self,
    ) -> Sequence[str]:
        """
        Return all persisted entry keys.
        """

        keys = await self._client.hkeys(
            self._hash_key
        )

        return sorted(
            key.decode()
            for key in keys
        )

    async def clear(self) -> None:
        """
        Remove all entries.
        """

        await self._client.delete(
            self._hash_key
        )


class _PostgresBackend:
    """
    PostgreSQL durable backend (async via asyncpg).
    """

    def __init__(
        self,
        *,
        collection: str,
    ) -> None:
        safe = "".join(
            (
                character
                if character.isalnum()
                or character == "_"
                else "_"
            )
            for character in collection
        )

        self._table = f"lt_{safe}"
        self._connection: Any = None

    async def connect(self) -> None:
        """
        Open the PostgreSQL connection and ensure schema.
        """

        import asyncpg

        self._connection = await asyncpg.connect(
            host="localhost",
            port=5432,
            database="cie_os",
            user="postgres",
            password="postgres",
        )

        await self._connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table} (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    async def disconnect(self) -> None:
        """
        Close the PostgreSQL connection.
        """

        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        """
        Upsert an entry.
        """

        await self._connection.execute(
            f"""
            INSERT INTO {self._table} (
                key,
                payload,
                updated_at
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (key) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = EXCLUDED.updated_at
            """,
            entry.key,
            _encode_entry(entry),
            datetime.now(
                timezone.utc
            ).isoformat(),
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        """
        Remove an entry by key.
        """

        await self._connection.execute(
            f"DELETE FROM {self._table} WHERE key = $1",
            key,
        )

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        """
        Load an entry by key.
        """

        row = await self._connection.fetchrow(
            f"SELECT payload FROM {self._table} WHERE key = $1",
            key,
        )

        if row is None:
            return None

        return _decode_entry(row["payload"])

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        """
        Search entries by key or payload text.
        """

        rows = await self._connection.fetch(
            f"""
            SELECT payload
            FROM {self._table}
            WHERE key ILIKE $1 OR payload ILIKE $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            f"%{query}%",
            limit,
        )

        return [
            _decode_entry(row["payload"])
            for row in rows
        ]

    async def keys(
        self,
    ) -> Sequence[str]:
        """
        Return all persisted entry keys.
        """

        rows = await self._connection.fetch(
            f"SELECT key FROM {self._table} ORDER BY key"
        )

        return [
            row["key"]
            for row in rows
        ]

    async def clear(self) -> None:
        """
        Remove all entries.
        """

        await self._connection.execute(
            f"DELETE FROM {self._table}"
        )


class _ChromaBackend:
    """
    Chroma vector backend.

    ChromaDB is optional. When the package is not
    installed the backend raises on connect, which
    keeps the engine usable with other backends.
    """

    def __init__(
        self,
        *,
        collection: str,
    ) -> None:
        self._collection = collection
        self._client: Any = None
        self._handle: Any = None

    def _unavailable(self) -> RuntimeError:
        """
        Build the not-installed error.
        """

        return RuntimeError(
            "chromadb is not installed; "
            "run `pip install chromadb`"
        )

    async def connect(self) -> None:
        """
        Connect to Chroma.
        """

        try:
            import chromadb  # type: ignore
        except ImportError:
            raise self._unavailable()

        self._client = chromadb.Client()

        self._handle = self._client.get_or_create_collection(
            name=self._collection,
        )

    async def disconnect(self) -> None:
        """
        No explicit release required.
        """

    async def save(
        self,
        entry: MemoryEntry[Any],
    ) -> None:
        """
        Upsert an entry.
        """

        if self._handle is None:
            raise self._unavailable()

        self._handle.upsert(
            ids=[entry.key],
            documents=[_entry_text(entry)],
            metadatas=[
                {
                    "payload": _encode_entry(entry),
                }
            ],
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        """
        Remove an entry by key.
        """

        if self._handle is None:
            raise self._unavailable()

        self._handle.delete(
            ids=[key],
        )

    async def load(
        self,
        key: str,
    ) -> MemoryEntry[Any] | None:
        """
        Load an entry by key.
        """

        if self._handle is None:
            raise self._unavailable()

        result = self._handle.get(
            ids=[key],
        )

        ids = result.get("ids", [])

        if not ids:
            return None

        metadatas = result.get("metadatas", [])

        if metadatas:
            return _decode_entry(
                metadatas[0]["payload"]
            )

        return MemoryEntry(
            key=key,
            value=None,
            metadata=MemoryMetadata(
                namespace=DEFAULT_NAMESPACE,
                tags=["lt:type:semantic"],
            ),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        """
        Search entries by key or payload text.
        """

        if self._handle is None:
            raise self._unavailable()

        result = self._handle.get(
            limit=limit,
        )

        metadatas = result.get("metadatas", [])

        return [
            _decode_entry(metadata["payload"])
            for metadata in metadatas
            if metadata
        ]

    async def keys(
        self,
    ) -> Sequence[str]:
        """
        Return all persisted entry keys.
        """

        if self._handle is None:
            raise self._unavailable()

        result = self._handle.get()

        return sorted(
            result.get("ids", [])
        )

    async def clear(self) -> None:
        """
        Remove all entries.
        """

        if self._handle is None:
            raise self._unavailable()

        self._handle.delete()

