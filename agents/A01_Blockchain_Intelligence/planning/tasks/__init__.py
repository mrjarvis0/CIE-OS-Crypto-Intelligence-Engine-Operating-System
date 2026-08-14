"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.tasks

Purpose:
    Task lifecycle, dependency graphs, decomposition, prioritization,
    scheduling, workflows, and plan state for the planning subsystem.
"""

from __future__ import annotations

# ==============================================================================
# Task
# ==============================================================================

from .task import (
    InvalidTaskTransitionError,
    TaskError,
    TaskManager,
    TaskNotFoundError,
)

# ==============================================================================
# Task Graph
# ==============================================================================

from .task_graph import (
    CyclicDependencyError,
    MissingDependencyError,
    TaskGraph,
    TaskGraphError,
)

# ==============================================================================
# Dependency
# ==============================================================================

from .dependency import (
    DependencyError,
    UnknownDependencyError,
    UnsatisfiedDependencyError,
    are_dependencies_satisfied,
    classify_dependencies,
    compute_blocked_tasks,
    get_dependency_statuses,
    is_dependency_blocked,
    resolve_ready_tasks,
)

# ==============================================================================
# Decomposition
# ==============================================================================

from .decomposition import (
    DecompositionError,
    DecompositionService,
    ExceededDepthError,
    NoTasksProducedError,
    build_chain_tasks,
    build_parallel_tasks,
    verify_task_connectivity,
)

# ==============================================================================
# Prioritizer
# ==============================================================================

from .prioritizer import (
    PrioritizedTask,
    TaskPrioritizer,
)

# ==============================================================================
# Scheduler
# ==============================================================================

from .scheduler import (
    ConcurrencyLimitError,
    SchedulerError,
    TaskScheduler,
)

# ==============================================================================
# Workflow
# ==============================================================================

from .workflow import (
    WorkflowDefinition,
    WorkflowError,
    WorkflowNotFoundError,
    WorkflowRegistry,
    WorkflowStep,
)

# ==============================================================================
# Planner State
# ==============================================================================

from .planner_state import (
    PlannerStateError,
    PlannerStateManager,
    PlannerStateNotFoundError,
)

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Task
    "TaskError",
    "TaskNotFoundError",
    "InvalidTaskTransitionError",
    "TaskManager",
    # Task Graph
    "TaskGraphError",
    "CyclicDependencyError",
    "MissingDependencyError",
    "TaskGraph",
    # Dependency
    "DependencyError",
    "UnknownDependencyError",
    "UnsatisfiedDependencyError",
    "get_dependency_statuses",
    "are_dependencies_satisfied",
    "is_dependency_blocked",
    "classify_dependencies",
    "resolve_ready_tasks",
    "compute_blocked_tasks",
    # Decomposition
    "DecompositionError",
    "NoTasksProducedError",
    "ExceededDepthError",
    "DecompositionService",
    "build_chain_tasks",
    "build_parallel_tasks",
    "verify_task_connectivity",
    # Prioritizer
    "PrioritizedTask",
    "TaskPrioritizer",
    # Scheduler
    "SchedulerError",
    "ConcurrencyLimitError",
    "TaskScheduler",
    # Workflow
    "WorkflowError",
    "WorkflowNotFoundError",
    "WorkflowStep",
    "WorkflowDefinition",
    "WorkflowRegistry",
    # Planner State
    "PlannerStateError",
    "PlannerStateNotFoundError",
    "PlannerStateManager",
]
