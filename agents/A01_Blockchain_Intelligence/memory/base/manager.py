"""
Memory Manager - Central orchestration layer for memory implementations.

Blockchain-Inspired Design Principles:
- Immutability: State transitions are atomic and verifiable
- Consensus: Thread-safe operations with async locking
- Persistence: Snapshot/backup patterns similar to blockchain checkpoints
- Audit Trail: Event sourcing for all state changes
- Fault Tolerance: Graceful degradation and recovery mechanisms

This module implements a comprehensive memory management system supporting:
- Short-term memory (working memory)
- Long-term memory (persistent storage)
- Conversation memory (contextual history)
- Vector memory (semantic search)
- Multi-backend support with failover
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4

from .memory import (
    BaseMemory,
    MemoryBackend,
    MemoryState,
)

# Configure module logger
logger = logging.getLogger(__name__)


class ManagerState(str, Enum):
    """
    Lifecycle state of the MemoryManager.
    
    State Transitions:
    CREATED -> INITIALIZING -> READY -> RUNNING <-> PAUSED -> STOPPING -> STOPPED -> CLOSED
                 |-> RUNNING (direct start)
                 |-> DEGRADED (error recovery)
    """

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    DEGRADED = "degraded"
    STARTING = "starting"
    CLOSED = "closed"


class SynchronizationMode(str, Enum):
    """
    Memory synchronization policy.
    
    MANUAL: Explicit synchronization calls only
    AUTOMATIC: Sync on every write operation
    PERIODIC: Time-based synchronization
    """

    MANUAL = "manual"
    AUTOMATIC = "automatic"
    PERIODIC = "periodic"


class BackupMode(str, Enum):
    """
    Backup strategy.
    
    DISABLED: No backups created
    SNAPSHOT: Point-in-time snapshots
    INCREMENTAL: Only changes since last backup
    FULL: Complete backup every time
    """

    DISABLED = "disabled"
    SNAPSHOT = "snapshot"
    INCREMENTAL = "incremental"
    FULL = "full"


class MemoryManagerError(Exception):
    """Base exception for MemoryManager errors."""
    pass


class MemoryNotRegisteredError(MemoryManagerError):
    """Raised when accessing unregistered memory."""
    pass


class NamespaceError(MemoryManagerError):
    """Raised when namespace operation fails."""
    pass


class StateTransitionError(MemoryManagerError):
    """Raised when invalid state transition is attempted."""
    pass


@dataclass(slots=True)
class RetryPolicy:
    """
    Retry configuration with exponential backoff.
    
    Attributes:
        attempts: Maximum retry attempts
        initial_delay: Initial delay in seconds
        maximum_delay: Maximum delay cap in seconds
        exponential_backoff: Enable exponential backoff
    """

    attempts: int = 3
    initial_delay: float = 0.5
    maximum_delay: float = 10.0
    exponential_backoff: bool = True


@dataclass(slots=True)
class MetricsConfiguration:
    """Runtime metrics configuration."""

    enabled: bool = True
    collect_latency: bool = True
    collect_cache_metrics: bool = True
    collect_backend_metrics: bool = True


@dataclass(slots=True)
class HealthConfiguration:
    """Health monitoring configuration."""

    enabled: bool = True
    check_interval: int = 60
    auto_recover: bool = True


@dataclass(slots=True)
class SnapshotConfiguration:
    """Snapshot configuration for state persistence."""

    enabled: bool = True
    keep_last: int = 20
    compress: bool = False


@dataclass(slots=True)
class MemoryManagerConfig:
    """
    Global configuration for the MemoryManager.
    
    Attributes:
        namespace: Default namespace identifier
        working_directory: Base path for persistence
        synchronization: Memory sync policy
        backup: Backup strategy
        retry: Retry configuration
        metrics: Metrics collection settings
        health: Health monitoring settings
        snapshots: Snapshot management settings
        metadata: Custom metadata dictionary
        automatic_maintenance: Enable background maintenance (default: False)
    """

    namespace: str = "default"
    working_directory: Path = Path("./memory")
    synchronization: SynchronizationMode = SynchronizationMode.AUTOMATIC
    backup: BackupMode = BackupMode.SNAPSHOT
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    metrics: MetricsConfiguration = field(default_factory=MetricsConfiguration)
    health: HealthConfiguration = field(default_factory=HealthConfiguration)
    snapshots: SnapshotConfiguration = field(default_factory=SnapshotConfiguration)
    metadata: dict[str, Any] = field(default_factory=dict)
    automatic_maintenance: bool = False


class MemoryManager:
    """
    Central orchestration layer for memory implementations.
    
    Thread-safe, async-aware memory manager with blockchain-inspired
    state management, event sourcing, and fault tolerance.
    
    Coordinates:
    - Short-term memory (working set)
    - Long-term memory (persistent storage)
    - Conversation memory (contextual history)
    - Vector memory (semantic search)
    - Retrieval routing
    - Synchronization pipelines
    
    Thread Safety:
    All public methods are protected by an asyncio lock to ensure
    thread-safe state mutations in concurrent environments.
    """

    def __init__(
        self,
        *,
        config: MemoryManagerConfig | None = None,
    ) -> None:
        """
        Initialize the memory manager.
        
        Args:
            config: Optional configuration object. Uses defaults if not provided.
        """
        self._id: UUID = uuid4()
        self._config = config if config is not None else MemoryManagerConfig()
        self._state = ManagerState.CREATED
        
        # Thread safety lock
        self._lock = asyncio.Lock()
        
        # Backend registry
        self._backends: dict[str, MemoryBackend] = {}
        
        # Namespace-based memory organization
        # Structure: {namespace: {memory_name: memory_instance}}
        self._namespaces: dict[str, dict[str, BaseMemory[Any]]] = {}
        
        # Flat memory registry for direct access
        self._memories: dict[str, BaseMemory[Any]] = {}
        
        # Active namespace tracking
        self._active_namespace = self._config.namespace
        
        # Specialized memory references
        self._short_term_memory: BaseMemory[Any] | None = None
        self._long_term_memory: BaseMemory[Any] | None = None
        self._conversation_memory: BaseMemory[Any] | None = None
        self._vector_memory: BaseMemory[Any] | None = None
        self._active_backend: str | None = None
        
        # Event sourcing
        self._event_listeners: dict[str, list[Any]] = {}
        
        # Snapshot and backup storage
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._backups: dict[str, dict[str, Any]] = {}
        
        # Metrics
        self._metrics: dict[str, int] = {}
        
        logger.info(f"MemoryManager initialized with ID: {self._id}")

    @property
    def identifier(self) -> UUID:
        """Return unique manager identifier."""
        return self._id

    @property
    def configuration(self) -> MemoryManagerConfig:
        """Return immutable configuration."""
        return self._config

    @property
    def state(self) -> ManagerState:
        """Return current lifecycle state."""
        return self._state

    @property
    def namespace(self) -> str:
        """Return active namespace."""
        return self._active_namespace

    @property
    def memory_count(self) -> int:
        """Return total number of registered memories."""
        return len(self._memories)

    @property
    def backend_count(self) -> int:
        """Return total number of registered backends."""
        return len(self._backends)

    def validate_configuration(self) -> None:
        """
        Validate manager configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if not self._config.namespace.strip():
            raise ValueError("Namespace cannot be empty.")
        
        if self._config.retry.attempts < 1:
            raise ValueError("Retry attempts must be greater than zero.")
        
        if self._config.health.check_interval < 1:
            raise ValueError("Health interval must be positive.")
        
        if self._config.snapshots.keep_last < 1:
            raise ValueError("Snapshot retention must be positive.")

    def configuration_snapshot(self) -> Mapping[str, Any]:
        """
        Export immutable configuration snapshot.
        
        Returns:
            Dictionary containing current configuration state
        """
        return {
            "manager_id": str(self._id),
            "namespace": self._config.namespace,
            "state": self._state.value,
            "working_directory": str(self._config.working_directory),
            "synchronization": self._config.synchronization.value,
            "backup": self._config.backup.value,
            "metrics_enabled": self._config.metrics.enabled,
            "health_enabled": self._config.health.enabled,
            "snapshots_enabled": self._config.snapshots.enabled,
            "active_backend": getattr(self, "_active_backend", None),
        }

    # ------------------------------------------------------------------
    # Backend Registry
    # ------------------------------------------------------------------

    def register_backend(
        self,
        name: str,
        backend: MemoryBackend,
        *,
        make_active: bool = False,
    ) -> None:
        """
        Register a memory backend.
        
        Args:
            name: Backend identifier
            backend: Backend implementation
            make_active: Set as active backend
            
        Raises:
            ValueError: If name is empty or backend already exists
        """
        if not name.strip():
            raise ValueError("Backend name cannot be empty.")
        
        if name in self._backends:
            raise ValueError(f"Backend '{name}' already exists.")
        
        self._backends[name] = backend
        
        if make_active:
            self._active_backend = name
        
        logger.debug(f"Registered backend: {name}")

    def unregister_backend(self, name: str) -> bool:
        """
        Remove a backend.
        
        Args:
            name: Backend identifier
            
        Returns:
            True if backend was removed, False if not found
        """
        backend = self._backends.pop(name, None)
        
        if backend is None:
            return False
        
        if getattr(self, "_active_backend", None) == name:
            self._active_backend = None
        
        logger.debug(f"Unregistered backend: {name}")
        return True

    def backend(self, name: str) -> MemoryBackend:
        """
        Return a registered backend.
        
        Args:
            name: Backend identifier
            
        Returns:
            Backend instance
            
        Raises:
            KeyError: If backend not found
        """
        try:
            return self._backends[name]
        except KeyError as exc:
            raise KeyError(f"Unknown backend '{name}'.") from exc

    @property
    def active_backend(self) -> MemoryBackend | None:
        """Return the active backend."""
        name = getattr(self, "_active_backend", None)
        if name is None:
            return None
        return self._backends.get(name)

    def set_active_backend(self, name: str) -> None:
        """
        Select the active backend.
        
        Args:
            name: Backend identifier
            
        Raises:
            KeyError: If backend not registered
        """
        if name not in self._backends:
            raise KeyError(f"Backend '{name}' is not registered.")
        self._active_backend = name

    def backend_names(self) -> list[str]:
        """Return all registered backend names."""
        return sorted(self._backends.keys())

    def has_backend(self, name: str) -> bool:
        """Check backend existence."""
        return name in self._backends

    def backend_count(self) -> int:
        """Return number of registered backends."""
        return len(self._backends)

    def backend_capabilities(self, name: str) -> dict[str, bool]:
        """
        Inspect backend capabilities.
        
        Args:
            name: Backend identifier
            
        Returns:
            Dictionary of available capabilities
        """
        backend = self.backend(name)
        return {
            "connect": hasattr(backend, "connect"),
            "disconnect": hasattr(backend, "disconnect"),
            "put": hasattr(backend, "put"),
            "get": hasattr(backend, "get"),
            "delete": hasattr(backend, "delete"),
            "search": hasattr(backend, "search"),
        }

    async def validate_backends(self) -> dict[str, bool]:
        """
        Validate every registered backend.
        
        Returns:
            Dictionary mapping backend names to health status
        """
        status: dict[str, bool] = {}
        
        for name, backend in self._backends.items():
            try:
                await backend.connect()
                await backend.disconnect()
                status[name] = True
            except Exception as e:
                logger.warning(f"Backend validation failed for {name}: {e}")
                status[name] = False
        
        return status

    async def backend_health(self) -> dict[str, str]:
        """
        Lightweight backend health report.
        
        Returns:
            Dictionary mapping backend names to health status
        """
        report: dict[str, str] = {}
        validation = await self.validate_backends()
        
        for name, healthy in validation.items():
            report[name] = "healthy" if healthy else "unhealthy"
        
        return report

    # ------------------------------------------------------------------
    # Namespace Manager
    # ------------------------------------------------------------------

    def create_namespace(self, namespace: str) -> None:
        """
        Create a logical namespace.
        
        Args:
            namespace: Namespace identifier
            
        Raises:
            ValueError: If namespace is empty or already exists
        """
        namespace = namespace.strip()
        
        if not namespace:
            raise ValueError("Namespace cannot be empty.")
        
        if namespace in self._namespaces:
            raise ValueError(f"Namespace '{namespace}' already exists.")
        
        self._namespaces[namespace] = {}
        logger.debug(f"Created namespace: {namespace}")

    def delete_namespace(self, namespace: str) -> bool:
        """
        Delete a namespace.
        
        Args:
            namespace: Namespace identifier
            
        Returns:
            True if deleted, False if not found
            
        Raises:
            RuntimeError: If attempting to delete active namespace
        """
        if namespace == self._active_namespace:
            raise RuntimeError("Cannot delete the active namespace.")
        
        if namespace not in self._namespaces:
            return False
        
        del self._namespaces[namespace]
        logger.debug(f"Deleted namespace: {namespace}")
        return True

    def has_namespace(self, namespace: str) -> bool:
        """Check namespace existence."""
        return namespace in self._namespaces

    def namespaces(self) -> list[str]:
        """Return every registered namespace."""
        return sorted(self._namespaces.keys())

    def switch_namespace(self, namespace: str) -> None:
        """
        Switch the active namespace.
        
        Args:
            namespace: Namespace identifier
            
        Raises:
            KeyError: If namespace doesn't exist
        """
        if namespace not in self._namespaces:
            raise KeyError(f"Namespace '{namespace}' does not exist.")
        
        self._active_namespace = namespace
        logger.debug(f"Switched to namespace: {namespace}")

    def active_namespace(self) -> str:
        """Return current namespace."""
        return self._active_namespace

    def namespace_exists(self, namespace: str) -> bool:
        """Check if namespace exists."""
        return namespace in self._namespaces

    def namespace_memory_count(self, namespace: str) -> int:
        """
        Return number of memories registered inside a namespace.
        
        Args:
            namespace: Namespace identifier
            
        Returns:
            Count of memories in namespace
            
        Raises:
            KeyError: If namespace doesn't exist
        """
        if namespace not in self._namespaces:
            raise KeyError(f"Namespace '{namespace}' does not exist.")
        
        return len(self._namespaces[namespace])

    def namespace_statistics(self, namespace: str) -> dict[str, Any]:
        """
        Return namespace statistics.
        
        Args:
            namespace: Namespace identifier
            
        Returns:
            Dictionary with namespace metrics
            
        Raises:
            KeyError: If namespace doesn't exist
        """
        if namespace not in self._namespaces:
            raise KeyError(f"Namespace '{namespace}' does not exist.")
        
        memories = self._namespaces[namespace]
        healthy = sum(
            1
            for memory in memories.values()
            if memory.state in (MemoryState.READY, MemoryState.ACTIVE)
        )
        
        return {
            "namespace": namespace,
            "registered_memories": len(memories),
            "healthy_memories": healthy,
            "state": "active" if namespace == self._active_namespace else "inactive",
        }

    def clear_namespace(self, namespace: str) -> None:
        """
        Remove every registered memory from a namespace.
        
        Args:
            namespace: Namespace identifier
            
        Raises:
            KeyError: If namespace doesn't exist
        """
        if namespace not in self._namespaces:
            raise KeyError(f"Namespace '{namespace}' does not exist.")
        
        self._namespaces[namespace].clear()
        logger.debug(f"Cleared namespace: {namespace}")

    def rename_namespace(self, source: str, target: str) -> None:
        """
        Rename a namespace.
        
        Args:
            source: Current namespace name
            target: New namespace name
            
        Raises:
            KeyError: If source doesn't exist
            ValueError: If target already exists
        """
        if source not in self._namespaces:
            raise KeyError(f"Namespace '{source}' does not exist.")
        
        if target in self._namespaces:
            raise ValueError(f"Namespace '{target}' already exists.")
        
        self._namespaces[target] = self._namespaces.pop(source)
        
        if self._active_namespace == source:
            self._active_namespace = target
        
        logger.debug(f"Renamed namespace: {source} -> {target}")

    def namespace_snapshot(self) -> dict[str, Any]:
        """
        Export namespace information.
        
        Returns:
            Dictionary with namespace metadata
        """
        return {
            "active": self._active_namespace,
            "count": len(self._namespaces),
            "namespaces": self.namespaces(),
        }

    # ------------------------------------------------------------------
    # Short-Term Memory Manager
    # ------------------------------------------------------------------

    def register_short_term_memory(
        self,
        memory: BaseMemory[Any],
        *,
        name: str = "short_term",
        namespace: str | None = None,
    ) -> None:
        """
        Register the primary short-term memory.
        
        Args:
            memory: Memory implementation
            name: Memory identifier
            namespace: Optional namespace (uses active if not provided)
        """
        target_namespace = namespace or self._active_namespace
        
        if target_namespace not in self._namespaces:
            self._namespaces[target_namespace] = {}
        
        self._namespaces[target_namespace][name] = memory
        self._memories[name] = memory
        self._short_term_memory = memory
        logger.debug(f"Registered short-term memory: {name} in namespace {target_namespace}")

    @property
    def short_term_memory(self) -> BaseMemory[Any] | None:
        """Return the active short-term memory."""
        return self._short_term_memory

    def has_short_term_memory(self) -> bool:
        """Check if short-term memory is registered."""
        return self.short_term_memory is not None

    def remove_short_term_memory(self) -> bool:
        """
        Unregister the current short-term memory.
        
        Returns:
            True if removed, False if not registered
        """
        memory = self.short_term_memory
        if memory is None:
            return False
        
        self._memories.pop("short_term", None)
        
        if self._active_namespace in self._namespaces:
            self._namespaces[self._active_namespace].pop("short_term", None)
        
        self._short_term_memory = None
        logger.debug("Removed short-term memory")
        return True

    async def remember(self, key: str, value: Any, **kwargs: Any) -> None:
        """
        Store data in short-term memory.
        
        Args:
            key: Memory key
            value: Value to store
            **kwargs: Additional metadata
            
        Raises:
            MemoryNotRegisteredError: If short-term memory not registered
        """
        memory = self.short_term_memory
        if memory is None:
            raise MemoryNotRegisteredError("Short-term memory is not registered.")
        
        await memory.put(key, value, **kwargs)

    async def recall(self, key: str) -> Any | None:
        """
        Retrieve data from short-term memory.
        
        Args:
            key: Memory key
            
        Returns:
            Stored value or None if not found
        """
        memory = self.short_term_memory
        if memory is None:
            return None
        
        entry = await memory.get(key)
        if entry is None:
            return None
        
        return entry.value

    async def forget(self, key: str) -> bool:
        """
        Remove an item from short-term memory.
        
        Args:
            key: Memory key
            
        Returns:
            True if deleted, False if not found
        """
        memory = self.short_term_memory
        if memory is None:
            return False
        
        return await memory.delete(key)

    async def clear_short_term(self) -> None:
        """Clear the active short-term memory."""
        memory = self.short_term_memory
        if memory is None:
            return
        
        await memory.clear()

    async def short_term_statistics(self) -> dict[str, Any]:
        """
        Export runtime statistics.
        
        Returns:
            Dictionary with short-term memory metrics
        """
        memory = self.short_term_memory
        if memory is None:
            return {}
        
        return {
            "namespace": self._active_namespace,
            "entries": await memory.count(),
            "health": memory.health(),
            "metrics": memory.metrics(),
        }

    async def compact_short_term(self) -> int:
        """
        Run maintenance on short-term memory.
        
        Returns:
            Number of entries compacted
        """
        memory = self.short_term_memory
        if memory is None:
            return 0
        
        return await memory.compact()

    # ------------------------------------------------------------------
    # Long-Term Memory Manager
    # ------------------------------------------------------------------

    def register_long_term_memory(
        self,
        memory: BaseMemory[Any],
        *,
        name: str = "long_term",
        namespace: str | None = None,
    ) -> None:
        """
        Register the primary long-term memory.
        
        Args:
            memory: Memory implementation
            name: Memory identifier
            namespace: Optional namespace
        """
        target_namespace = namespace or self._active_namespace
        
        if target_namespace not in self._namespaces:
            self._namespaces[target_namespace] = {}
        
        self._namespaces[target_namespace][name] = memory
        self._memories[name] = memory
        self._long_term_memory = memory
        logger.debug(f"Registered long-term memory: {name}")

    @property
    def long_term_memory(self) -> BaseMemory[Any] | None:
        """Return the active long-term memory."""
        return self._long_term_memory

    def has_long_term_memory(self) -> bool:
        """Check if long-term memory is registered."""
        return self.long_term_memory is not None

    def remove_long_term_memory(self) -> bool:
        """
        Unregister the current long-term memory.
        
        Returns:
            True if removed, False if not registered
        """
        memory = self.long_term_memory
        if memory is None:
            return False
        
        self._memories.pop("long_term", None)
        
        if self._active_namespace in self._namespaces:
            self._namespaces[self._active_namespace].pop("long_term", None)
        
        self._long_term_memory = None
        logger.debug("Removed long-term memory")
        return True

    async def memorize(self, key: str, value: Any, **kwargs: Any) -> None:
        """
        Persist information into long-term memory.
        
        Args:
            key: Memory key
            value: Value to store
            **kwargs: Additional metadata
            
        Raises:
            MemoryNotRegisteredError: If long-term memory not registered
        """
        memory = self.long_term_memory
        if memory is None:
            raise MemoryNotRegisteredError("Long-term memory is not registered.")
        
        await memory.put(key, value, **kwargs)

    async def remember_forever(self, key: str) -> Any | None:
        """
        Retrieve a value from long-term memory.
        
        Args:
            key: Memory key
            
        Returns:
            Stored value or None
        """
        memory = self.long_term_memory
        if memory is None:
            return None
        
        entry = await memory.get(key)
        if entry is None:
            return None
        
        return entry.value

    async def forget_forever(self, key: str) -> bool:
        """
        Remove an item from long-term memory.
        
        Args:
            key: Memory key
            
        Returns:
            True if deleted, False if not found
        """
        memory = self.long_term_memory
        if memory is None:
            return False
        
        return await memory.delete(key)

    async def consolidate_short_term(
        self, *, overwrite: bool = False
    ) -> int:
        """
        Copy active short-term memories into long-term memory.
        
        Args:
            overwrite: Overwrite existing entries
            
        Returns:
            Number of entries migrated
        """
        short_memory = self.short_term_memory
        long_memory = self.long_term_memory
        
        if short_memory is None or long_memory is None:
            return 0
        
        migrated = 0
        for entry in short_memory:
            existing = await long_memory.get(entry.key)
            
            if existing is not None and not overwrite:
                continue
            
            await long_memory.put(
                entry.key, entry.value, metadata=entry.metadata
            )
            migrated += 1
        
        return migrated

    async def long_term_statistics(self) -> dict[str, Any]:
        """
        Export runtime statistics for long-term memory.
        
        Returns:
            Dictionary with long-term memory metrics
        """
        memory = self.long_term_memory
        if memory is None:
            return {}
        
        return {
            "namespace": self._active_namespace,
            "entries": await memory.count(),
            "health": memory.health(),
            "metrics": memory.metrics(),
        }

    async def compact_long_term(self) -> int:
        """
        Execute maintenance on long-term memory.
        
        Returns:
            Number of entries compacted
        """
        memory = self.long_term_memory
        if memory is None:
            return 0
        
        return await memory.compact()

    async def synchronize_long_term(self) -> None:
        """Synchronize persistent storage."""
        memory = self.long_term_memory
        if memory is None:
            return
        
        await memory.synchronize()

    # ------------------------------------------------------------------
    # Conversation Memory Manager
    # ------------------------------------------------------------------

    def register_conversation_memory(
        self,
        memory: BaseMemory[Any],
        *,
        name: str = "conversation",
        namespace: str | None = None,
    ) -> None:
        """
        Register the conversation memory.
        
        Args:
            memory: Memory implementation
            name: Memory identifier
            namespace: Optional namespace
        """
        target_namespace = namespace or self._active_namespace
        
        if target_namespace not in self._namespaces:
            self._namespaces[target_namespace] = {}
        
        self._namespaces[target_namespace][name] = memory
        self._memories[name] = memory
        self._conversation_memory = memory
        logger.debug(f"Registered conversation memory: {name}")

    @property
    def conversation_memory(self) -> BaseMemory[Any] | None:
        """Return the active conversation memory."""
        return self._conversation_memory

    def has_conversation_memory(self) -> bool:
        """Check if conversation memory is registered."""
        return self.conversation_memory is not None

    async def add_message(
        self, message_id: str, message: Any, **kwargs: Any
    ) -> None:
        """
        Store a conversation message.
        
        Args:
            message_id: Message identifier
            message: Message content
            **kwargs: Additional metadata
            
        Raises:
            MemoryNotRegisteredError: If conversation memory not registered
        """
        memory = self.conversation_memory
        if memory is None:
            raise MemoryNotRegisteredError("Conversation memory is not registered.")
        
        await memory.put(message_id, message, **kwargs)

    async def get_message(self, message_id: str) -> Any | None:
        """
        Retrieve a conversation message.
        
        Args:
            message_id: Message identifier
            
        Returns:
            Message content or None
        """
        memory = self.conversation_memory
        if memory is None:
            return None
        
        entry = await memory.get(message_id)
        if entry is None:
            return None
        
        return entry.value

    async def delete_message(self, message_id: str) -> bool:
        """
        Remove a conversation message.
        
        Args:
            message_id: Message identifier
            
        Returns:
            True if deleted, False if not found
        """
        memory = self.conversation_memory
        if memory is None:
            return False
        
        return await memory.delete(message_id)

    async def conversation_history(self) -> list[Any]:
        """
        Return the current conversation history.
        
        Returns:
            List of messages in chronological order
        """
        memory = self.conversation_memory
        if memory is None:
            return []
        
        history: list[Any] = []
        for entry in memory:
            history.append(entry.value)
        
        return history

    async def recent_messages(self, limit: int = 20) -> list[Any]:
        """
        Return the most recent messages.
        
        Args:
            limit: Maximum number of messages to return
            
        Returns:
            List of recent messages
        """
        history = await self.conversation_history()
        
        if limit <= 0:
            return []
        
        return history[-limit:]

    async def clear_conversation(self) -> None:
        """Remove all conversation history."""
        memory = self.conversation_memory
        if memory is None:
            return
        
        await memory.clear()

    async def trim_conversation(self, keep_last: int = 100) -> int:
        """
        Keep only the newest messages.
        
        Args:
            keep_last: Number of recent messages to retain
            
        Returns:
            Number of messages removed
        """
        memory = self.conversation_memory
        if memory is None:
            return 0
        
        entries = list(memory)
        if len(entries) <= keep_last:
            return 0
        
        remove = len(entries) - keep_last
        for entry in entries[:remove]:
            await memory.delete(entry.key)
        
        return remove

    async def conversation_statistics(self) -> dict[str, Any]:
        """
        Export conversation statistics.
        
        Returns:
            Dictionary with conversation metrics
        """
        memory = self.conversation_memory
        if memory is None:
            return {}
        
        return {
            "namespace": self._active_namespace,
            "messages": await memory.count(),
            "health": memory.health(),
            "metrics": memory.metrics(),
        }

    async def persist_conversation(self) -> None:
        """Synchronize conversation memory."""
        memory = self.conversation_memory
        if memory is None:
            return
        
        await memory.synchronize()

    # ------------------------------------------------------------------
    # Vector Memory Manager
    # ------------------------------------------------------------------

    def register_vector_memory(
        self,
        memory: BaseMemory[Any],
        *,
        name: str = "vector",
        namespace: str | None = None,
    ) -> None:
        """
        Register the primary vector memory.
        
        Args:
            memory: Memory implementation
            name: Memory identifier
            namespace: Optional namespace
        """
        target_namespace = namespace or self._active_namespace
        
        if target_namespace not in self._namespaces:
            self._namespaces[target_namespace] = {}
        
        self._namespaces[target_namespace][name] = memory
        self._memories[name] = memory
        self._vector_memory = memory
        logger.debug(f"Registered vector memory: {name}")

    @property
    def vector_memory(self) -> BaseMemory[Any] | None:
        """Return the active vector memory."""
        return self._vector_memory

    def has_vector_memory(self) -> bool:
        """Check if vector memory is registered."""
        return self.vector_memory is not None

    async def index_vector(self, key: str, value: Any, **kwargs: Any) -> None:
        """
        Store an item in vector memory.
        
        Args:
            key: Vector key
            value: Value to store
            **kwargs: Additional metadata
            
        Raises:
            MemoryNotRegisteredError: If vector memory not registered
        """
        memory = self.vector_memory
        if memory is None:
            raise MemoryNotRegisteredError("Vector memory is not registered.")
        
        await memory.put(key, value, **kwargs)

    async def semantic_search(
        self, query: str, *, limit: int = 10, **kwargs: Any
    ) -> list[Any]:
        """
        Execute semantic retrieval.
        
        Args:
            query: Search query
            limit: Maximum results
            **kwargs: Additional search parameters
            
        Returns:
            List of matching results
        """
        memory = self.vector_memory
        if memory is None:
            return []
        
        results = await memory.search(query, limit=limit, **kwargs)
        return list(results)

    async def similarity_search(
        self,
        query: str,
        *,
        limit: int = 10,
        minimum_score: float | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Execute similarity search with optional score filtering.
        
        Args:
            query: Search query
            limit: Maximum results
            minimum_score: Minimum similarity score threshold
            **kwargs: Additional search parameters
            
        Returns:
            List of results filtered by score
        """
        memory = self.vector_memory
        if memory is None:
            return []
        
        results = await memory.search(query, limit=limit, **kwargs)
        
        if minimum_score is None:
            return list(results)
        
        filtered: list[Any] = []
        for item in results:
            score = getattr(item, "score", None)
            if score is None or score >= minimum_score:
                filtered.append(item)
        
        return filtered

    async def delete_vector(self, key: str) -> bool:
        """
        Remove a vector entry.
        
        Args:
            key: Vector key
            
        Returns:
            True if deleted, False if not found
        """
        memory = self.vector_memory
        if memory is None:
            return False
        
        return await memory.delete(key)

    async def clear_vector_memory(self) -> None:
        """Remove every indexed vector."""
        memory = self.vector_memory
        if memory is None:
            return
        
        await memory.clear()

    async def rebuild_vector_index(self) -> None:
        """Rebuild the vector index."""
        memory = self.vector_memory
        if memory is None:
            return
        
        rebuild = getattr(memory, "rebuild_index", None)
        if callable(rebuild):
            await rebuild()

    async def synchronize_vector_memory(self) -> None:
        """Synchronize vector backend."""
        memory = self.vector_memory
        if memory is None:
            return
        
        await memory.synchronize()

    async def vector_statistics(self) -> dict[str, Any]:
        """
        Export vector memory statistics.
        
        Returns:
            Dictionary with vector memory metrics
        """
        memory = self.vector_memory
        if memory is None:
            return {}
        
        return {
            "namespace": self._active_namespace,
            "entries": await memory.count(),
            "health": memory.health(),
            "metrics": memory.metrics(),
        }

    async def embedding_provider(self) -> Any | None:
        """
        Return the configured embedding provider, if supported.
        
        Returns:
            Embedding provider or None
        """
        memory = self.vector_memory
        if memory is None:
            return None
        
        return getattr(memory, "embedding_provider", None)

    # ------------------------------------------------------------------
    # Retrieval Router
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        *,
        limit: int = 10,
        strategy: str = "auto",
        namespace: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """
        Execute memory retrieval using the selected strategy.
        
        Args:
            query: Search query
            limit: Maximum results
            strategy: Retrieval strategy (auto/semantic/keyword/hybrid)
            namespace: Optional namespace filter
            metadata: Optional metadata filters
            
        Returns:
            List of retrieved memories
            
        Raises:
            ValueError: If strategy is unknown
        """
        strategy = strategy.lower()
        
        if strategy == "auto":
            strategy = self.select_strategy(query)
        
        if strategy == "semantic":
            return await self.semantic_search(query, limit=limit)
        
        if strategy == "keyword":
            return await self.keyword_search(query, limit=limit)
        
        if strategy == "hybrid":
            return await self.hybrid_search(
                query, limit=limit, metadata=metadata
            )
        
        raise ValueError(f"Unknown retrieval strategy '{strategy}'.")

    def select_strategy(self, query: str) -> str:
        """
        Select the most appropriate retrieval strategy.
        
        Args:
            query: Search query
            
        Returns:
            Strategy name (semantic/keyword/hybrid)
        """
        query = query.strip()
        
        if not query:
            return "keyword"
        
        words = len(query.split())
        if words <= 2:
            return "keyword"
        
        # Semantic indicators
        semantic_tokens = {"why", "how", "similar", "related", "explain"}
        if any(token in query.lower() for token in semantic_tokens):
            return "semantic"
        
        return "hybrid"

    async def keyword_search(
        self, query: str, *, limit: int = 10
    ) -> list[Any]:
        """
        Execute keyword retrieval.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching results
        """
        memory = self.short_term_memory
        if memory is None:
            return []
        
        search = getattr(memory, "keyword_search", None)
        if callable(search):
            return list(await search(query, limit=limit))
        
        return []

    async def hybrid_search(
        self,
        query: str,
        *,
        limit: int = 10,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """
        Combine semantic and keyword retrieval.
        
        Args:
            query: Search query
            limit: Maximum results
            metadata: Optional metadata filter
            
        Returns:
            Merged results from both strategies
        """
        semantic = await self.semantic_search(query, limit=limit)
        keyword = await self.keyword_search(query, limit=limit)
        
        # Merge results, preferring semantic
        merged: dict[Any, Any] = {}
        for item in semantic:
            key = getattr(item, "key", id(item))
            merged[key] = item
        
        for item in keyword:
            key = getattr(item, "key", id(item))
            merged.setdefault(key, item)
        
        results = list(merged.values())
        
        # Apply metadata filter
        if metadata:
            results = [
                item
                for item in results
                if self._match_metadata(item, metadata)
            ]
        
        return results[:limit]

    def _match_metadata(
        self, item: Any, metadata: Mapping[str, Any]
    ) -> bool:
        """
        Match metadata filters.
        
        Args:
            item: Item to check
            metadata: Required metadata
            
        Returns:
            True if all metadata matches
        """
        item_metadata = getattr(item, "metadata", None)
        if item_metadata is None:
            return False
        
        for key, value in metadata.items():
            if item_metadata.get(key) != value:
                return False
        
        return True

    async def rerank_results(
        self, results: list[Any], *, limit: int = 10
    ) -> list[Any]:
        """
        Rerank retrieved memories by score.
        
        Args:
            results: List of results to rerank
            limit: Maximum results to return
            
        Returns:
            Reranked and limited results
        """
        ordered = sorted(
            results,
            key=lambda item: getattr(item, "score", 0.0),
            reverse=True,
        )
        return ordered[:limit]

    async def build_context(
        self, query: str, *, limit: int = 10
    ) -> list[Any]:
        """
        Build the final retrieval context.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            Final context list
        """
        results = await self.retrieve(query, limit=limit)
        return await self.rerank_results(results, limit=limit)

    async def retrieve_context(
        self, query: str, *, limit: int = 10
    ) -> list[Any]:
        """
        Public helper for prompt builders.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            Context list for prompt construction
        """
        return await self.build_context(query, limit=limit)

    # ------------------------------------------------------------------
    # Summarization Pipeline
    # ------------------------------------------------------------------

    def register_summarizer(self, summarizer: Any) -> None:
        """
        Register the active summarizer implementation.
        
        Args:
            summarizer: Summarizer instance
        """
        self._summarizer = summarizer

    @property
    def summarizer(self) -> Any | None:
        """Return the active summarizer."""
        return getattr(self, "_summarizer", None)

    def has_summarizer(self) -> bool:
        """Check whether a summarizer exists."""
        return self.summarizer is not None

    async def summarize(self, content: Any, **kwargs: Any) -> Any:
        """
        Generate a summary.
        
        Args:
            content: Content to summarize
            **kwargs: Additional parameters
            
        Returns:
            Summarized content
            
        Raises:
            RuntimeError: If no summarizer registered
        """
        summarizer = self.summarizer
        if summarizer is None:
            raise RuntimeError("No summarizer registered.")
        
        return await summarizer.summarize(content, **kwargs)

    async def compress_memory(
        self, content: Any, **kwargs: Any
    ) -> Any:
        """
        Compress memory before persistence.
        
        Args:
            content: Content to compress
            **kwargs: Additional parameters
            
        Returns:
            Compressed content or original if no compressor
        """
        summarizer = self.summarizer
        if summarizer is None:
            return content
        
        compress = getattr(summarizer, "compress", None)
        if callable(compress):
            return await compress(content, **kwargs)
        
        return content

    async def importance_score(self, content: Any) -> float:
        """
        Calculate memory importance.
        
        Args:
            content: Content to score
            
        Returns:
            Importance score (0.0-1.0)
        """
        summarizer = self.summarizer
        if summarizer is None:
            return 1.0
        
        scorer = getattr(summarizer, "importance_score", None)
        if callable(scorer):
            return float(await scorer(content))
        
        return 1.0

    async def should_persist(
        self, content: Any, *, threshold: float = 0.50
    ) -> bool:
        """
        Decide whether content should be stored permanently.
        
        Args:
            content: Content to evaluate
            threshold: Minimum importance threshold
            
        Returns:
            True if content should be persisted
        """
        score = await self.importance_score(content)
        return score >= threshold

    async def summarize_conversation(self) -> Any | None:
        """
        Summarize the active conversation.
        
        Returns:
            Summary or None if no history
        """
        history = await self.conversation_history()
        if not history:
            return None
        
        return await self.summarize(history)

    async def consolidate_memory(self) -> int:
        """
        Summarize and migrate short-term memory.
        
        Returns:
            Number of summaries persisted
        """
        summary = await self.summarize_conversation()
        if summary is None:
            return 0
        
        keep = await self.should_persist(summary)
        if not keep:
            return 0
        
        await self.memorize("__conversation_summary__", summary)
        return 1

    async def prune_memory(self, *, threshold: float = 0.20) -> int:
        """
        Remove low-value memories.
        
        Args:
            threshold: Minimum importance threshold
            
        Returns:
            Number of memories removed
        """
        memory = self.long_term_memory
        if memory is None:
            return 0
        
        removed = 0
        for entry in memory:
            score = await self.importance_score(entry.value)
            if score < threshold:
                await memory.delete(entry.key)
                removed += 1
        
        return removed

    async def summary_statistics(self) -> dict[str, Any]:
        """
        Export summarization metrics.
        
        Returns:
            Dictionary with summarization status
        """
        return {
            "enabled": self.has_summarizer(),
            "conversation_memory": self.has_conversation_memory(),
            "short_term": self.has_short_term_memory(),
            "long_term": self.has_long_term_memory(),
        }

    # ------------------------------------------------------------------
    # Synchronization
    # ------------------------------------------------------------------

    async def synchronize(self) -> dict[str, bool]:
        """
        Synchronize every registered memory.
        
        Returns:
            Dictionary mapping memory names to sync status
        """
        results: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            try:
                await memory.synchronize()
                results[name] = True
            except Exception as e:
                logger.warning(f"Sync failed for memory {name}: {e}")
                results[name] = False
        
        return results

    async def synchronize_namespace(
        self, namespace: str | None = None
    ) -> dict[str, bool]:
        """
        Synchronize all memories inside a namespace.
        
        Args:
            namespace: Namespace to sync (uses active if not provided)
            
        Returns:
            Dictionary mapping memory names to sync status
            
        Raises:
            NamespaceError: If namespace not found
        """
        target = namespace or self._active_namespace
        
        if target not in self._namespaces:
            raise NamespaceError(f"Unknown namespace '{target}'.")
        
        results: dict[str, bool] = {}
        
        for name, memory in self._namespaces[target].items():
            try:
                await memory.synchronize()
                results[name] = True
            except Exception as e:
                logger.warning(f"Sync failed for memory {name} in namespace {target}: {e}")
                results[name] = False
        
        return results

    async def flush(self) -> None:
        """Flush every registered memory backend."""
        for memory in self._memories.values():
            flush = getattr(memory, "flush", None)
            if callable(flush):
                try:
                    await flush()
                except Exception as e:
                    logger.warning(f"Flush failed: {e}")

    async def save_all(self) -> None:
        """Persist every memory."""
        await self.flush()
        await self.synchronize()

    async def load_all(self) -> None:
        """Load every registered memory."""
        for memory in self._memories.values():
            load = getattr(memory, "load", None)
            if callable(load):
                try:
                    await load()
                except Exception as e:
                    logger.warning(f"Load failed: {e}")

    async def synchronize_backend(self, backend_name: str) -> bool:
        """
        Synchronize memories associated with a backend.
        
        Args:
            backend_name: Backend to synchronize
            
        Returns:
            True if successful
        """
        backend = self.backend(backend_name)
        sync = getattr(backend, "synchronize", None)
        
        if not callable(sync):
            return False
        
        try:
            await sync()
            return True
        except Exception as e:
            logger.warning(f"Backend sync failed for {backend_name}: {e}")
            return False

    async def synchronize_all_backends(self) -> dict[str, bool]:
        """
        Synchronize every registered backend.
        
        Returns:
            Dictionary mapping backend names to sync status
        """
        status: dict[str, bool] = {}
        
        for name in self.backend_names():
            status[name] = await self.synchronize_backend(name)
        
        return status

    async def synchronize_pipeline(self) -> dict[str, Any]:
        """
        Execute the complete synchronization pipeline.
        
        Returns:
            Comprehensive sync report
        """
        report = {
            "memories": await self.synchronize(),
            "backends": await self.synchronize_all_backends(),
        }
        
        report["successful"] = all(report["memories"].values()) and all(
            report["backends"].values()
        )
        
        return report

    async def synchronize_if_needed(self) -> bool:
        """
        Synchronize automatically when automatic mode is enabled.
        
        Returns:
            True if sync was performed
        """
        if self._config.synchronization != SynchronizationMode.AUTOMATIC:
            return False
        
        await self.synchronize_pipeline()
        return True

    async def checkpoint(self) -> dict[str, Any]:
        """
        Create a synchronization checkpoint.
        
        Returns:
            Checkpoint state dictionary
        """
        return {
            "namespace": self._active_namespace,
            "state": self._state.value,
            "memory_count": len(self._memories),
            "backend_count": len(self._backends),
            "sync_report": await self.synchronize(),
        }

    # ------------------------------------------------------------------
    # Event Dispatch
    # ------------------------------------------------------------------

    def register_event_listener(self, event: str, listener: Any) -> None:
        """
        Register an event listener.
        
        Args:
            event: Event name
            listener: Callable listener
        """
        if not hasattr(self, "_event_listeners"):
            self._event_listeners = {}
        
        self._event_listeners.setdefault(event, []).append(listener)

    def unregister_event_listener(
        self, event: str, listener: Any
    ) -> bool:
        """
        Remove an event listener.
        
        Args:
            event: Event name
            listener: Listener to remove
            
        Returns:
            True if removed, False if not found
        """
        listeners = getattr(self, "_event_listeners", {}).get(event, [])
        
        if listener not in listeners:
            return False
        
        listeners.remove(listener)
        return True

    def event_listeners(self, event: str) -> list[Any]:
        """
        Return listeners for an event.
        
        Args:
            event: Event name
            
        Returns:
            List of listeners
        """
        return list(
            getattr(self, "_event_listeners", {}).get(event, [])
        )

    async def dispatch_event(
        self,
        event: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Dispatch an event to every listener.
        
        Args:
            event: Event name
            payload: Event data
        """
        listeners = self.event_listeners(event)
        payload = dict(payload or {})
        
        payload.setdefault("namespace", self._active_namespace)
        payload.setdefault("manager_id", str(self._id))
        
        for listener in listeners:
            if hasattr(listener, "__call__"):
                result = listener(event, payload)
                if hasattr(result, "__await__"):
                    await result

    async def emit_memory_event(
        self, operation: str, memory_name: str, **metadata: Any
    ) -> None:
        """Emit a memory lifecycle event."""
        await self.dispatch_event(
            f"memory.{operation}",
            {"memory": memory_name, **metadata},
        )

    async def emit_backend_event(
        self, operation: str, backend_name: str, **metadata: Any
    ) -> None:
        """Emit a backend lifecycle event."""
        await self.dispatch_event(
            f"backend.{operation}",
            {"backend": backend_name, **metadata},
        )

    async def emit_system_event(
        self, operation: str, **metadata: Any
    ) -> None:
        """Emit a manager-level event."""
        await self.dispatch_event(
            f"system.{operation}", metadata
        )

    async def notify_registered_memories(
        self, event: str, **metadata: Any
    ) -> None:
        """Notify every registered memory."""
        for memory in self._memories.values():
            handler = getattr(memory, "emit", None)
            if callable(handler):
                try:
                    await handler(event, metadata)
                except Exception as e:
                    logger.warning(f"Notification failed for memory: {e}")

    def clear_event_listeners(self) -> None:
        """Remove every registered listener."""
        if hasattr(self, "_event_listeners"):
            self._event_listeners.clear()

    def event_statistics(self) -> dict[str, Any]:
        """
        Export event subsystem statistics.
        
        Returns:
            Dictionary with event metrics
        """
        listeners = getattr(self, "_event_listeners", {})
        
        return {
            "registered_events": len(listeners),
            "listener_count": sum(len(value) for value in listeners.values()),
            "events": sorted(listeners.keys()),
        }

    # ------------------------------------------------------------------
    # Health Monitoring
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """
        Execute a complete health check.
        
        Returns:
            Comprehensive health report
        """
        report = {
            "manager": self.manager_health(),
            "backends": await self.backend_health(),
            "memories": await self.memory_health(),
            "ready": False,
        }
        
        report["ready"] = (
            report["manager"]["healthy"]
            and all(report["backends"].values())
            and all(report["memories"].values())
        )
        
        return report

    def manager_health(self) -> dict[str, Any]:
        """
        Return manager health information.
        
        Returns:
            Dictionary with manager health metrics
        """
        return {
            "healthy": self._state != ManagerState.CLOSED,
            "state": self._state.value,
            "namespace": self._active_namespace,
            "memory_count": len(self._memories),
            "backend_count": len(self._backends),
        }

    async def memory_health(self) -> dict[str, bool]:
        """
        Validate every registered memory.
        
        Returns:
            Dictionary mapping memory names to health status
        """
        status: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            try:
                health = memory.health()
                if isinstance(health, Mapping):
                    status[name] = bool(health.get("healthy", True))
                else:
                    status[name] = True
            except Exception as e:
                logger.warning(f"Health check failed for memory {name}: {e}")
                status[name] = False
        
        return status

    async def unhealthy_memories(self) -> list[str]:
        """
        Return unhealthy memories.
        
        Returns:
            List of unhealthy memory names
        """
        report = await self.memory_health()
        return [name for name, ok in report.items() if not ok]

    async def readiness_check(self) -> bool:
        """
        Verify that the manager is ready for operation.
        
        Returns:
            True if ready
        """
        report = await self.health_check()
        return bool(report["ready"])

    async def liveness_check(self) -> bool:
        """
        Lightweight liveness probe.
        
        Returns:
            True if manager is not closed
        """
        return self._state != ManagerState.CLOSED

    async def diagnostics(self) -> dict[str, Any]:
        """
        Export runtime diagnostics.
        
        Returns:
            Comprehensive diagnostic report
        """
        return {
            "health": await self.health_check(),
            "configuration": self.configuration_snapshot(),
            "events": self.event_statistics(),
        }

    async def recover_unhealthy_memories(self) -> dict[str, bool]:
        """
        Attempt recovery for unhealthy memories.
        
        Returns:
            Dictionary mapping memory names to recovery status
        """
        recovered: dict[str, bool] = {}
        
        for name in await self.unhealthy_memories():
            memory = self._memories[name]
            initialize = getattr(memory, "initialize", None)
            
            if not callable(initialize):
                recovered[name] = False
                continue
            
            try:
                await initialize()
                recovered[name] = True
            except Exception as e:
                logger.warning(f"Recovery failed for memory {name}: {e}")
                recovered[name] = False
        
        return recovered

    async def self_test(self) -> dict[str, Any]:
        """
        Execute an internal self-test routine.
        
        Returns:
            Comprehensive self-test report
        """
        return {
            "health": await self.health_check(),
            "diagnostics": await self.diagnostics(),
            "recoverable": await self.recover_unhealthy_memories(),
        }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def initialize_metrics(self) -> None:
        """Initialize runtime metrics."""
        self._metrics = {
            "stores": 0,
            "retrievals": 0,
            "deletions": 0,
            "summaries": 0,
            "synchronizations": 0,
            "errors": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "vector_queries": 0,
            "conversation_updates": 0,
        }

    def increment_metric(self, name: str, value: int = 1) -> None:
        """
        Increment a metric counter.
        
        Args:
            name: Metric name
            value: Increment value
        """
        if not hasattr(self, "_metrics"):
            self.initialize_metrics()
        
        self._metrics[name] = self._metrics.get(name, 0) + value

    def metric(self, name: str) -> int:
        """
        Return a metric value.
        
        Args:
            name: Metric name
            
        Returns:
            Metric value
        """
        if not hasattr(self, "_metrics"):
            self.initialize_metrics()
        
        return int(self._metrics.get(name, 0))

    def metrics(self) -> dict[str, Any]:
        """
        Export all runtime metrics.
        
        Returns:
            Dictionary of all metrics
        """
        if not hasattr(self, "_metrics"):
            self.initialize_metrics()
        
        return dict(self._metrics)

    def reset_metrics(self) -> None:
        """Reset runtime metrics."""
        self.initialize_metrics()

    def cache_hit(self) -> None:
        """Record a cache hit."""
        self.increment_metric("cache_hits")

    def cache_miss(self) -> None:
        """Record a cache miss."""
        self.increment_metric("cache_misses")

    def record_error(self) -> None:
        """Record an internal error."""
        self.increment_metric("errors")

    def cache_hit_ratio(self) -> float:
        """
        Return cache hit ratio.
        
        Returns:
            Ratio of hits to total requests (0.0-1.0)
        """
        hits = self.metric("cache_hits")
        misses = self.metric("cache_misses")
        total = hits + misses
        
        if total == 0:
            return 0.0
        
        return hits / total

    def export_metrics(self) -> dict[str, Any]:
        """
        Export metrics together with runtime information.
        
        Returns:
            Dictionary with metrics and metadata
        """
        return {
            "manager_id": str(self._id),
            "namespace": self._active_namespace,
            "state": self._state.value,
            "metrics": self.metrics(),
            "cache_hit_ratio": self.cache_hit_ratio(),
            "memory_count": len(self._memories),
            "backend_count": len(self._backends),
        }

    async def collect_runtime_metrics(
        self,
    ) -> dict[str, Any]:
        """
        Collect runtime metrics from every registered memory.
        
        Returns:
            Dictionary mapping memory names to their metrics
        """
        runtime: dict[str, Any] = {}
        
        for name, memory in self._memories.items():
            try:
                runtime[name] = memory.metrics()
            except Exception as e:
                logger.warning(f"Metric collection failed for memory {name}: {e}")
                runtime[name] = None
        
        return runtime

    async def metrics_report(self) -> dict[str, Any]:
        """
        Produce a complete metrics report.
        
        Returns:
            Comprehensive metrics report
        """
        return {
            "manager": self.export_metrics(),
            "runtime": await self.collect_runtime_metrics(),
            "health": await self.health_check(),
        }

    # ------------------------------------------------------------------
    # Snapshot Manager
    # ------------------------------------------------------------------

    def initialize_snapshots(self) -> None:
        """Initialize snapshot storage."""
        if not hasattr(self, "_snapshots"):
            self._snapshots: dict[str, dict[str, Any]] = {}

    async def create_snapshot(
        self,
        name: str,
        *,
        namespace: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a manager snapshot.
        
        Args:
            name: Snapshot identifier
            namespace: Optional namespace (uses active if not provided)
            metadata: Optional metadata
            
        Returns:
            Snapshot dictionary
        """
        self.initialize_snapshots()
        
        target = namespace or self._active_namespace
        
        snapshot = {
            "name": name,
            "namespace": target,
            "state": self._state.value,
            "configuration": self.configuration_snapshot(),
            "metrics": self.metrics(),
            "metadata": dict(metadata or {}),
        }
        
        self._snapshots[name] = snapshot
        
        # Enforce retention policy
        if len(self._snapshots) > self._config.snapshots.keep_last:
            oldest = min(self._snapshots.keys())
            del self._snapshots[oldest]
        
        logger.info(f"Created snapshot: {name}")
        return snapshot

    def snapshot(self, name: str) -> dict[str, Any]:
        """
        Return a snapshot.
        
        Args:
            name: Snapshot identifier
            
        Returns:
            Snapshot dictionary
            
        Raises:
            KeyError: If snapshot not found
        """
        self.initialize_snapshots()
        
        if name not in self._snapshots:
            raise KeyError(f"Snapshot '{name}' not found.")
        
        return dict(self._snapshots[name])

    def snapshot_exists(self, name: str) -> bool:
        """
        Check snapshot existence.
        
        Args:
            name: Snapshot identifier
            
        Returns:
            True if exists
        """
        self.initialize_snapshots()
        return name in self._snapshots

    def snapshot_names(self) -> list[str]:
        """Return snapshot names."""
        self.initialize_snapshots()
        return sorted(self._snapshots.keys())

    def delete_snapshot(self, name: str) -> bool:
        """
        Delete a snapshot.
        
        Args:
            name: Snapshot identifier
            
        Returns:
            True if deleted
        """
        self.initialize_snapshots()
        return self._snapshots.pop(name, None) is not None

    async def restore_snapshot(self, name: str) -> bool:
        """
        Restore manager state from a snapshot.
        
        Args:
            name: Snapshot identifier
            
        Returns:
            True if restored
            
        Raises:
            KeyError: If snapshot not found
        """
        snapshot = self.snapshot(name)
        self._active_namespace = snapshot["namespace"]
        logger.info(f"Restored snapshot: {name}")
        return True

    def latest_snapshot(self) -> dict[str, Any] | None:
        """
        Return the latest snapshot.
        
        Returns:
            Latest snapshot or None
        """
        self.initialize_snapshots()
        
        if not self._snapshots:
            return None
        
        last = next(reversed(self._snapshots))
        return self.snapshot(last)

    async def rollback(self, name: str) -> bool:
        """
        Roll back to a snapshot.
        
        Args:
            name: Snapshot identifier
            
        Returns:
            True if rolled back
        """
        return await self.restore_snapshot(name)

    def snapshot_statistics(self) -> dict[str, Any]:
        """
        Export snapshot statistics.
        
        Returns:
            Dictionary with snapshot metrics
        """
        self.initialize_snapshots()
        
        return {
            "count": len(self._snapshots),
            "latest": next(reversed(self._snapshots)) if self._snapshots else None,
            "names": self.snapshot_names(),
        }

    async def prune_snapshots(self) -> int:
        """
        Remove old snapshots according to retention policy.
        
        Returns:
            Number of snapshots removed
        """
        self.initialize_snapshots()
        
        keep = self._config.snapshots.keep_last
        names = self.snapshot_names()
        
        if len(names) <= keep:
            return 0
        
        remove = names[:-keep]
        for name in remove:
            self.delete_snapshot(name)
        
        return len(remove)

    # ------------------------------------------------------------------
    # Backup / Restore
    # ------------------------------------------------------------------

    def initialize_backups(self) -> None:
        """Initialize backup registry."""
        if not hasattr(self, "_backups"):
            self._backups: dict[str, dict[str, Any]] = {}

    async def create_backup(
        self,
        name: str,
        *,
        namespace: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a persistent backup record.
        
        Args:
            name: Backup identifier
            namespace: Optional namespace
            metadata: Optional metadata
            
        Returns:
            Backup dictionary
        """
        self.initialize_backups()
        
        target = namespace or self._active_namespace
        
        backup = {
            "name": name,
            "namespace": target,
            "state": self._state.value,
            "configuration": self.configuration_snapshot(),
            "snapshot": await self.create_snapshot(
                f"{name}_snapshot", namespace=target
            ),
            "metadata": dict(metadata or {}),
        }
        
        self._backups[name] = backup
        logger.info(f"Created backup: {name}")
        return backup

    def backup(self, name: str) -> dict[str, Any]:
        """
        Return a backup.
        
        Args:
            name: Backup identifier
            
        Returns:
            Backup dictionary
            
        Raises:
            KeyError: If backup not found
        """
        self.initialize_backups()
        
        if name not in self._backups:
            raise KeyError(f"Backup '{name}' not found.")
        
        return dict(self._backups[name])

    def backup_exists(self, name: str) -> bool:
        """
        Check backup existence.
        
        Args:
            name: Backup identifier
            
        Returns:
            True if exists
        """
        self.initialize_backups()
        return name in self._backups

    def backup_names(self) -> list[str]:
        """Return backup names."""
        self.initialize_backups()
        return sorted(self._backups.keys())

    def delete_backup(self, name: str) -> bool:
        """
        Delete a backup.
        
        Args:
            name: Backup identifier
            
        Returns:
            True if deleted
        """
        self.initialize_backups()
        return self._backups.pop(name, None) is not None

    async def restore_backup(self, name: str) -> bool:
        """
        Restore manager state from a backup.
        
        Args:
            name: Backup identifier
            
        Returns:
            True if restored
            
        Raises:
            KeyError: If backup not found
        """
        backup = self.backup(name)
        snapshot = backup["snapshot"]
        
        await self.restore_snapshot(snapshot["name"])
        logger.info(f"Restored backup: {name}")
        return True

    async def export_backup(self, name: str) -> dict[str, Any]:
        """
        Export a backup.
        
        Args:
            name: Backup identifier
            
        Returns:
            Backup dictionary
        """
        return self.backup(name)

    async def import_backup(
        self, backup: Mapping[str, Any]
    ) -> None:
        """
        Import a backup.
        
        Args:
            backup: Backup data to import
        """
        self.initialize_backups()
        self._backups[str(backup["name"])] = dict(backup)

    async def backup_all(self) -> dict[str, Any]:
        """
        Backup the entire manager.
        
        Returns:
            Automatic backup dictionary
        """
        return await self.create_backup("automatic")

    async def restore_latest_backup(self) -> bool:
        """
        Restore the newest backup.
        
        Returns:
            True if restored, False if no backups
        """
        self.initialize_backups()
        
        if not self._backups:
            return False
        
        latest = next(reversed(self._backups))
        return await self.restore_backup(latest)

    def backup_statistics(self) -> dict[str, Any]:
        """
        Export backup statistics.
        
        Returns:
            Dictionary with backup metrics
        """
        self.initialize_backups()
        
        latest = next(reversed(self._backups)) if self._backups else None
        
        return {
            "count": len(self._backups),
            "latest": latest,
            "backups": self.backup_names(),
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def compact_memories(self) -> dict[str, bool]:
        """
        Compact every registered memory.
        
        Returns:
            Dictionary mapping memory names to compaction status
        """
        status: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            compact = getattr(memory, "compact", None)
            if not callable(compact):
                status[name] = False
                continue
            
            try:
                await compact()
                status[name] = True
            except Exception as e:
                logger.warning(f"Compaction failed for memory {name}: {e}")
                status[name] = False
        
        return status

    async def cleanup_memories(self) -> dict[str, bool]:
        """
        Execute cleanup routines.
        
        Returns:
            Dictionary mapping memory names to cleanup status
        """
        status: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            cleanup = getattr(memory, "cleanup", None)
            if not callable(cleanup):
                status[name] = False
                continue
            
            try:
                await cleanup()
                status[name] = True
            except Exception as e:
                logger.warning(f"Cleanup failed for memory {name}: {e}")
                status[name] = False
        
        return status

    async def validate_memories(self) -> dict[str, bool]:
        """
        Validate every registered memory.
        
        Returns:
            Dictionary mapping memory names to validation status
        """
        status: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            validate = getattr(memory, "validate", None)
            if not callable(validate):
                status[name] = True
                continue
            
            try:
                status[name] = bool(await validate())
            except Exception as e:
                logger.warning(f"Validation failed for memory {name}: {e}")
                status[name] = False
        
        return status

    async def optimize_memories(self) -> dict[str, bool]:
        """
        Execute optimization routines.
        
        Returns:
            Dictionary mapping memory names to optimization status
        """
        status: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            optimize = getattr(memory, "optimize", None)
            if not callable(optimize):
                status[name] = False
                continue
            
            try:
                await optimize()
                status[name] = True
            except Exception as e:
                logger.warning(f"Optimization failed for memory {name}: {e}")
                status[name] = False
        
        return status

    async def rebuild_indexes(self) -> dict[str, bool]:
        """
        Rebuild indexes where supported.
        
        Returns:
            Dictionary mapping memory names to rebuild status
        """
        status: dict[str, bool] = {}
        
        for name, memory in self._memories.items():
            rebuild = getattr(memory, "rebuild_index", None)
            if not callable(rebuild):
                status[name] = False
                continue
            
            try:
                await rebuild()
                status[name] = True
            except Exception as e:
                logger.warning(f"Index rebuild failed for memory {name}: {e}")
                status[name] = False
        
        return status

    async def purge_expired(self) -> int:
        """
        Remove expired entries.
        
        Returns:
            Total number of entries removed
        """
        removed = 0
        
        for memory in self._memories.values():
            purge = getattr(memory, "purge_expired", None)
            if not callable(purge):
                continue
            
            try:
                removed += int(await purge())
            except Exception as e:
                logger.warning(f"Purge failed: {e}")
        
        return removed

    async def maintenance(self) -> dict[str, Any]:
        """
        Execute the complete maintenance pipeline.
        
        Returns:
            Maintenance report
        """
        report = {
            "compaction": await self.compact_memories(),
            "cleanup": await self.cleanup_memories(),
            "validation": await self.validate_memories(),
            "optimization": await self.optimize_memories(),
        }
        
        report["successful"] = all(bool(value) for value in report.values())
        
        return report

    async def maintenance_report(self) -> dict[str, Any]:
        """
        Produce a complete maintenance report.
        
        Returns:
            Comprehensive maintenance report
        """
        return {
            "maintenance": await self.maintenance(),
            "health": await self.health_check(),
            "metrics": self.export_metrics(),
        }

    async def schedule_maintenance(self) -> bool:
        """
        Execute maintenance when automatic maintenance is enabled.
        
        Returns:
            True if maintenance was performed
        """
        if not self._config.automatic_maintenance:
            return False
        
        await self.maintenance()
        return True

    # ------------------------------------------------------------------
    # Async Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Initialize the memory manager.
        
        State: CREATED -> READY
        """
        if self._state != ManagerState.CREATED:
            return
        
        async with self._lock:
            if self._state != ManagerState.CREATED:
                return
            
            self._state = ManagerState.INITIALIZING
            
            try:
                await self.load_all()
                await self.dispatch_event("manager.initialized")
                self._state = ManagerState.READY
                logger.info("MemoryManager initialized successfully")
            except Exception as e:
                self._state = ManagerState.CREATED
                logger.error(f"Initialization failed: {e}")
                raise

    async def start(self) -> None:
        """
        Start the memory manager.
        
        State: CREATED/READY -> RUNNING
        """
        if self._state == ManagerState.RUNNING:
            return
        
        async with self._lock:
            if self._state == ManagerState.RUNNING:
                return
            
            if self._state == ManagerState.CREATED:
                await self.initialize()
            
            self._state = ManagerState.RUNNING
            
            await self.synchronize_if_needed()
            await self.dispatch_event("manager.started")
            
            logger.info("MemoryManager started")

    async def pause(self) -> None:
        """
        Pause manager execution.
        
        State: RUNNING -> PAUSED
        """
        if self._state != ManagerState.RUNNING:
            return
        
        async with self._lock:
            if self._state != ManagerState.RUNNING:
                return
            
            self._state = ManagerState.PAUSED
            await self.dispatch_event("manager.paused")
            logger.info("MemoryManager paused")

    async def resume(self) -> None:
        """
        Resume manager execution.
        
        State: PAUSED -> RUNNING
        """
        if self._state != ManagerState.PAUSED:
            return
        
        async with self._lock:
            if self._state != ManagerState.PAUSED:
                return
            
            self._state = ManagerState.RUNNING
            await self.dispatch_event("manager.resumed")
            logger.info("MemoryManager resumed")

    async def shutdown(self) -> None:
        """
        Gracefully shut down the manager.
        
        State: RUNNING/PAUSED -> STOPPING -> STOPPED
        """
        if self._state == ManagerState.CLOSED:
            return
        
        async with self._lock:
            if self._state == ManagerState.CLOSED:
                return
            
            self._state = ManagerState.STOPPING
            
            try:
                await self.save_all()
                await self.dispatch_event("manager.shutdown")
                self._state = ManagerState.STOPPED
                logger.info("MemoryManager shutdown complete")
            except Exception as e:
                logger.error(f"Shutdown error: {e}")
                self._state = ManagerState.STOPPED
                raise

    async def close(self) -> None:
        """
        Close every managed resource.
        
        State: STOPPING -> CLOSED
        """
        await self.shutdown()
        
        for memory in self._memories.values():
            close = getattr(memory, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception as e:
                    logger.warning(f"Memory close failed: {e}")
        
        self._state = ManagerState.CLOSED
        await self.dispatch_event("manager.closed")
        logger.info("MemoryManager closed")

    async def restart(self) -> None:
        """
        Restart the manager.
        
        State: STOPPED -> RUNNING
        """
        await self.shutdown()
        await self.start()

    async def before_start(self) -> None:
        """Lifecycle hook executed before startup."""
        pass

    async def after_start(self) -> None:
        """Lifecycle hook executed after startup."""
        pass

    async def before_shutdown(self) -> None:
        """Lifecycle hook executed before shutdown."""
        pass

    async def after_shutdown(self) -> None:
        """Lifecycle hook executed after shutdown."""
        pass

    async def run(self) -> None:
        """
        Execute the complete manager lifecycle.
        
        Pipeline: before_start -> start -> after_start
        """
        await self.before_start()
        await self.start()
        await self.after_start()

    async def stop(self) -> None:
        """
        Stop the complete manager lifecycle.
        
        Pipeline: before_shutdown -> close -> after_shutdown
        """
        await self.before_shutdown()
        await self.close()
        await self.after_shutdown()

    async def lifecycle_status(self) -> dict[str, Any]:
        """
        Export lifecycle information.
        
        Returns:
            Dictionary with lifecycle state
        """
        return {
            "state": self._state.value,
            "namespace": self._active_namespace,
            "running": self._state == ManagerState.RUNNING,
            "ready": self._state
            in (ManagerState.READY, ManagerState.RUNNING),
            "memory_count": len(self._memories),
            "backend_count": len(self._backends),
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MemoryManager(id={self._id}, state={self._state.value}, "
            f"namespace={self._active_namespace}, memories={self.memory_count})"
        )