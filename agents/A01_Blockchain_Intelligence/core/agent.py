"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.agent

Description
-----------
Enterprise-grade BaseAgent foundation for the CIE-OS platform.

This module provides:

- Shared constants and type aliases
- Validation helpers and runtime utilities
- Enums for capabilities, status, priority, health, execution mode
- Configuration, identity, metadata, and statistics dataclasses
- BaseAgent: the async-first base class that every CIE-OS agent inherits

Concrete agents (BlockchainAgent, WalletAnalyzer, MEVDetector, etc.)
override ``execute()`` and register domain-specific tools, services,
and event handlers.
"""

from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================

import asyncio
import logging
import re
import time
import uuid

from contextlib import suppress
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import (
    Any,
    Final,
    NewType,
    TypeAlias,
)

from dataclasses import (
    dataclass,
    field,
)

# =============================================================================
# Project Imports
# =============================================================================

from .context import AgentContext
from .runtime import AgentRuntime
from .lifecycle import AgentLifecycle

# =============================================================================
# Logger
# =============================================================================

logger = logging.getLogger(__name__)

# =============================================================================
# Type Aliases
# =============================================================================

JSONPrimitive: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
)

JSONValue: TypeAlias = (
    JSONPrimitive
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)

Metadata: TypeAlias = dict[str, JSONValue]

Headers: TypeAlias = dict[str, str]

ToolArguments: TypeAlias = dict[str, Any]

ToolResult: TypeAlias = dict[str, Any]

AgentID = NewType("AgentID", str)

TaskID = NewType("TaskID", str)

ExecutionID = NewType("ExecutionID", str)

# =============================================================================
# Constants
# =============================================================================

DEFAULT_AGENT_VERSION: Final[str] = "1.0.0"

DEFAULT_TIMEOUT_SECONDS: Final[int] = 300

DEFAULT_HEARTBEAT_SECONDS: Final[int] = 30

DEFAULT_RETRY_LIMIT: Final[int] = 3

DEFAULT_PRIORITY: Final[int] = 50

DEFAULT_MAX_CONCURRENT_TASKS: Final[int] = 100

DEFAULT_DESCRIPTION: Final[str] = (
    "Enterprise Blockchain Intelligence Agent"
)

SEMVER_PATTERN: Final = re.compile(
    r"^\d+\.\d+\.\d+$"
)

AGENT_NAME_PATTERN: Final = re.compile(
    r"^[A-Za-z0-9_.\- ]{3,64}$"
)

# =============================================================================
# Helper Functions
# =============================================================================


def utc_now() -> datetime:
    return datetime.now(UTC)


def monotonic_ms() -> int:
    return int(time.perf_counter() * 1000)


def generate_agent_id() -> AgentID:
    return AgentID(str(uuid.uuid4()))


def generate_execution_id() -> ExecutionID:
    return ExecutionID(str(uuid.uuid4()))


def generate_task_id() -> TaskID:
    return TaskID(str(uuid.uuid4()))


def validate_agent_name(name: str) -> str:
    name = name.strip()

    if not AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"Invalid agent name: {name}"
        )

    return name


def validate_version(version: str) -> str:
    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(
            f"Invalid version: {version}"
        )

    return version


def ensure_directory(path: Path) -> Path:
    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def safe_metadata(
    metadata: Metadata | None,
) -> Metadata:
    return metadata or {}


def is_async_callable(
    obj: Any,
) -> bool:
    return (
        asyncio.iscoroutinefunction(obj)
        or asyncio.iscoroutine(obj)
    )


# =============================================================================
# Agent Capabilities
# =============================================================================


class AgentCapability(StrEnum):

    # Blockchain Intelligence
    ANALYZE_TRANSACTIONS = "analyze_transactions"
    ANALYZE_WALLETS = "analyze_wallets"
    ANALYZE_CONTRACTS = "analyze_contracts"
    TOKEN_ANALYSIS = "token_analysis"
    NFT_ANALYSIS = "nft_analysis"
    DEFI_ANALYSIS = "defi_analysis"
    BRIDGE_ANALYSIS = "bridge_analysis"
    MEV_DETECTION = "mev_detection"
    GAS_ANALYSIS = "gas_analysis"
    RISK_SCORING = "risk_scoring"
    SCAM_DETECTION = "scam_detection"
    COMPLIANCE_ANALYSIS = "compliance_analysis"

    # Intelligence
    MARKET_INTELLIGENCE = "market_intelligence"
    SOCIAL_INTELLIGENCE = "social_intelligence"
    NEWS_INTELLIGENCE = "news_intelligence"
    ONCHAIN_INTELLIGENCE = "onchain_intelligence"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    ENTITY_RESOLUTION = "entity_resolution"
    KNOWLEDGE_GRAPH = "knowledge_graph"

    # AI
    TOOL_EXECUTION = "tool_execution"
    MEMORY = "memory"
    REASONING = "reasoning"
    PLANNING = "planning"
    AUTONOMOUS_EXECUTION = "autonomous_execution"
    MULTI_AGENT = "multi_agent"
    HUMAN_APPROVAL = "human_approval"

    # Infrastructure
    EVENT_PROCESSING = "event_processing"
    STATE_SYNCHRONIZATION = "state_synchronization"
    AUDIT_LOGGING = "audit_logging"
    OBSERVABILITY = "observability"
    HEALTH_MONITORING = "health_monitoring"


# =============================================================================
# Agent Status
# =============================================================================


class AgentStatus(StrEnum):

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    IDLE = "idle"
    RUNNING = "running"
    BUSY = "busy"
    WAITING = "waiting"
    PAUSED = "paused"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    SHUTDOWN = "shutdown"


# =============================================================================
# Agent Priority
# =============================================================================


class AgentPriority(IntEnum):

    BACKGROUND = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    CRITICAL = 100


# =============================================================================
# Execution Mode
# =============================================================================


class ExecutionMode(StrEnum):

    MANUAL = "manual"
    INTERACTIVE = "interactive"
    SCHEDULED = "scheduled"
    EVENT_DRIVEN = "event_driven"
    STREAMING = "streaming"
    AUTONOMOUS = "autonomous"


# =============================================================================
# Health Status
# =============================================================================


class HealthStatus(StrEnum):

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"
    FAILED = "failed"


# =============================================================================
# Restart Policy
# =============================================================================


class RestartPolicy(StrEnum):

    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"
    EXPONENTIAL_BACKOFF = "exponential_backoff"


# =============================================================================
# Audit Severity
# =============================================================================


class AuditSeverity(StrEnum):

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =============================================================================
# Supported Chain
# =============================================================================


@dataclass(slots=True)
class SupportedChain:

    chain_id: int
    name: str
    symbol: str
    ecosystem: str
    rpc_provider: str = ""
    explorer_url: str = ""
    native_currency: str = ""
    enabled: bool = True
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.symbol = self.symbol.upper()


# =============================================================================
# Supported Protocol
# =============================================================================


@dataclass(slots=True)
class SupportedProtocol:

    name: str
    category: str
    version: str = "1.0"
    enabled: bool = True
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = self.name.strip()


# =============================================================================
# Agent Metadata
# =============================================================================


@dataclass(slots=True)
class AgentMetadata:

    author: str = "CIE-OS"
    organization: str = "CIE"
    repository: str = ""
    documentation: str = ""
    license: str = "MIT"
    description: str = DEFAULT_DESCRIPTION
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    tags: list[str] = field(default_factory=list)
    metadata: Metadata = field(default_factory=dict)


# =============================================================================
# Agent Identity
# =============================================================================


@dataclass(slots=True)
class AgentIdentity:

    agent_id: AgentID = field(default_factory=generate_agent_id)
    name: str = "Blockchain Intelligence Agent"
    version: str = DEFAULT_AGENT_VERSION
    vendor: str = "CIE-OS"
    instance_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.name = validate_agent_name(self.name)
        self.version = validate_version(self.version)


# =============================================================================
# Agent Configuration
# =============================================================================


@dataclass(slots=True)
class AgentConfig:

    identity: AgentIdentity = field(
        default_factory=AgentIdentity
    )
    metadata: AgentMetadata = field(
        default_factory=AgentMetadata
    )
    enabled: bool = True
    priority: AgentPriority = AgentPriority.NORMAL
    execution_mode: ExecutionMode = (
        ExecutionMode.INTERACTIVE
    )
    restart_policy: RestartPolicy = (
        RestartPolicy.ON_FAILURE
    )
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    retry_limit: int = DEFAULT_RETRY_LIMIT
    max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS
    capabilities: set[AgentCapability] = field(
        default_factory=set
    )
    supported_chains: list[SupportedChain] = field(
        default_factory=list
    )
    supported_protocols: list[SupportedProtocol] = field(
        default_factory=list
    )
    metadata_extra: Metadata = field(
        default_factory=dict
    )

    def add_capability(
        self,
        capability: AgentCapability,
    ) -> None:
        self.capabilities.add(capability)

    def supports(
        self,
        capability: AgentCapability,
    ) -> bool:
        return capability in self.capabilities

    def add_chain(
        self,
        chain: SupportedChain,
    ) -> None:
        self.supported_chains.append(chain)

    def add_protocol(
        self,
        protocol: SupportedProtocol,
    ) -> None:
        self.supported_protocols.append(protocol)

    @property
    def chain_count(self) -> int:
        return len(self.supported_chains)

    @property
    def protocol_count(self) -> int:
        return len(self.supported_protocols)


# =============================================================================
# Agent Statistics
# =============================================================================


@dataclass(slots=True)
class AgentStatistics:

    started_at: datetime = field(default_factory=utc_now)
    last_activity: datetime = field(default_factory=utc_now)
    uptime_seconds: float = 0.0
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    tool_calls: int = 0
    rpc_calls: int = 0
    memory_reads: int = 0
    memory_writes: int = 0
    state_updates: int = 0
    events_published: int = 0
    average_latency_ms: float = 0.0
    peak_latency_ms: float = 0.0

    def update_uptime(self) -> None:
        self.uptime_seconds = (
            utc_now() - self.started_at
        ).total_seconds()

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0

        return (
            self.successful_executions
            / self.total_executions
        ) * 100.0


# =============================================================================
# Agent Health
# =============================================================================


@dataclass(slots=True)
class AgentHealth:

    status: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    checked_at: datetime = field(default_factory=utc_now)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    active_tasks: int = 0
    rpc_connected: bool = False
    memory_available: bool = False
    state_manager_available: bool = False
    event_bus_available: bool = False
    metadata: Metadata = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status is HealthStatus.HEALTHY


# =============================================================================
# Agent Execution Context
# =============================================================================


@dataclass(slots=True)
class AgentExecutionContext:

    execution_id: ExecutionID = field(
        default_factory=generate_execution_id
    )
    task_id: TaskID = field(
        default_factory=generate_task_id
    )
    started_at: datetime = field(
        default_factory=utc_now
    )
    user_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    parent_execution: ExecutionID | None = None
    metadata: Metadata = field(default_factory=dict)


# =============================================================================
# Agent Hooks
# =============================================================================


@dataclass(slots=True)
class AgentHooks:

    before_initialize: list[Any] = field(
        default_factory=list
    )
    after_initialize: list[Any] = field(
        default_factory=list
    )
    before_execute: list[Any] = field(
        default_factory=list
    )
    after_execute: list[Any] = field(
        default_factory=list
    )
    before_shutdown: list[Any] = field(
        default_factory=list
    )
    after_shutdown: list[Any] = field(
        default_factory=list
    )
    on_error: list[Any] = field(
        default_factory=list
    )
    on_health_change: list[Any] = field(
        default_factory=list
    )
    on_state_change: list[Any] = field(
        default_factory=list
    )


# =============================================================================
# Agent Snapshot
# =============================================================================


@dataclass(slots=True)
class AgentSnapshot:

    identity: AgentIdentity
    status: AgentStatus
    health: AgentHealth
    statistics: AgentStatistics
    created_at: datetime = field(
        default_factory=utc_now
    )
    metadata: Metadata = field(default_factory=dict)


# =============================================================================
# Base Agent
# =============================================================================


class BaseAgent:
    """
    Enterprise-grade base class for every CIE-OS agent.

    Concrete implementations override ``execute()`` and register
    domain-specific tools, services, and event handlers.

    Examples
    --------
        BlockchainAgent(BaseAgent)
        WalletAnalyzer(BaseAgent)
        SmartContractAnalyzer(BaseAgent)
        MEVDetector(BaseAgent)
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        runtime: AgentRuntime | None = None,
        context: AgentContext | None = None,
        lifecycle: AgentLifecycle | None = None,
    ) -> None:

        # ==========================================================
        # Core Configuration
        # ==========================================================

        self.config: AgentConfig = (
            config or AgentConfig()
        )

        self.identity: AgentIdentity = (
            self.config.identity
        )

        self.metadata: AgentMetadata = (
            self.config.metadata
        )

        # ==========================================================
        # Runtime Components
        # ==========================================================

        self.runtime: AgentRuntime = (
            runtime or AgentRuntime()
        )

        self.context: AgentContext = (
            context or AgentContext()
        )

        self.lifecycle: AgentLifecycle = (
            lifecycle or AgentLifecycle()
        )

        # ==========================================================
        # Runtime State
        # ==========================================================

        self.status: AgentStatus = (
            AgentStatus.CREATED
        )

        self.health = AgentHealth()

        self.statistics = AgentStatistics()

        self.execution: AgentExecutionContext | None = None

        self.snapshot: AgentSnapshot | None = None

        # ==========================================================
        # Hook Registry
        # ==========================================================

        self.hooks = AgentHooks()

        # ==========================================================
        # Startup Flags
        # ==========================================================

        self._initialized = False
        self._running = False
        self._paused = False
        self._shutdown = False
        self._failed = False

        # ==========================================================
        # Timing
        # ==========================================================

        self._created_at = utc_now()
        self._last_activity = utc_now()

        # ==========================================================
        # Runtime Identity
        # ==========================================================

        self._instance_id = str(uuid.uuid4())
        self._boot_id = str(uuid.uuid4())

        # ==========================================================
        # Internal Metadata
        # ==========================================================

        self._metadata: Metadata = {}
        self._tags: set[str] = set()
        self._labels: dict[str, str] = {}

        # ==========================================================
        # Internal Registries
        # ==========================================================

        self._tools: dict[str, Any] = {}
        self._services: dict[str, Any] = {}
        self._memories: dict[str, Any] = {}
        self._contracts: dict[str, Any] = {}
        self._state_managers: dict[str, Any] = {}
        self._plugins: dict[str, Any] = {}
        self._models: dict[str, Any] = {}
        self._chains: dict[str, SupportedChain] = {}
        self._protocols: dict[str, SupportedProtocol] = {}
        self._event_handlers: dict[str, list[Any]] = {}
        self._middleware: list[Any] = []
        self._resources: dict[str, Any] = {}
        self._extensions: dict[str, Any] = {}
        self._shared_objects: dict[str, Any] = {}

        # ==========================================================
        # Runtime Collections
        # ==========================================================

        self._tasks: set[asyncio.Task[Any]] = set()
        self._pending_jobs: list[Any] = []
        self._completed_jobs: list[Any] = []
        self._failed_jobs: list[Any] = []
        self._notifications: list[Any] = []
        self._warnings: list[str] = []
        self._errors: list[Exception] = []

        # ==========================================================
        # Async Infrastructure
        # ==========================================================

        self._agent_lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()
        self._memory_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._event_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._startup_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._resume_event = asyncio.Event()

        # ==========================================================
        # Internal Queues
        # ==========================================================

        self._event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._task_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._tool_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._rpc_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._audit_queue: asyncio.Queue[Any] = asyncio.Queue()

        # ==========================================================
        # Runtime Cache
        # ==========================================================

        self._cache: dict[str, Any] = {}
        self._temporary_storage: dict[str, Any] = {}
        self._execution_cache: dict[str, Any] = {}
        self._result_cache: dict[str, Any] = {}
        self._metrics_cache: dict[str, Any] = {}

        # ==========================================================
        # Background Workers
        # ==========================================================

        self._background_workers: dict[str, asyncio.Task[Any]] = {}
        self._worker_states: dict[str, bool] = {}
        self._worker_metadata: dict[str, Metadata] = {}

        # ==========================================================
        # Dependency Injection Container
        # ==========================================================

        self._container: dict[str, Any] = {}
        self._singletons: dict[str, Any] = {}
        self._factories: dict[str, Any] = {}
        self._providers: dict[str, Any] = {}

        # ==========================================================
        # Runtime Diagnostics
        # ==========================================================

        self._diagnostics: dict[str, Any] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._startup_duration_ms: float = 0.0
        self._last_exception: Exception | None = None
        self._last_health_check = utc_now()
        self._last_snapshot = utc_now()

        # ==========================================================
        # Validation
        # ==========================================================

        self._validate_configuration()

    # =================================================================
    # Async Context Manager
    # =================================================================

    async def __aenter__(self) -> "BaseAgent":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.shutdown()

    # =================================================================
    # Internal Validation
    # =================================================================

    def _validate_configuration(self) -> None:

        if not self.config.enabled:
            raise RuntimeError(
                "Agent is disabled."
            )

        validate_agent_name(
            self.identity.name,
        )

        validate_version(
            self.identity.version,
        )

    # =================================================================
    # Agent Lifecycle
    # =================================================================

    async def initialize(self) -> None:
        """
        Initialize the complete agent.

        Initialization order:
            1. Validate configuration
            2. Runtime
            3. Context
            4. Services
            5. Memories
            6. Contracts
            7. State Managers
            8. Event System
            9. Hooks
        """

        async with self._agent_lock:

            if self._initialized:
                return

            boot_start = monotonic_ms()

            self.status = AgentStatus.INITIALIZING

            await self.lifecycle.initialize()

            self.statistics.last_activity = utc_now()

            await self._initialize_runtime()

            await self._initialize_services()

            await self._initialize_memories()

            await self._initialize_contracts()

            await self._initialize_state_managers()

            await self._initialize_event_handlers()

            await self._run_initialize_hooks()

            await self.lifecycle.ready()

            self.status = AgentStatus.READY

            self.health.status = HealthStatus.HEALTHY

            self._initialized = True

            self._startup_duration_ms = (
                monotonic_ms() - boot_start
            )

            self._diagnostics["boot_completed"] = True

            self._startup_event.set()

    async def start(self) -> None:

        if not self._initialized:
            await self.initialize()

        if self._running:
            return

        await self.runtime.start()

        await self.lifecycle.start()

        self.status = AgentStatus.RUNNING

        self._running = True

        self.statistics.last_activity = utc_now()

        self._audit("agent_started")

    async def pause(self) -> None:

        if not self._running or self._paused:
            return

        await self.lifecycle.pause()

        self._paused = True

        self.status = AgentStatus.PAUSED

        self._pause_event.set()

        self._audit("agent_paused")

    async def resume(self) -> None:

        if not self._paused:
            return

        await self.lifecycle.resume()

        self._paused = False

        self.status = AgentStatus.RUNNING

        self._resume_event.set()

        self._audit("agent_resumed")

    async def stop(self) -> None:

        if not self._running:
            return

        self.status = AgentStatus.STOPPING

        await self._stop_workers()

        await self.runtime.stop()

        await self.lifecycle.stop()

        self._running = False

        self._paused = False

        self.status = AgentStatus.STOPPED

        self._audit("agent_stopped")

    async def shutdown(self) -> None:

        if self._shutdown:
            return

        await self.stop()

        await self._run_shutdown_hooks()

        await self.cleanup()

        await self.runtime.shutdown()

        await self.lifecycle.shutdown()

        self.status = AgentStatus.SHUTDOWN

        self._shutdown = True

        self._shutdown_event.set()

        self._audit("agent_shutdown")

    # =================================================================
    # Internal Bootstrap
    # =================================================================

    async def _initialize_runtime(self) -> None:
        await self.runtime.initialize()

    async def _initialize_services(self) -> None:
        for service in self._services.values():
            initialize = getattr(
                service, "initialize", None,
            )
            if initialize is None:
                continue
            result = initialize()
            if asyncio.iscoroutine(result):
                await result

    async def _initialize_memories(self) -> None:
        for memory in self._memories.values():
            initialize = getattr(
                memory, "initialize", None,
            )
            if initialize:
                result = initialize()
                if asyncio.iscoroutine(result):
                    await result

    async def _initialize_contracts(self) -> None:
        for contract in self._contracts.values():
            initialize = getattr(
                contract, "initialize", None,
            )
            if initialize:
                result = initialize()
                if asyncio.iscoroutine(result):
                    await result

    async def _initialize_state_managers(self) -> None:
        for manager in self._state_managers.values():
            initialize = getattr(
                manager, "initialize", None,
            )
            if initialize:
                result = initialize()
                if asyncio.iscoroutine(result):
                    await result

    async def _initialize_event_handlers(self) -> None:
        for name, handlers in self._event_handlers.items():
            for handler in handlers:
                initialize = getattr(
                    handler, "initialize", None,
                )
                if initialize:
                    result = initialize()
                    if asyncio.iscoroutine(result):
                        await result

    # =================================================================
    # Hook Execution
    # =================================================================

    async def _run_initialize_hooks(self) -> None:
        for hook in self.hooks.after_initialize:
            result = hook(self)
            if asyncio.iscoroutine(result):
                await result

    async def _run_shutdown_hooks(self) -> None:
        for hook in self.hooks.before_shutdown:
            result = hook(self)
            if asyncio.iscoroutine(result):
                await result

    async def _run_before_execute_hooks(self) -> None:
        for hook in self.hooks.before_execute:
            result = hook(self)
            if asyncio.iscoroutine(result):
                await result

    async def _run_after_execute_hooks(
        self,
        result: Any,
    ) -> None:
        for hook in self.hooks.after_execute:
            response = hook(self, result)
            if asyncio.iscoroutine(response):
                await response

    # =================================================================
    # Execution Engine
    # =================================================================

    async def run(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Main public execution entrypoint.

        Pipeline: Request -> Validation -> Context ->
        before_execute -> middleware -> execute() ->
        after_execute -> Metrics -> Response
        """

        if not self._running:
            await self.start()

        return await self.invoke(task, **kwargs)

    async def invoke(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:

        self.execution = AgentExecutionContext()

        self.statistics.total_executions += 1
        self.statistics.last_activity = utc_now()

        started = monotonic_ms()

        try:
            await self._run_before_execute_hooks()

            result = await self._run_middleware(
                task, **kwargs,
            )

            await self._run_after_execute_hooks(result)

            self.statistics.successful_executions += 1

            return result

        except Exception as exc:

            self.statistics.failed_executions += 1
            self._last_exception = exc
            self._errors.append(exc)

            await self._handle_execution_error(exc)

            raise

        finally:
            elapsed = monotonic_ms() - started
            self._update_latency(elapsed)

    async def _run_middleware(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute the middleware pipeline, with ``execute()``
        as the terminal handler.
        """

        if not self._middleware:
            return await self.execute(task, **kwargs)

        index = 0

        async def next_handler(t: Any, **kw: Any) -> Any:
            nonlocal index
            if index < len(self._middleware):
                mw = self._middleware[index]
                index += 1
                return await mw(t, next_handler, **kw)
            return await self.execute(t, **kw)

        return await next_handler(task, **kwargs)

    async def execute(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Main execution method. Child classes MUST override this.
        """
        raise NotImplementedError(
            "BaseAgent.execute() must be implemented."
        )

    # =================================================================
    # Metrics
    # =================================================================

    def _update_latency(
        self,
        latency_ms: float,
    ) -> None:

        stats = self.statistics
        total = stats.total_executions

        if latency_ms > stats.peak_latency_ms:
            stats.peak_latency_ms = latency_ms

        stats.average_latency_ms = (
            (
                stats.average_latency_ms
                * max(total - 1, 0)
            )
            + latency_ms
        ) / max(total, 1)

        stats.update_uptime()

    # =================================================================
    # Error Handling
    # =================================================================

    async def _handle_execution_error(
        self,
        exc: Exception,
    ) -> None:

        self.health.status = HealthStatus.DEGRADED

        self._audit_log.append(
            {
                "timestamp": utc_now(),
                "severity": AuditSeverity.ERROR.value,
                "event": "execution_failed",
                "exception": type(exc).__name__,
                "message": str(exc),
            }
        )

        for hook in self.hooks.on_error:
            result = hook(self, exc)
            if asyncio.iscoroutine(result):
                await result

    # =================================================================
    # Registry Management
    # =================================================================

    def register_tool(
        self,
        name: str,
        tool: Any,
    ) -> None:
        if name in self._tools:
            raise ValueError(
                f"Tool '{name}' already registered."
            )
        self._tools[name] = tool
        self._audit("tool_registered", name=name)

    def register_service(
        self,
        name: str,
        service: Any,
    ) -> None:
        if name in self._services:
            raise ValueError(
                f"Service '{name}' already exists."
            )
        self._services[name] = service
        self._audit("service_registered", name=name)

    def register_memory(
        self,
        name: str,
        memory: Any,
    ) -> None:
        self._memories[name] = memory
        self._audit("memory_registered", name=name)

    def register_contract(
        self,
        name: str,
        contract: Any,
    ) -> None:
        self._contracts[name] = contract
        self._audit("contract_registered", name=name)

    def register_state_manager(
        self,
        name: str,
        manager: Any,
    ) -> None:
        self._state_managers[name] = manager
        self._audit(
            "state_manager_registered", name=name,
        )

    def register_plugin(
        self,
        name: str,
        plugin: Any,
    ) -> None:
        self._plugins[name] = plugin
        self._audit("plugin_registered", name=name)

    def register_chain(
        self,
        chain: SupportedChain,
    ) -> None:
        self._chains[chain.name.lower()] = chain

    def register_protocol(
        self,
        protocol: SupportedProtocol,
    ) -> None:
        self._protocols[protocol.name.lower()] = protocol

    # =================================================================
    # Registry Lookup
    # =================================================================

    def get_tool(self, name: str) -> Any:
        return self._tools.get(name)

    def get_service(self, name: str) -> Any:
        return self._services.get(name)

    def get_memory(self, name: str) -> Any:
        return self._memories.get(name)

    def get_contract(self, name: str) -> Any:
        return self._contracts.get(name)

    def get_plugin(self, name: str) -> Any:
        return self._plugins.get(name)

    def get_chain(
        self,
        name: str,
    ) -> SupportedChain | None:
        return self._chains.get(name.lower())

    def get_protocol(
        self,
        name: str,
    ) -> SupportedProtocol | None:
        return self._protocols.get(name.lower())

    # =================================================================
    # Registry Removal
    # =================================================================

    def unregister_tool(self, name: str) -> None:
        self._tools.pop(name, None)

    def unregister_service(self, name: str) -> None:
        self._services.pop(name, None)

    def unregister_plugin(self, name: str) -> None:
        self._plugins.pop(name, None)

    # =================================================================
    # Registry Inspection
    # =================================================================

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(self._tools.keys())

    @property
    def services(self) -> tuple[str, ...]:
        return tuple(self._services.keys())

    @property
    def plugins(self) -> tuple[str, ...]:
        return tuple(self._plugins.keys())

    @property
    def memories(self) -> tuple[str, ...]:
        return tuple(self._memories.keys())

    @property
    def contracts(self) -> tuple[str, ...]:
        return tuple(self._contracts.keys())

    # =================================================================
    # Middleware
    # =================================================================

    def use_middleware(self, middleware: Any) -> None:
        self._middleware.append(middleware)

    def remove_middleware(self, middleware: Any) -> None:
        if middleware in self._middleware:
            self._middleware.remove(middleware)

    def clear_middleware(self) -> None:
        self._middleware.clear()

    # =================================================================
    # Extension Management
    # =================================================================

    def register_extension(
        self,
        name: str,
        extension: Any,
    ) -> None:
        self._extensions[name] = extension
        self._audit(
            "extension_registered", name=name,
        )

    def get_extension(self, name: str) -> Any:
        return self._extensions.get(name)

    def unregister_extension(self, name: str) -> None:
        self._extensions.pop(name, None)

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(self._extensions.keys())

    # =================================================================
    # Shared Objects
    # =================================================================

    def share(self, key: str, obj: Any) -> None:
        self._shared_objects[key] = obj

    def shared(self, key: str) -> Any:
        return self._shared_objects.get(key)

    def unshare(self, key: str) -> None:
        self._shared_objects.pop(key, None)

    # =================================================================
    # Dependency Resolution
    # =================================================================

    def has_dependency(self, name: str) -> bool:
        return (
            name in self._services
            or name in self._tools
            or name in self._plugins
            or name in self._memories
            or name in self._contracts
        )

    def resolve(self, name: str) -> Any:
        registries = (
            self._services,
            self._tools,
            self._plugins,
            self._memories,
            self._contracts,
            self._state_managers,
        )

        for registry in registries:
            if name in registry:
                return registry[name]

        raise KeyError(
            f"Dependency '{name}' not found."
        )

    def require(self, name: str) -> Any:
        dependency = self.resolve(name)

        if dependency is None:
            raise RuntimeError(
                f"Required dependency '{name}' missing."
            )

        return dependency

    # =================================================================
    # DI Container
    # =================================================================

    def register_singleton(
        self,
        name: str,
        instance: Any,
    ) -> None:
        self._singletons[name] = instance
        self._container[name] = instance

    def register_factory(
        self,
        name: str,
        factory: Any,
    ) -> None:
        self._factories[name] = factory

    def register_provider(
        self,
        name: str,
        provider: Any,
    ) -> None:
        self._providers[name] = provider

    def inject(self, name: str) -> Any:
        if name in self._singletons:
            return self._singletons[name]

        if name in self._factories:
            instance = self._factories[name]()
            return instance

        if name in self._providers:
            return self._providers[name]

        return self.resolve(name)

    # =================================================================
    # Resource Management
    # =================================================================

    def register_resource(
        self,
        name: str,
        resource: Any,
    ) -> None:
        self._resources[name] = resource

    def get_resource(self, name: str) -> Any:
        return self._resources.get(name)

    async def release_resource(
        self,
        name: str,
    ) -> None:
        resource = self._resources.pop(name, None)

        if resource is None:
            return

        close = getattr(resource, "close", None)

        if callable(close):
            result = close()
            if asyncio.iscoroutine(result):
                await result

    # =================================================================
    # Background Task Management
    # =================================================================

    def create_background_task(
        self,
        coro: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:

        task = asyncio.create_task(
            coro,
            name=name,
        )

        self._tasks.add(task)

        task.add_done_callback(
            self._tasks.discard,
        )

        return task

    async def cancel_background_tasks(self) -> None:

        for task in list(self._tasks):
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(
                *self._tasks,
                return_exceptions=True,
            )

    # =================================================================
    # Named Worker Management
    # =================================================================

    def start_worker(
        self,
        name: str,
        coro: Any,
        *,
        metadata: Metadata | None = None,
    ) -> asyncio.Task[Any]:
        if name in self._background_workers:
            existing = self._background_workers[name]
            if not existing.done():
                raise ValueError(
                    f"Worker '{name}' already running."
                )

        task = asyncio.create_task(coro, name=name)
        self._background_workers[name] = task
        self._worker_states[name] = True
        self._worker_metadata[name] = metadata or {}

        def _on_done(t: asyncio.Task[Any]) -> None:
            self._worker_states[name] = False

        task.add_done_callback(_on_done)

        self._audit("worker_started", name=name)
        return task

    async def stop_worker(self, name: str) -> None:
        task = self._background_workers.get(name)

        if task is None or task.done():
            return

        task.cancel()

        with suppress(asyncio.CancelledError):
            await task

        self._worker_states[name] = False
        self._audit("worker_stopped", name=name)

    async def _stop_workers(self) -> None:
        for name in list(self._background_workers):
            await self.stop_worker(name)

    def is_worker_running(self, name: str) -> bool:
        return self._worker_states.get(name, False)

    @property
    def active_workers(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, running in self._worker_states.items()
            if running
        )

    # =================================================================
    # Cache Management
    # =================================================================

    def cache_get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self._cache.get(key, default)

    def cache_set(
        self,
        key: str,
        value: Any,
    ) -> None:
        self._cache[key] = value

    def cache_delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def cache_has(self, key: str) -> bool:
        return key in self._cache

    def cache_clear(self) -> None:
        self._cache.clear()

    def result_cache_get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self._result_cache.get(key, default)

    def result_cache_set(
        self,
        key: str,
        value: Any,
    ) -> None:
        self._result_cache[key] = value

    # =================================================================
    # Event System
    # =================================================================

    def subscribe(
        self,
        event: str,
        callback: Any,
    ) -> None:
        self._event_handlers.setdefault(
            event, [],
        ).append(callback)

    def unsubscribe(
        self,
        event: str,
        callback: Any,
    ) -> None:
        handlers = self._event_handlers.get(event, [])
        if callback in handlers:
            handlers.remove(callback)

    async def publish_event(
        self,
        event: str,
        payload: Any = None,
    ) -> None:
        handlers = self._event_handlers.get(event, [])

        for handler in handlers:
            result = handler(payload)
            if asyncio.iscoroutine(result):
                await result

        self.statistics.events_published += 1

    # =================================================================
    # Notification / Warning / Error Tracking
    # =================================================================

    def add_notification(
        self,
        notification: Any,
    ) -> None:
        self._notifications.append(notification)

    def add_warning(self, message: str) -> None:
        self._warnings.append(message)
        logger.warning(
            "[%s] %s", self.identity.name, message,
        )

    def get_warnings(self) -> list[str]:
        return list(self._warnings)

    def get_errors(self) -> list[Exception]:
        return list(self._errors)

    def clear_warnings(self) -> None:
        self._warnings.clear()

    def clear_errors(self) -> None:
        self._errors.clear()

    # =================================================================
    # Health & Diagnostics
    # =================================================================

    def health_check(self) -> AgentHealth:

        self.health.checked_at = utc_now()
        self.health.active_tasks = len(self._tasks)

        self._last_health_check = utc_now()

        return self.health

    def diagnostics(self) -> dict[str, Any]:

        return {
            "status": self.status.value,
            "running": self._running,
            "paused": self._paused,
            "initialized": self._initialized,
            "shutdown": self._shutdown,
            "background_tasks": len(self._tasks),
            "active_workers": len(self.active_workers),
            "services": len(self._services),
            "tools": len(self._tools),
            "plugins": len(self._plugins),
            "extensions": len(self._extensions),
            "chains": len(self._chains),
            "protocols": len(self._protocols),
            "middleware": len(self._middleware),
            "pending_jobs": len(self._pending_jobs),
            "completed_jobs": len(self._completed_jobs),
            "failed_jobs": len(self._failed_jobs),
            "warnings": len(self._warnings),
            "errors": len(self._errors),
            "cache_keys": len(self._cache),
            "startup_duration_ms": self._startup_duration_ms,
            "statistics": {
                "total_executions": self.statistics.total_executions,
                "successful": self.statistics.successful_executions,
                "failed": self.statistics.failed_executions,
                "success_rate": self.statistics.success_rate,
                "avg_latency_ms": self.statistics.average_latency_ms,
                "peak_latency_ms": self.statistics.peak_latency_ms,
            },
        }

    def snapshot_state(self) -> AgentSnapshot:

        self.snapshot = AgentSnapshot(
            identity=self.identity,
            status=self.status,
            health=self.health,
            statistics=self.statistics,
        )

        self._last_snapshot = utc_now()

        return self.snapshot

    # =================================================================
    # Serialization
    # =================================================================

    def to_dict(self) -> dict[str, Any]:

        return {
            "identity": {
                "agent_id": str(self.identity.agent_id),
                "name": self.identity.name,
                "version": self.identity.version,
                "vendor": self.identity.vendor,
                "instance_id": self.identity.instance_id,
            },
            "status": self.status.value,
            "health": {
                "status": self.health.status.value,
                "message": self.health.message,
                "is_healthy": self.health.is_healthy,
            },
            "config": {
                "priority": self.config.priority.value,
                "execution_mode": self.config.execution_mode.value,
                "restart_policy": self.config.restart_policy.value,
                "timeout_seconds": self.config.timeout_seconds,
                "max_concurrent_tasks": self.config.max_concurrent_tasks,
                "capabilities": sorted(
                    c.value for c in self.config.capabilities
                ),
            },
            "registries": {
                "tools": list(self._tools.keys()),
                "services": list(self._services.keys()),
                "plugins": list(self._plugins.keys()),
                "chains": list(self._chains.keys()),
                "protocols": list(self._protocols.keys()),
                "extensions": list(self._extensions.keys()),
            },
            "statistics": {
                "total_executions": self.statistics.total_executions,
                "successful": self.statistics.successful_executions,
                "failed": self.statistics.failed_executions,
                "success_rate": self.statistics.success_rate,
                "uptime_seconds": self.statistics.uptime_seconds,
            },
            "runtime": {
                "running": self._running,
                "paused": self._paused,
                "initialized": self._initialized,
                "startup_duration_ms": self._startup_duration_ms,
                "created_at": self._created_at.isoformat(),
            },
        }

    # =================================================================
    # Internal Audit Helper
    # =================================================================

    def _audit(
        self,
        event: str,
        **data: Any,
    ) -> None:
        self._audit_log.append(
            {
                "timestamp": utc_now(),
                "event": event,
                "data": data,
            }
        )

    # =================================================================
    # Cleanup
    # =================================================================

    async def cleanup(self) -> None:

        await self.cancel_background_tasks()

        await self._stop_workers()

        for name in list(self._resources):
            await self.release_resource(name)

        self._cache.clear()
        self._execution_cache.clear()
        self._temporary_storage.clear()
        self._result_cache.clear()
        self._metrics_cache.clear()

        self._audit("cleanup_completed")

    # =================================================================
    # String Representation
    # =================================================================

    def __repr__(self) -> str:

        return (
            f"{self.__class__.__name__}("
            f"name={self.identity.name!r}, "
            f"status={self.status.value!r})"
        )


# =============================================================================
# Public Exports
# =============================================================================

__all__ = [

    # Agent
    "BaseAgent",

    # Configuration
    "AgentConfig",
    "AgentIdentity",
    "AgentMetadata",

    # Runtime
    "AgentStatistics",
    "AgentHealth",
    "AgentExecutionContext",
    "AgentHooks",
    "AgentSnapshot",

    # Enums
    "AgentCapability",
    "AgentPriority",
    "AgentStatus",
    "ExecutionMode",
    "HealthStatus",
    "RestartPolicy",
    "AuditSeverity",

    # Data models
    "SupportedChain",
    "SupportedProtocol",

    # Helpers
    "generate_agent_id",
    "generate_execution_id",
    "generate_task_id",
    "utc_now",
    "monotonic_ms",
    "validate_agent_name",
    "validate_version",
    "ensure_directory",
    "safe_metadata",
    "is_async_callable",
]
