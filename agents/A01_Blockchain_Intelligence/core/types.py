"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.types

Purpose:
    Shared enums and result types exported by the ``core`` public API.

Notes
-----
``core.agent`` defines its own richer ``AgentStatus`` / ``ExecutionMode`` for
the BaseAgent state machine. The versions here are the lightweight ones used
by callers that only depend on ``core``'s public surface; keep the member
values of the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


class AgentStatus(StrEnum):
    CREATED = "created"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class ExecutionMode(StrEnum):
    SYNC = "sync"
    ASYNC = "async"
    BACKGROUND = "background"


class TaskPriority(IntEnum):
    LOW = 10
    NORMAL = 50
    HIGH = 80
    CRITICAL = 100


@dataclass(slots=True)
class ExecutionResult:
    """
    Outcome of a single agent or task execution.

    ``error`` carries a human-readable message rather than the exception
    object so the result stays JSON-serializable and safe to log.
    """

    success: bool

    output: Any = None

    error: str | None = None

    execution_id: str | None = None

    started_at: datetime = field(default_factory=utc_now)

    finished_at: datetime | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        """True when the execution did not succeed."""
        return not self.success

    @property
    def duration_ms(self) -> float | None:
        """Elapsed time in milliseconds, or None if still running."""
        if self.finished_at is None:
            return None

        delta = self.finished_at - self.started_at
        return delta.total_seconds() * 1000.0


__all__ = [
    "AgentStatus",
    "ExecutionMode",
    "ExecutionResult",
    "TaskPriority",
    "utc_now",
]
