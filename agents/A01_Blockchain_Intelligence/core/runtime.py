"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.runtime

Purpose:
    Runtime execution engine.

Part 1 includes only the runtime foundation.

The AgentRuntime implementation is added in Part 2.
"""

from __future__ import annotations

import os
import socket
import time
import uuid

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

# =============================================================================
# Helpers
# =============================================================================


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


def generate_runtime_id() -> str:
    """Generate unique runtime identifier."""
    return str(uuid.uuid4())


# =============================================================================
# Runtime Status
# =============================================================================


class RuntimeStatus(StrEnum):
    CREATED = "created"

    INITIALIZING = "initializing"

    READY = "ready"

    RUNNING = "running"

    STOPPING = "stopping"

    STOPPED = "stopped"

    FAILED = "failed"

    SHUTDOWN = "shutdown"


# =============================================================================
# Runtime Mode
# =============================================================================


class RuntimeMode(StrEnum):
    DEVELOPMENT = "development"

    TESTING = "testing"

    STAGING = "staging"

    PRODUCTION = "production"


# =============================================================================
# Runtime Metrics
# =============================================================================


@dataclass(slots=True)
class RuntimeMetrics:
    """
    Runtime performance metrics.
    """

    started_at: datetime = field(default_factory=utc_now)

    uptime_seconds: float = 0.0

    total_requests: int = 0

    successful_requests: int = 0

    failed_requests: int = 0

    total_tool_calls: int = 0

    total_rpc_calls: int = 0

    average_latency_ms: float = 0.0

    peak_memory_mb: float = 0.0

    cpu_percent: float = 0.0

    active_workers: int = 0

    def update_uptime(self) -> None:
        self.uptime_seconds = (
            utc_now() - self.started_at
        ).total_seconds()


# =============================================================================
# Runtime Event
# =============================================================================


@dataclass(slots=True)
class RuntimeEvent:
    """
    Runtime event object.
    """

    event_id: str = field(default_factory=generate_runtime_id)

    timestamp: datetime = field(default_factory=utc_now)

    event_type: str = ""

    message: str = ""

    source: str = "runtime"

    severity: str = "INFO"

    metadata: dict[str, Any] = field(default_factory=dict)




@dataclass(slots=True)
class RuntimeConfig:
    """
    Runtime configuration.
    """

    runtime_name: str = "A01-Blockchain-Agent"

    version: str = "1.0.0"

    environment: RuntimeMode = RuntimeMode.DEVELOPMENT

    debug: bool = False

    enable_metrics: bool = True

    enable_health_checks: bool = True

    heartbeat_interval: int = 30

    max_concurrent_tasks: int = 100

    shutdown_timeout: int = 30

    auto_restart: bool = False

    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Runtime Information
# =============================================================================


@dataclass(slots=True)
class RuntimeInfo:
    """
    Static runtime information.
    """

    runtime_id: str = field(default_factory=generate_runtime_id)

    hostname: str = field(default_factory=socket.gethostname)

    process_id: int = field(default_factory=os.getpid)

    started_at: datetime = field(default_factory=utc_now)

    version: str = "1.0.0"


# =============================================================================
# Constants
# =============================================================================


DEFAULT_RUNTIME_NAME: Final[str] = "A01 Blockchain Runtime"

DEFAULT_HEARTBEAT: Final[int] = 30

DEFAULT_MAX_WORKERS: Final[int] = 100

DEFAULT_SHUTDOWN_TIMEOUT: Final[int] = 30
# =============================================================================
# Part 2 Imports
# =============================================================================

import asyncio
from collections.abc import Awaitable, Callable

from .context import AgentContext
from .lifecycle import AgentLifecycle

# =============================================================================
# Service Type
# =============================================================================

Service = object

# =============================================================================
# Agent Runtime
# =============================================================================


class AgentRuntime:
    """
    Central runtime responsible for bootstrapping
    and managing the entire agent.

    Responsibilities
    ----------------
    - Context management
    - Lifecycle management
    - Service registry
    - Runtime startup
    - Runtime shutdown
    - Background workers
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
    ) -> None:

        self.config = config or RuntimeConfig()

        self.info = RuntimeInfo()

        self.metrics = RuntimeMetrics()

        self.status = RuntimeStatus.CREATED

        self.context = AgentContext()

        self.lifecycle = AgentLifecycle()

        self._services: dict[str, Service] = {}

        self._background_tasks: set[asyncio.Task] = set()

        self._startup_complete = False

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self.status is RuntimeStatus.RUNNING

    @property
    def service_count(self) -> int:
        return len(self._services)

    # ------------------------------------------------------------------
    # Service Registry
    # ------------------------------------------------------------------

    def register_service(
        self,
        name: str,
        service: Service,
    ) -> None:

        self._services[name] = service

        self.context.register_service(
            name,
            service,
        )

    def get_service(
        self,
        name: str,
    ) -> Service:

        return self._services[name]

    def has_service(
        self,
        name: str,
    ) -> bool:

        return name in self._services

    async def initialize_services(self) -> None:
        """
        Initialize registered services.

        Later versions will support dependency ordering.
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

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def initialize(self) -> None:

        async with self._lock:

            if self._startup_complete:
                return

            self.status = RuntimeStatus.INITIALIZING

            await self.lifecycle.initialize()

            await self.initialize_services()

            await self.lifecycle.ready()

            self.status = RuntimeStatus.READY

            self._startup_complete = True

    async def start(self) -> None:

        if not self._startup_complete:
            await self.initialize()

        await self.lifecycle.start()

        self.status = RuntimeStatus.RUNNING

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def stop(self) -> None:

        if self.status is RuntimeStatus.STOPPED:
            return

        await self.lifecycle.stop()

        self.status = RuntimeStatus.STOPPED

    async def shutdown(self) -> None:

        if self.status is RuntimeStatus.SHUTDOWN:
            return

        await self.stop()

        await self.lifecycle.shutdown()

        self.status = RuntimeStatus.SHUTDOWN

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------

    async def restart(self) -> None:

        await self.shutdown()

        self._startup_complete = False

        await self.initialize()

        await self.start()
        # =============================================================================
# Part 3 - Runtime Execution Engine
# =============================================================================

from contextlib import suppress


class AgentRuntime(AgentRuntime):
    """
    Runtime execution extensions.
    """

    # ------------------------------------------------------------------
    # Task Management
    # ------------------------------------------------------------------

    def create_background_task(
        self,
        coro: Awaitable,
        *,
        name: str | None = None,
    ) -> asyncio.Task:
        """
        Create and track a background task.
        """

        task = asyncio.create_task(coro, name=name)

        self._background_tasks.add(task)

        task.add_done_callback(
            self._background_tasks.discard
        )

        return task

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        callback: Callable[..., Awaitable],
        *args,
        **kwargs,
    ):
        """
        Execute a coroutine inside the runtime.

        Updates metrics automatically.
        """

        started = time.perf_counter()

        self.metrics.total_requests += 1

        try:

            result = await callback(*args, **kwargs)

            self.metrics.successful_requests += 1

            return result

        except Exception:

            self.metrics.failed_requests += 1

            raise

        finally:

            elapsed = (
                time.perf_counter() - started
            ) * 1000

            total = self.metrics.total_requests

            avg = self.metrics.average_latency_ms

            self.metrics.average_latency_ms = (
                ((avg * (total - 1)) + elapsed)
                / total
            )

    # ------------------------------------------------------------------
    # Event Dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        event: RuntimeEvent,
    ) -> None:
        """
        Dispatch runtime events.

        Future versions will forward events to
        EventBus and Observability.
        """

        _ = event

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(self) -> None:
        """
        Runtime heartbeat loop.
        """

        while self.is_running:

            self.metrics.update_uptime()

            await asyncio.sleep(
                self.config.heartbeat_interval
            )

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Basic runtime health.
        """

        return (
            self.status is RuntimeStatus.RUNNING
            and self.lifecycle.state.value == "running"
        )

    # ------------------------------------------------------------------
    # Background Workers
    # ------------------------------------------------------------------

    async def start_background_workers(self) -> None:
        """
        Start runtime workers.
        """

        self.create_background_task(
            self.heartbeat(),
            name="heartbeat",
        )

    async def stop_background_workers(self) -> None:
        """
        Gracefully stop workers.
        """

        tasks = list(self._background_tasks)

        for task in tasks:
            task.cancel()

        for task in tasks:

            with suppress(asyncio.CancelledError):
                await task

        self._background_tasks.clear()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """
        Runtime cleanup.
        """

        await self.stop_background_workers()

        self.context.clear_shared()

        self.metrics.update_uptime()