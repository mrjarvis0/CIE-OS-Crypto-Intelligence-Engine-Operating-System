"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    core

Purpose:
    Public API for the Core execution engine.

The Core package provides the runtime foundation for the A01 Blockchain
Intelligence Agent. It is responsible for coordinating the lifecycle,
execution, orchestration, context propagation, event processing,
guardrails, and task scheduling.

Design Principles
-----------------
- Async-first
- Event-driven
- Modular
- Strongly typed
- Security-first
- Extensible
- Production-ready

Notes
-----
Only stable public interfaces should be exported here.
Avoid business logic or heavy initialization inside __init__.py.
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "CIE-OS"
__package_name__ = "core"

# ============================================================================
# Core Runtime
# ============================================================================

from .agent import BaseAgent
from .context import AgentContext
from .lifecycle import AgentLifecycle, LifecycleState
from .runtime import AgentRuntime

# ============================================================================
# Types & Exceptions
# ============================================================================

from .exceptions import (
    AgentError,
    AgentInitializationError,
    AgentRuntimeError,
    CheckpointError,
    ContextError,
    FinalityViolationError,
    GuardrailError,
    IngestionError,
    LifecycleError,
    PipelineError,
    SensorError,
    ToolExecutionError,
)

from .types import (
    AgentStatus,
    ExecutionMode,
    ExecutionResult,
    TaskPriority,
)

# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Metadata
    "__version__",
    "__author__",
    "__package_name__",

    # Core
    "BaseAgent",
    "AgentRuntime",
    "AgentContext",
    "AgentLifecycle",
    "LifecycleState",

    # Types
    "AgentStatus",
    "ExecutionMode",
    "ExecutionResult",
    "TaskPriority",

    # Exceptions
    "AgentError",
    "AgentInitializationError",
    "AgentRuntimeError",
    "CheckpointError",
    "ContextError",
    "FinalityViolationError",
    "GuardrailError",
    "IngestionError",
    "LifecycleError",
    "PipelineError",
    "SensorError",
    "ToolExecutionError",
]