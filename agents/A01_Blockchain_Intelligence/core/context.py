"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.context

Purpose:
    Shared execution context definitions used throughout the Core runtime.

This file contains only the foundation layer:

- Constants
- Type aliases
- Context identifiers
- Metadata models
- Base dataclasses

Higher-level runtime logic (AgentContext, ContextVar management,
dependency injection, validation, serialization, etc.) is implemented
in later parts.
"""

from __future__ import annotations

import time
import uuid

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, TypeAlias

# =============================================================================
# Constants
# =============================================================================

DEFAULT_CONTEXT_VERSION: Final[str] = "1.0"

UNKNOWN_SESSION: Final[str] = "unknown"

UNKNOWN_REQUEST: Final[str] = "unknown"

UNKNOWN_WORKFLOW: Final[str] = "unknown"

UNKNOWN_TASK: Final[str] = "unknown"

SYSTEM_USER: Final[str] = "system"

DEFAULT_TIMEOUT_SECONDS: Final[int] = 30

# =============================================================================
# Type Aliases
# =============================================================================

ContextID: TypeAlias = str

SessionID: TypeAlias = str

RequestID: TypeAlias = str

WorkflowID: TypeAlias = str

TaskID: TypeAlias = str

CorrelationID: TypeAlias = str

TraceID: TypeAlias = str

ChainName: TypeAlias = str

JsonDict: TypeAlias = dict[str, Any]

# =============================================================================
# Helper Functions
# =============================================================================


def generate_id() -> str:
    """
    Generate a UUID4 string.

    Used for request, task, workflow and session identifiers.
    """
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """
    Return current UTC datetime.
    """
    return datetime.now(UTC)


def monotonic_ms() -> int:
    """
    High precision monotonic clock.

    Useful for execution duration calculations.
    """
    return int(time.perf_counter() * 1000)


# =============================================================================
# Context Identifiers
# =============================================================================


@dataclass(slots=True, frozen=True)
class ContextIdentifiers:
    """
    Immutable identifiers shared across an execution.

    These IDs allow complete tracing of a request through
    the entire execution pipeline.
    """

    context_id: ContextID = field(default_factory=generate_id)

    session_id: SessionID = UNKNOWN_SESSION

    request_id: RequestID = field(default_factory=generate_id)

    workflow_id: WorkflowID = UNKNOWN_WORKFLOW

    task_id: TaskID = UNKNOWN_TASK

    correlation_id: CorrelationID = field(default_factory=generate_id)

    trace_id: TraceID = field(default_factory=generate_id)

    chain: ChainName | None = None


# =============================================================================
# Metadata
# =============================================================================


@dataclass(slots=True)
class ContextMetadata:
    """
    Runtime metadata attached to the current execution.
    """

    created_at: datetime = field(default_factory=utc_now)

    started_at: datetime | None = None

    finished_at: datetime | None = None

    created_monotonic_ms: int = field(default_factory=monotonic_ms)

    user_id: str = SYSTEM_USER

    tenant_id: str | None = None

    source: str = "internal"

    tags: list[str] = field(default_factory=list)

    labels: dict[str, str] = field(default_factory=dict)

    extra: JsonDict = field(default_factory=dict)


# =============================================================================
# Audit Metadata
# =============================================================================


@dataclass(slots=True)
class AuditMetadata:
    """
    Audit information used by logging and observability.
    """

    actor: str = SYSTEM_USER

    ip_address: str | None = None

    user_agent: str | None = None

    operation: str | None = None

    resource: str | None = None

    success: bool = True

    message: str | None = None


# =============================================================================
# Execution Statistics
# =============================================================================


@dataclass(slots=True)
class ExecutionStats:
    """
    Lightweight execution statistics.

    Full runtime metrics will be added later by RuntimeContext.
    """

    started_ms: int = field(default_factory=monotonic_ms)

    finished_ms: int | None = None

    duration_ms: int = 0

    retries: int = 0

    tool_calls: int = 0

    rpc_calls: int = 0

    cache_hits: int = 0

    cache_misses: int = 0

    errors: int = 0


# =============================================================================
# Base Context Object
# =============================================================================


@dataclass(slots=True)
class BaseContext:
    """
    Base object inherited by higher-level context models.

    This class intentionally contains only immutable identifiers,
    metadata, and execution statistics.
    """

    identifiers: ContextIdentifiers = field(
        default_factory=ContextIdentifiers
    )

    metadata: ContextMetadata = field(
        default_factory=ContextMetadata
    )

    audit: AuditMetadata = field(
        default_factory=AuditMetadata
    )

    stats: ExecutionStats = field(
        default_factory=ExecutionStats
    )

    def age_seconds(self) -> float:
        """
        Return context age in seconds.
        """
        return (
            utc_now() - self.metadata.created_at
        ).total_seconds()

    def is_finished(self) -> bool:
        """
        True if execution has completed.
        """
        return self.metadata.finished_at is not None

    def mark_started(self) -> None:
        """
        Mark execution start.
        """
        self.metadata.started_at = utc_now()

    def mark_finished(self) -> None:
        """
        Mark execution completion.
        """
        self.metadata.finished_at = utc_now()

        if self.stats.finished_ms is None:
            self.stats.finished_ms = monotonic_ms()

        self.stats.duration_ms = (
            self.stats.finished_ms
            - self.stats.started_ms
        )


@dataclass(slots=True)
class SessionContext(BaseContext):
    """
    Represents a logical user session.

    A session may contain multiple requests and multiple
    execution workflows.
    """

    session_name: str | None = None

    user_id: str = SYSTEM_USER

    authenticated: bool = False

    roles: set[str] = field(default_factory=set)

    permissions: set[str] = field(default_factory=set)

    attributes: JsonDict = field(default_factory=dict)

    last_activity: datetime = field(default_factory=utc_now)

    expires_at: datetime | None = None

    def touch(self) -> None:
        """Update session activity timestamp."""
        self.last_activity = utc_now()

    def is_expired(self) -> bool:
        """Return True if session has expired."""
        if self.expires_at is None:
            return False
        return utc_now() >= self.expires_at

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


# =============================================================================
# Request Context
# =============================================================================

@dataclass(slots=True)
class RequestContext(BaseContext):
    """
    Context describing one incoming request.
    """

    method: str = "INTERNAL"

    endpoint: str | None = None

    source: str = "system"

    client_ip: str | None = None

    headers: dict[str, str] = field(default_factory=dict)

    query: dict[str, str] = field(default_factory=dict)

    parameters: JsonDict = field(default_factory=dict)

    payload: JsonDict = field(default_factory=dict)

    received_at: datetime = field(default_factory=utc_now)

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled


# =============================================================================
# Execution Context
# =============================================================================

@dataclass(slots=True)
class ExecutionContext(BaseContext):
    """
    Runtime execution information.

    This object exists only while a task is executing.
    """

    execution_id: str = field(default_factory=generate_id)

    worker_id: str | None = None

    execution_mode: str = "async"

    retry_count: int = 0

    max_retries: int = 3

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    cancelled: bool = False

    completed: bool = False

    current_tool: str | None = None

    current_chain: ChainName | None = None

    variables: JsonDict = field(default_factory=dict)

    def mark_completed(self) -> None:
        self.completed = True
        self.mark_finished()

    def increment_retry(self) -> None:
        self.retry_count += 1

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def cancel(self) -> None:
        self.cancelled = True


# =============================================================================
# Runtime Context
# =============================================================================

@dataclass(slots=True)
class RuntimeContext(BaseContext):
    """
    Global runtime state shared by the running agent.
    """

    runtime_id: str = field(default_factory=generate_id)

    process_id: int | None = None

    hostname: str | None = None

    version: str = DEFAULT_CONTEXT_VERSION

    environment: str = "development"

    started_at: datetime = field(default_factory=utc_now)

    uptime_seconds: float = 0.0

    active_tasks: int = 0

    queued_tasks: int = 0

    completed_tasks: int = 0

    failed_tasks: int = 0

    health: str = "healthy"

    metadata: JsonDict = field(default_factory=dict)

    def update_uptime(self) -> None:
        self.uptime_seconds = (
            utc_now() - self.started_at
        ).total_seconds()

    def task_started(self) -> None:
        self.active_tasks += 1

    def task_completed(self) -> None:
        if self.active_tasks > 0:
            self.active_tasks -= 1
        self.completed_tasks += 1

    def task_failed(self) -> None:
        if self.active_tasks > 0:
            self.active_tasks -= 1
        self.failed_tasks += 1

    @property
    def total_processed(self) -> int:
        return self.completed_tasks + self.failed_tasks


# =============================================================================
# Context Factory Helpers
# =============================================================================

def create_session_context(**kwargs: Any) -> SessionContext:
    """Create a SessionContext."""
    return SessionContext(**kwargs)


def create_request_context(**kwargs: Any) -> RequestContext:
    """Create a RequestContext."""
    return RequestContext(**kwargs)


def create_execution_context(**kwargs: Any) -> ExecutionContext:
    """Create an ExecutionContext."""
    return ExecutionContext(**kwargs)


def create_runtime_context(**kwargs: Any) -> RuntimeContext:
    """Create a RuntimeContext."""
    return RuntimeContext(**kwargs)

# =============================================================================
# Standard Library Imports (Part 3)
# =============================================================================

from contextvars import ContextVar, Token
from asyncio import Lock

# =============================================================================
# Service Registry
# =============================================================================


@dataclass(slots=True)
class ServiceRegistry:
    """
    Lightweight dependency injection container.

    Stores runtime services used by the agent.

    Examples:
        logger
        settings
        rpc_manager
        memory
        state_manager
        contract_manager
        event_bus
        tool_registry
    """

    _services: dict[str, Any] = field(default_factory=dict)

    def register(self, name: str, service: Any) -> None:
        """Register a runtime service."""
        self._services[name] = service

    def resolve(self, name: str) -> Any:
        """Resolve a registered service."""
        if name not in self._services:
            raise KeyError(f"Unknown service: {name}")
        return self._services[name]

    def remove(self, name: str) -> None:
        self._services.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._services

    def clear(self) -> None:
        self._services.clear()

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._services.keys()))

    def to_dict(self) -> dict[str, str]:
        return {
            key: type(value).__name__
            for key, value in self._services.items()
        }


# =============================================================================
# Context Variable
# =============================================================================

_CURRENT_CONTEXT: ContextVar["AgentContext | None"] = ContextVar(
    "cie_os_current_context",
    default=None,
)

# =============================================================================
# Agent Context
# =============================================================================


@dataclass(slots=True)
class AgentContext(BaseContext):
    """
    Root execution context.

    Every running agent owns exactly one AgentContext.

    It aggregates:

        RuntimeContext
        SessionContext
        RequestContext
        ExecutionContext
        ServiceRegistry
    """

    runtime: RuntimeContext = field(
        default_factory=RuntimeContext
    )

    session: SessionContext = field(
        default_factory=SessionContext
    )

    request: RequestContext = field(
        default_factory=RequestContext
    )

    execution: ExecutionContext = field(
        default_factory=ExecutionContext
    )

    services: ServiceRegistry = field(
        default_factory=ServiceRegistry
    )

    state: JsonDict = field(default_factory=dict)

    shared: JsonDict = field(default_factory=dict)

    _lock: Lock = field(
        default_factory=Lock,
        init=False,
        repr=False,
    )

    # ------------------------------------------------------------------
    # Service Helpers
    # ------------------------------------------------------------------

    def register_service(
        self,
        name: str,
        service: Any,
    ) -> None:
        self.services.register(name, service)

    def get_service(self, name: str) -> Any:
        return self.services.resolve(name)

    def has_service(self, name: str) -> bool:
        return self.services.has(name)

    def remove_service(self, name: str) -> None:
        self.services.remove(name)

    # ------------------------------------------------------------------
    # Shared State
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        self.shared[key] = value

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self.shared.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.shared

    def delete(self, key: str) -> None:
        self.shared.pop(key, None)

    def clear_shared(self) -> None:
        self.shared.clear()

    # ------------------------------------------------------------------
    # Async Lock
    # ------------------------------------------------------------------

    @property
    def lock(self) -> Lock:
        return self._lock

# =============================================================================
# Active Context API
# =============================================================================


def current_context() -> AgentContext:
    """
    Return current active AgentContext.
    """
    ctx = _CURRENT_CONTEXT.get()

    if ctx is None:
        raise RuntimeError(
            "No active AgentContext."
        )

    return ctx


def has_current_context() -> bool:
    return _CURRENT_CONTEXT.get() is not None


def set_current_context(
    context: AgentContext,
) -> Token:
    """
    Activate a context.

    Returns ContextVar token.
    """
    return _CURRENT_CONTEXT.set(context)


def reset_current_context(
    token: Token,
) -> None:
    """
    Restore previous context.
    """
    _CURRENT_CONTEXT.reset(token)


# =============================================================================
# Context Scope
# =============================================================================


class ContextScope:
    """
    Context manager for temporary AgentContext activation.

    Example:

        with ContextScope(ctx):
            ...

    Automatically restores previous context.
    """

    def __init__(
        self,
        context: AgentContext,
    ):
        self._context = context
        self._token: Token | None = None

    def __enter__(self) -> AgentContext:
        self._token = set_current_context(
            self._context
        )
        return self._context

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        if self._token is not None:
            reset_current_context(self._token)

            # =============================================================================
# Validation Helpers
# =============================================================================

def validate_context(context: AgentContext) -> None:
    """
    Validate that the context contains the minimum required objects.
    """

    if context.runtime is None:
        raise ValueError("RuntimeContext is missing.")

    if context.session is None:
        raise ValueError("SessionContext is missing.")

    if context.request is None:
        raise ValueError("RequestContext is missing.")

    if context.execution is None:
        raise ValueError("ExecutionContext is missing.")

    if context.services is None:
        raise ValueError("ServiceRegistry is missing.")


# =============================================================================
# Serialization
# =============================================================================

def context_to_dict(context: AgentContext) -> JsonDict:
    """
    Export the current context into a JSON-compatible dictionary.

    Secrets and service instances are intentionally excluded.
    """

    return {
        "identifiers": {
            "context_id": context.identifiers.context_id,
            "session_id": context.identifiers.session_id,
            "request_id": context.identifiers.request_id,
            "workflow_id": context.identifiers.workflow_id,
            "task_id": context.identifiers.task_id,
            "correlation_id": context.identifiers.correlation_id,
            "trace_id": context.identifiers.trace_id,
            "chain": context.identifiers.chain,
        },
        "metadata": {
            "created_at": context.metadata.created_at.isoformat(),
            "started_at": (
                context.metadata.started_at.isoformat()
                if context.metadata.started_at
                else None
            ),
            "finished_at": (
                context.metadata.finished_at.isoformat()
                if context.metadata.finished_at
                else None
            ),
            "user_id": context.metadata.user_id,
            "tenant_id": context.metadata.tenant_id,
            "source": context.metadata.source,
            "tags": list(context.metadata.tags),
            "labels": dict(context.metadata.labels),
        },
        "runtime": {
            "runtime_id": context.runtime.runtime_id,
            "environment": context.runtime.environment,
            "health": context.runtime.health,
            "active_tasks": context.runtime.active_tasks,
            "queued_tasks": context.runtime.queued_tasks,
            "completed_tasks": context.runtime.completed_tasks,
            "failed_tasks": context.runtime.failed_tasks,
        },
        "services": context.services.to_dict(),
        "shared": dict(context.shared),
    }


# =============================================================================
# Clone Helpers
# =============================================================================

def clone_context(context: AgentContext) -> AgentContext:
    """
    Create a shallow runtime clone.

    Service instances are preserved.
    Shared dictionaries are copied.
    """

    clone = AgentContext()

    clone.runtime = context.runtime
    clone.session = context.session
    clone.request = context.request
    clone.execution = context.execution

    clone.services = context.services

    clone.state = dict(context.state)
    clone.shared = dict(context.shared)

    return clone


# =============================================================================
# Reset Helpers
# =============================================================================

def reset_context(context: AgentContext) -> None:
    """
    Reset runtime state while preserving
    registered services.
    """

    context.state.clear()
    context.shared.clear()

    context.execution = ExecutionContext()
    context.request = RequestContext()

    context.runtime.active_tasks = 0
    context.runtime.queued_tasks = 0


# =============================================================================
# Debug Helpers
# =============================================================================

def dump_context(context: AgentContext) -> JsonDict:
    """
    Convenience helper for debugging.
    """
    return context_to_dict(context)


# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # Base
    "BaseContext",
    "ContextIdentifiers",
    "ContextMetadata",
    "AuditMetadata",
    "ExecutionStats",

    # Runtime contexts
    "SessionContext",
    "RequestContext",
    "ExecutionContext",
    "RuntimeContext",
    "AgentContext",

    # Registry
    "ServiceRegistry",

    # Active context
    "current_context",
    "has_current_context",
    "set_current_context",
    "reset_current_context",
    "ContextScope",

    # Utilities
    "validate_context",
    "context_to_dict",
    "clone_context",
    "reset_context",
    "dump_context",

    # Helpers
    "generate_id",
    "utc_now",
    "monotonic_ms",
]