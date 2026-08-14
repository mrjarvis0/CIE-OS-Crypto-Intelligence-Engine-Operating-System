"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.agent

Description
-----------
Enterprise-grade BaseAgent foundation for the CIE-OS platform.

This module provides:

- Shared constants
- Common type aliases
- Validation helpers
- Runtime helper utilities

The actual BaseAgent implementation is added in later parts.
"""

from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================

import asyncio
import re
import time
import uuid

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
    """
    Return current UTC timestamp.
    """
    return datetime.now(UTC)


def monotonic_ms() -> int:
    """
    High precision monotonic clock.

    Useful for latency measurements.
    """
    return int(time.perf_counter() * 1000)


def generate_agent_id() -> AgentID:
    """
    Generate globally unique Agent ID.
    """
    return AgentID(str(uuid.uuid4()))


def generate_execution_id() -> ExecutionID:
    """
    Generate execution identifier.
    """
    return ExecutionID(str(uuid.uuid4()))


def generate_task_id() -> TaskID:
    """
    Generate task identifier.
    """
    return TaskID(str(uuid.uuid4()))


def validate_agent_name(name: str) -> str:
    """
    Validate agent name.

    Rules
    -----
    - 3–64 characters
    - Letters
    - Numbers
    - Space
    - _
    - -
    - .
    """

    name = name.strip()

    if not AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"Invalid agent name: {name}"
        )

    return name


def validate_version(version: str) -> str:
    """
    Validate semantic version.
    """

    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(
            f"Invalid version: {version}"
        )

    return version


def ensure_directory(path: Path) -> Path:
    """
    Ensure directory exists.
    """

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def safe_metadata(
    metadata: Metadata | None,
) -> Metadata:
    """
    Return non-null metadata dictionary.
    """

    return metadata or {}


def is_async_callable(
    obj: Any,
) -> bool:
    """
    Determine whether object is awaitable.
    """

    return (
        asyncio.iscoroutinefunction(obj)
        or asyncio.iscoroutine(obj)
    )
# =============================================================================
# Agent Capabilities
# =============================================================================


class AgentCapability(StrEnum):
    """
    Defines every capability that an Agent may expose.

    These capabilities are intentionally generic so they can be
    reused across all CIE-OS intelligence modules.
    """

    # ---------------------------------------------------------
    # Blockchain Intelligence
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Intelligence
    # ---------------------------------------------------------

    MARKET_INTELLIGENCE = "market_intelligence"

    SOCIAL_INTELLIGENCE = "social_intelligence"

    NEWS_INTELLIGENCE = "news_intelligence"

    ONCHAIN_INTELLIGENCE = "onchain_intelligence"

    SENTIMENT_ANALYSIS = "sentiment_analysis"

    ENTITY_RESOLUTION = "entity_resolution"

    KNOWLEDGE_GRAPH = "knowledge_graph"

    # ---------------------------------------------------------
    # AI
    # ---------------------------------------------------------

    TOOL_EXECUTION = "tool_execution"

    MEMORY = "memory"

    REASONING = "reasoning"

    PLANNING = "planning"

    AUTONOMOUS_EXECUTION = "autonomous_execution"

    MULTI_AGENT = "multi_agent"

    HUMAN_APPROVAL = "human_approval"

    # ---------------------------------------------------------
    # Infrastructure
    # ---------------------------------------------------------

    EVENT_PROCESSING = "event_processing"

    STATE_SYNCHRONIZATION = "state_synchronization"

    AUDIT_LOGGING = "audit_logging"

    OBSERVABILITY = "observability"

    HEALTH_MONITORING = "health_monitoring"


# =============================================================================
# Agent Status
# =============================================================================


class AgentStatus(StrEnum):
    """
    High-level runtime state.
    """

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
    """
    Scheduling priority.

    Higher values receive execution preference.
    """

    BACKGROUND = 0

    LOW = 25

    NORMAL = 50

    HIGH = 75

    CRITICAL = 100


# =============================================================================
# Execution Mode
# =============================================================================


class ExecutionMode(StrEnum):
    """
    Determines how the agent executes work.
    """

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
    """
    Agent health classification.
    """

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
    """
    Automatic restart behavior.
    """

    NEVER = "never"

    ON_FAILURE = "on_failure"

    ALWAYS = "always"

    EXPONENTIAL_BACKOFF = "exponential_backoff"


# =============================================================================
# Audit Severity
# =============================================================================


class AuditSeverity(StrEnum):
    """
    Severity level for audit events.
    """

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
    """
    Describes a blockchain network supported by an agent.
    """

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
    """
    Protocol supported by the agent.

    Examples:
        - Uniswap
        - Aave
        - Curve
        - LayerZero
    """

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
    """
    Descriptive information about the agent.
    """

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
    """
    Immutable identity of an agent instance.
    """

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
    """
    Primary configuration object used by BaseAgent.
    """

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

    heartbeat_seconds: int = (
        DEFAULT_HEARTBEAT_SECONDS
    )

    retry_limit: int = DEFAULT_RETRY_LIMIT

    max_concurrent_tasks: int = (
        DEFAULT_MAX_CONCURRENT_TASKS
    )

    capabilities: set[AgentCapability] = field(
        default_factory=set
    )

    supported_chains: list[SupportedChain] = field(
        default_factory=list
    )

    supported_protocols: list[
        SupportedProtocol
    ] = field(default_factory=list)

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
    """
    Runtime statistics collected throughout the lifetime
    of an agent instance.
    """

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
    """
    Current operational health.
    """

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
    """
    Information describing the current execution.
    """

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
    """
    Lifecycle callback registry.
    """

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
    """
    Immutable snapshot of the current runtime state.
    """

    identity: AgentIdentity

    status: AgentStatus

    health: AgentHealth

    statistics: AgentStatistics

    created_at: datetime = field(
        default_factory=utc_now
    )

    metadata: Metadata = field(default_factory=dict)


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

    # Helpers
    "generate_agent_id",
    "generate_execution_id",
    "generate_task_id",
    "utc_now",
]# =============================================================================
# Base Agent
# =============================================================================


class BaseAgent:
    """
    Enterprise-grade base class for every CIE-OS agent.

    This class provides the common infrastructure required by all
    intelligence agents while remaining completely domain-agnostic.

    Concrete implementations should inherit from this class instead
    of implementing their own runtime infrastructure.

    Examples
    --------
        BlockchainAgent(BaseAgent)
        WalletAnalyzer(BaseAgent)
        SmartContractAnalyzer(BaseAgent)
        MEVDetector(BaseAgent)
        ForexAgent(BaseAgent)
        StockAgent(BaseAgent)
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        runtime: AgentRuntime | None = None,
        context: AgentContext | None = None,
        lifecycle: AgentLifecycle | None = None,
    ) -> None:
        """
        Create a new BaseAgent instance.

        Parameters
        ----------
        config
            Agent configuration.

        runtime
            Existing runtime instance.

        context
            Existing shared context.

        lifecycle
            Existing lifecycle manager.
        """

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
        # Validation
        # ==========================================================

        self._validate_configuration()

    # ------------------------------------------------------------------
    # Internal Validation
    # ------------------------------------------------------------------

    def _validate_configuration(self) -> None:
        """
        Validate configuration before runtime startup.

        Additional enterprise validation will be added
        in later parts.
        """

        if not self.config.enabled:
            raise RuntimeError(
                "Agent is disabled."
            )

        validate_agent_name(
            self.identity.name,
        )

        validate_version(
            self.identity.version,
        )# ==========================================================
# Internal Registries
# ==========================================================

        #
        # Every subsystem is registered here.
        # Future modules can simply register themselves
        # without modifying BaseAgent.
        #

        self._tools: dict[str, Any] = {}

        self._services: dict[str, Any] = {}

        self._memories: dict[str, Any] = {}

        self._contracts: dict[str, Any] = {}

        self._state_managers: dict[str, Any] = {}

        self._plugins: dict[str, Any] = {}

        self._models: dict[str, Any] = {}

        self._chains: dict[str, SupportedChain] = {}

        self._protocols: dict[str, SupportedProtocol] = {}

        self._event_handlers: dict[
            str,
            list[Any],
        ] = {}

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

        self._event_queue: asyncio.Queue[Any] = (
            asyncio.Queue()
        )

        self._task_queue: asyncio.Queue[Any] = (
            asyncio.Queue()
        )

        self._tool_queue: asyncio.Queue[Any] = (
            asyncio.Queue()
        )

        self._rpc_queue: asyncio.Queue[Any] = (
            asyncio.Queue()
        )

        self._audit_queue: asyncio.Queue[Any] = (
            asyncio.Queue()
        )

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

        self._background_workers: dict[
            str,
            asyncio.Task[Any],
        ] = {}

        self._worker_states: dict[str, bool] = {}

        self._worker_metadata: dict[
            str,
            Metadata,
        ] = {}

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
        # =============================================================================
# Agent Lifecycle
# =============================================================================

    async def initialize(self) -> None:
        """
        Initialize the complete agent.

        Initialization order is important:

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

            self.status = AgentStatus.INITIALIZING

            self.statistics.last_activity = utc_now()

            await self._initialize_runtime()

            await self._initialize_services()

            await self._initialize_memories()

            await self._initialize_contracts()

            await self._initialize_state_managers()

            await self._initialize_event_handlers()

            await self._run_initialize_hooks()

            self.status = AgentStatus.READY

            self.health.status = HealthStatus.HEALTHY

            self._initialized = True

            self._diagnostics["boot_completed"] = True


# =============================================================================
# Runtime Startup
# =============================================================================

    async def start(self) -> None:
        """
        Start the agent runtime.
        """

        if not self._initialized:

            await self.initialize()

        if self._running:
            return

        await self.runtime.start()

        self.status = AgentStatus.RUNNING

        self._running = True

        self.statistics.last_activity = utc_now()


# =============================================================================
# Pause / Resume
# =============================================================================

    async def pause(self) -> None:
        """
        Pause execution.
        """

        if not self._running:
            return

        self._paused = True

        self.status = AgentStatus.PAUSED

        self._pause_event.set()


    async def resume(self) -> None:
        """
        Resume execution.
        """

        if not self._paused:
            return

        self._paused = False

        self.status = AgentStatus.RUNNING

        self._resume_event.set()


# =============================================================================
# Stop
# =============================================================================

    async def stop(self) -> None:
        """
        Stop agent execution.
        """

        if not self._running:
            return

        self.status = AgentStatus.STOPPING

        await self.runtime.stop()

        self._running = False

        self.status = AgentStatus.STOPPED


# =============================================================================
# Shutdown
# =============================================================================

    async def shutdown(self) -> None:
        """
        Gracefully shutdown the agent.
        """

        if self._shutdown:
            return

        await self.stop()

        await self._run_shutdown_hooks()

        await self.runtime.shutdown()

        self.status = AgentStatus.SHUTDOWN

        self._shutdown = True


# =============================================================================
# Internal Bootstrap
# =============================================================================

    async def _initialize_runtime(self) -> None:
        """
        Runtime initialization.
        """

        await self.runtime.initialize()


    async def _initialize_services(self) -> None:
        """
        Initialize registered services.
        """

        for service in self._services.values():

            initialize = getattr(
                service,
                "initialize",
                None,
            )

            if initialize is None:
                continue

            result = initialize()

            if asyncio.iscoroutine(result):
                await result


    async def _initialize_memories(self) -> None:
        """
        Initialize memory providers.
        """

        for memory in self._memories.values():

            initialize = getattr(
                memory,
                "initialize",
                None,
            )

            if initialize:

                result = initialize()

                if asyncio.iscoroutine(result):
                    await result


    async def _initialize_contracts(self) -> None:
        """
        Initialize contract wrappers.
        """

        for contract in self._contracts.values():

            initialize = getattr(
                contract,
                "initialize",
                None,
            )

            if initialize:

                result = initialize()

                if asyncio.iscoroutine(result):
                    await result


    async def _initialize_state_managers(self) -> None:
        """
        Initialize state managers.
        """

        for manager in self._state_managers.values():

            initialize = getattr(
                manager,
                "initialize",
                None,
            )

            if initialize:

                result = initialize()

                if asyncio.iscoroutine(result):
                    await result


    async def _initialize_event_handlers(self) -> None:
        """
        Placeholder.

        EventBus integration arrives later.
        """

        return


# =============================================================================
# Hook Execution
# =============================================================================

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
                # =============================================================================
# Execution Engine
# =============================================================================

    async def run(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Main public execution entrypoint.

        Every request entering the agent passes through this method.

        Pipeline

            Request
                │
                ▼
            Validation
                │
                ▼
            Execution Context
                │
                ▼
            before_execute hooks
                │
                ▼
            execute()
                │
                ▼
            after_execute hooks
                │
                ▼
            Metrics
                │
                ▼
            Response
        """

        if not self._running:
            await self.start()

        return await self.invoke(
            task,
            **kwargs,
        )


# =============================================================================
# Invoke
# =============================================================================

    async def invoke(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Creates an execution context
        before delegating work.
        """

        self.execution = AgentExecutionContext()

        self.statistics.total_executions += 1

        self.statistics.last_activity = utc_now()

        started = monotonic_ms()

        try:

            await self._run_before_execute_hooks()

            result = await self.execute(
                task,
                **kwargs,
            )

            await self._run_after_execute_hooks(
                result,
            )

            self.statistics.successful_executions += 1

            return result

        except Exception as exc:

            self.statistics.failed_executions += 1

            self._last_exception = exc

            await self._handle_execution_error(
                exc,
            )

            raise

        finally:

            elapsed = monotonic_ms() - started

            self._update_latency(
                elapsed,
            )


# =============================================================================
# Execute
# =============================================================================

    async def execute(
        self,
        task: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Main execution method.

        Child classes MUST override this.

        Examples

            WalletAnalyzer.execute()

            TokenAnalyzer.execute()

            SmartContractAnalyzer.execute()

            MEVDetector.execute()
        """

        raise NotImplementedError(
            "BaseAgent.execute() "
            "must be implemented."
        )


# =============================================================================
# Hook Execution
# =============================================================================

    async def _run_before_execute_hooks(
        self,
    ) -> None:

        for hook in self.hooks.before_execute:

            result = hook(self)

            if asyncio.iscoroutine(result):
                await result


    async def _run_after_execute_hooks(
        self,
        result: Any,
    ) -> None:

        for hook in self.hooks.after_execute:

            response = hook(
                self,
                result,
            )

            if asyncio.iscoroutine(response):
                await response


# =============================================================================
# Metrics
# =============================================================================

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


# =============================================================================
# Error Handling
# =============================================================================

    async def _handle_execution_error(
        self,
        exc: Exception,
    ) -> None:
        """
        Default execution error handler.
        """

        self.health.status = (
            HealthStatus.DEGRADED
        )

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

            result = hook(
                self,
                exc,
            )

            if asyncio.iscoroutine(result):
                await result
                # =============================================================================
# Registry Management
# =============================================================================

    def register_tool(
        self,
        name: str,
        tool: Any,
    ) -> None:
        """
        Register a tool implementation.
        """

        if name in self._tools:
            raise ValueError(
                f"Tool '{name}' already registered."
            )

        self._tools[name] = tool

        self._audit(
            "tool_registered",
            name=name,
        )


    def register_service(
        self,
        name: str,
        service: Any,
    ) -> None:
        """
        Register a shared service.
        """

        if name in self._services:
            raise ValueError(
                f"Service '{name}' already exists."
            )

        self._services[name] = service

        self._audit(
            "service_registered",
            name=name,
        )


    def register_memory(
        self,
        name: str,
        memory: Any,
    ) -> None:

        self._memories[name] = memory

        self._audit(
            "memory_registered",
            name=name,
        )


    def register_contract(
        self,
        name: str,
        contract: Any,
    ) -> None:

        self._contracts[name] = contract

        self._audit(
            "contract_registered",
            name=name,
        )


    def register_state_manager(
        self,
        name: str,
        manager: Any,
    ) -> None:

        self._state_managers[name] = manager

        self._audit(
            "state_manager_registered",
            name=name,
        )


    def register_plugin(
        self,
        name: str,
        plugin: Any,
    ) -> None:

        self._plugins[name] = plugin

        self._audit(
            "plugin_registered",
            name=name,
        )


    def register_chain(
        self,
        chain: SupportedChain,
    ) -> None:

        self._chains[
            chain.name.lower()
        ] = chain


    def register_protocol(
        self,
        protocol: SupportedProtocol,
    ) -> None:

        self._protocols[
            protocol.name.lower()
        ] = protocol


# =============================================================================
# Registry Lookup
# =============================================================================

    def get_tool(
        self,
        name: str,
    ) -> Any:

        return self._tools.get(name)


    def get_service(
        self,
        name: str,
    ) -> Any:

        return self._services.get(name)


    def get_memory(
        self,
        name: str,
    ) -> Any:

        return self._memories.get(name)


    def get_contract(
        self,
        name: str,
    ) -> Any:

        return self._contracts.get(name)


    def get_plugin(
        self,
        name: str,
    ) -> Any:

        return self._plugins.get(name)


    def get_chain(
        self,
        name: str,
    ) -> SupportedChain | None:

        return self._chains.get(
            name.lower(),
        )


    def get_protocol(
        self,
        name: str,
    ) -> SupportedProtocol | None:

        return self._protocols.get(
            name.lower(),
        )


# =============================================================================
# Registry Removal
# =============================================================================

    def unregister_tool(
        self,
        name: str,
    ) -> None:

        self._tools.pop(
            name,
            None,
        )


    def unregister_service(
        self,
        name: str,
    ) -> None:

        self._services.pop(
            name,
            None,
        )


    def unregister_plugin(
        self,
        name: str,
    ) -> None:

        self._plugins.pop(
            name,
            None,
        )


# =============================================================================
# Registry Inspection
# =============================================================================

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


# =============================================================================
# Internal Audit Helper
# =============================================================================

    def _audit(
        self,
        event: str,
        **data: Any,
    ) -> None:
        """
        Record lightweight audit events.

        Later this will integrate with the
        Audit Engine and Event Bus.
        """

        self._audit_log.append(
            {
                "timestamp": utc_now(),
                "event": event,
                "data": data,
            }
        )
        # =============================================================================
# Dependency Resolution
# =============================================================================

    def has_dependency(
        self,
        name: str,
    ) -> bool:
        """
        Returns True if dependency exists.
        """

        return (
            name in self._services
            or name in self._tools
            or name in self._plugins
            or name in self._memories
            or name in self._contracts
        )


    def resolve(
        self,
        name: str,
    ) -> Any:
        """
        Resolve any registered object.
        """

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


    def require(
        self,
        name: str,
    ) -> Any:
        """
        Resolve or fail immediately.
        """

        dependency = self.resolve(name)

        if dependency is None:
            raise RuntimeError(
                f"Required dependency '{name}' missing."
            )

        return dependency


# =============================================================================
# Resource Management
# =============================================================================

    def register_resource(
        self,
        name: str,
        resource: Any,
    ) -> None:

        self._resources[name] = resource


    def get_resource(
        self,
        name: str,
    ) -> Any:

        return self._resources.get(name)


    async def release_resource(
        self,
        name: str,
    ) -> None:

        resource = self._resources.pop(
            name,
            None,
        )

        if resource is None:
            return

        close = getattr(
            resource,
            "close",
            None,
        )

        if callable(close):

            result = close()

            if asyncio.iscoroutine(result):
                await result


# =============================================================================
# Background Task Management
# =============================================================================

    def create_background_task(
        self,
        coro: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """
        Create and track background task.
        """

        task = asyncio.create_task(
            coro,
            name=name,
        )

        self._tasks.add(task)

        task.add_done_callback(
            self._tasks.discard,
        )

        return task


    async def cancel_background_tasks(
        self,
    ) -> None:

        for task in list(self._tasks):

            if not task.done():
                task.cancel()

        if self._tasks:

            await asyncio.gather(
                *self._tasks,
                return_exceptions=True,
            )


# =============================================================================
# Event System
# =============================================================================

    def subscribe(
        self,
        event: str,
        callback: Any,
    ) -> None:

        self._event_handlers.setdefault(
            event,
            [],
        ).append(callback)


    async def publish_event(
        self,
        event: str,
        payload: Any = None,
    ) -> None:

        handlers = self._event_handlers.get(
            event,
            [],
        )

        for handler in handlers:

            result = handler(payload)

            if asyncio.iscoroutine(result):
                await result


# =============================================================================
# Health & Diagnostics
# =============================================================================

    def health_check(
        self,
    ) -> AgentHealth:
        """
        Return current health.
        """

        self.health.checked_at = utc_now()

        self.health.active_tasks = len(
            self._tasks
        )

        return self.health


    def diagnostics(
        self,
    ) -> dict[str, Any]:
        """
        Runtime diagnostic snapshot.
        """

        return {
            "status": self.status.value,
            "running": self._running,
            "initialized": self._initialized,
            "background_tasks": len(self._tasks),
            "services": len(self._services),
            "tools": len(self._tools),
            "plugins": len(self._plugins),
            "chains": len(self._chains),
            "protocols": len(self._protocols),
            "statistics": self.statistics,
        }


    def snapshot_state(
        self,
    ) -> AgentSnapshot:

        self.snapshot = AgentSnapshot(
            identity=self.identity,
            status=self.status,
            health=self.health,
            statistics=self.statistics,
        )

        return self.snapshot


# =============================================================================
# Cleanup
# =============================================================================

    async def cleanup(
        self,
    ) -> None:
        """
        Release all managed resources.
        """

        await self.cancel_background_tasks()

        for name in list(self._resources):
            await self.release_resource(
                name,
            )

        self._cache.clear()
        self._execution_cache.clear()
        self._temporary_storage.clear()
        self._result_cache.clear()

        self._audit(
            "cleanup_completed",
        )


# =============================================================================
# String Representation
# =============================================================================

    def __repr__(self) -> str:

        return (
            f"{self.__class__.__name__}("
            f"name={self.identity.name!r}, "
            f"status={self.status.value!r})"
        )