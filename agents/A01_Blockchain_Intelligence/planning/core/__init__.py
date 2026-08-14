"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.core

Purpose:
    Core orchestration for the planning stack.

Wires the context, planner, dispatcher, executor, lifecycle,
coordinator, orchestrator, and runtime into a coherent entry point.
"""

from __future__ import annotations

# ==============================================================================
# Context
# ==============================================================================

from .context import PlanningContext

# ==============================================================================
# Planner
# ==============================================================================

from .planner import (
    PlanConstructionError,
    Planner,
    PlannerError,
)

# ==============================================================================
# Dispatcher
# ==============================================================================

from .dispatcher import (
    DispatchError,
    Dispatcher,
    NoTargetError,
)

# ==============================================================================
# Executor
# ==============================================================================

from .executor import (
    ExecutionReport,
    PlanExecutor,
)

# ==============================================================================
# Lifecycle
# ==============================================================================

from .lifecycle import (
    InvalidTransitionError,
    LifecycleError,
    LifecycleState,
    PlanLifecycle,
)

# ==============================================================================
# Coordinator
# ==============================================================================

from .coordinator import (
    Coordinator,
    PlanOutcome,
)

# ==============================================================================
# Orchestrator
# ==============================================================================

from .orchestrator import (
    Orchestrator,
    OrchestratorError,
)

# ==============================================================================
# Runtime
# ==============================================================================

from .runtime import PlanningRuntime

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Context
    "PlanningContext",
    # Planner
    "PlannerError",
    "PlanConstructionError",
    "Planner",
    # Dispatcher
    "DispatchError",
    "NoTargetError",
    "Dispatcher",
    # Executor
    "ExecutionReport",
    "PlanExecutor",
    # Lifecycle
    "LifecycleError",
    "InvalidTransitionError",
    "LifecycleState",
    "PlanLifecycle",
    # Coordinator
    "Coordinator",
    "PlanOutcome",
    # Orchestrator
    "OrchestratorError",
    "Orchestrator",
    # Runtime
    "PlanningRuntime",
]
