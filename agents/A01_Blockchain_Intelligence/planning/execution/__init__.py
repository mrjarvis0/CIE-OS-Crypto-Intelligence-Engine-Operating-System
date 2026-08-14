"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.execution

Purpose:
    Task execution subsystem for the planning stack.

Provides state-machined single-task execution, sequential and
parallel runners, checkpointing, and recovery.
"""

from __future__ import annotations

from .checkpoint import Checkpoint, CheckpointManager
from .executor import (
    ExecutionError,
    ExecutionExhaustedError,
    ExecutionTimeoutError,
    Handler,
    TaskExecutor,
)
from .recovery import RecoveryResult, RecoveryService
from .runners import AsyncRunner, ParallelExecutor, SequentialExecutor
from .state_machine import (
    ExecutionStateMachine,
    InvalidExecutionTransitionError,
    StateMachineError,
)

__all__ = [
    "AsyncRunner",
    "Checkpoint",
    "CheckpointManager",
    "ExecutionError",
    "ExecutionExhaustedError",
    "ExecutionStateMachine",
    "ExecutionTimeoutError",
    "Handler",
    "InvalidExecutionTransitionError",
    "ParallelExecutor",
    "RecoveryResult",
    "RecoveryService",
    "SequentialExecutor",
    "StateMachineError",
    "TaskExecutor",
]
