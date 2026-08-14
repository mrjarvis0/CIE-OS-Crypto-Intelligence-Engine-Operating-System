"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning

Purpose:
    Cognitive planning subsystem for the A01 Blockchain Intelligence
    Agent.

Transforms goals into validated task graphs, routes tasks to tools and
agents, executes plans with retries and checkpoints, validates and
verifies results, reflects on outcomes, and replans when needed.

Subpackages
-----------
core        Context, planner, dispatcher, executor, lifecycle,
            coordinator, orchestrator, and runtime.
goals       Goal, objective, constraint, assumption, and success
            management.
tasks       Task management, decomposition, scheduling, and workflows.
routing     Routing strategies, policies, and selectors.
execution   State-machine task execution, sequential/parallel runners,
            checkpoints, and recovery.
reasoning   Critic, evaluator, reflection, replanner, retry, validator,
            and verifier.
monitoring  Events, metrics, tracing, timelines, progress, diagnostics.
schemas     Canonical data models.
utils       Shared constants, helpers, serialization, hashing, ids,
            timers, validation, graph utilities, and decorators.
"""

from __future__ import annotations

from . import (
    core,
    execution,
    goals,
    monitoring,
    reasoning,
    routing,
    schemas,
    tasks,
    utils,
)
from .core import (
    Coordinator,
    InvalidTransitionError,
    Orchestrator,
    PlanConstructionError,
    PlanLifecycle,
    PlanOutcome,
    Planner,
    PlanningContext,
    PlanningRuntime,
)
from .utils.constants import (
    ExecutionMode,
    ExecutionStatus,
    EventType,
    GoalStatus,
    PlanningState,
    Priority,
    RetryPolicy,
    RoutingStrategy,
    TaskStatus,
)

__all__ = [
    # Subpackages
    "core",
    "execution",
    "goals",
    "monitoring",
    "reasoning",
    "routing",
    "schemas",
    "tasks",
    "utils",
    # Core
    "PlanningContext",
    "Planner",
    "PlanConstructionError",
    "PlanLifecycle",
    "InvalidTransitionError",
    "Coordinator",
    "PlanOutcome",
    "Orchestrator",
    "PlanningRuntime",
    # Constants
    "PlanningState",
    "GoalStatus",
    "TaskStatus",
    "ExecutionStatus",
    "ExecutionMode",
    "Priority",
    "RetryPolicy",
    "RoutingStrategy",
    "EventType",
]
