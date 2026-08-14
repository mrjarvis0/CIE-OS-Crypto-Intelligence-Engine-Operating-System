"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.dependency

Purpose:
    Dependency validation and readiness resolution for tasks.

Determines whether tasks are runnable based on the status of their
dependencies, and validates that dependencies reference known tasks.
"""

from __future__ import annotations

import logging

from planning.schemas import TaskSchema
from planning.utils.constants import TaskStatus

logger = logging.getLogger("a01.planning.tasks")


class DependencyError(Exception):
    """
    Base class for dependency failures.
    """


class UnknownDependencyError(DependencyError):
    """
    Raised when a dependency references an unknown task.
    """


class UnsatisfiedDependencyError(DependencyError):
    """
    Raised when a task's dependencies are not yet satisfied.
    """


# Statuses that count as a satisfied dependency.
_SATISFIED: frozenset[TaskStatus] = frozenset({TaskStatus.SUCCEEDED})

# Statuses that count as a failed dependency (blocking or terminal).
_BLOCKED: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    }
)


def get_dependency_statuses(
    task: TaskSchema,
    tasks: dict[str, TaskSchema],
) -> dict[str, TaskStatus]:
    """
    Resolve the current status of every dependency of a task.

    Raises
    ------
    UnknownDependencyError
        When a dependency is not present in ``tasks``.
    """

    statuses: dict[str, TaskStatus] = {}

    for dependency in task.dependencies:
        dependency_task = tasks.get(dependency)

        if dependency_task is None:
            raise UnknownDependencyError(
                f"task {task.id} depends on unknown task {dependency}"
            )

        statuses[dependency] = dependency_task.status

    return statuses


def are_dependencies_satisfied(
    task: TaskSchema,
    tasks: dict[str, TaskSchema],
) -> bool:
    """Whether every dependency of a task has succeeded."""

    statuses = get_dependency_statuses(task, tasks)
    return all(status in _SATISFIED for status in statuses.values())


def is_dependency_blocked(
    task: TaskSchema,
    tasks: dict[str, TaskSchema],
) -> bool:
    """Whether any dependency has failed or been skipped/cancelled."""

    statuses = get_dependency_statuses(task, tasks)
    return any(status in _BLOCKED for status in statuses.values())


def classify_dependencies(
    task: TaskSchema,
    tasks: dict[str, TaskSchema],
) -> dict[str, str]:
    """
    Classify each dependency of a task.

    Returns a mapping of dependency id to one of:
        * ``satisfied`` — dependency succeeded
        * ``blocked`` — dependency failed, cancelled, or skipped
        * ``pending`` — dependency still in progress
    """

    statuses = get_dependency_statuses(task, tasks)
    classified: dict[str, str] = {}

    for dependency, status in statuses.items():
        if status in _SATISFIED:
            classified[dependency] = "satisfied"
        elif status in _BLOCKED:
            classified[dependency] = "blocked"
        else:
            classified[dependency] = "pending"

    return classified


def resolve_ready_tasks(
    tasks: dict[str, TaskSchema],
    *,
    include_blocked: bool = True,
) -> list[TaskSchema]:
    """
    Return tasks whose dependencies are satisfied.

    Tasks with no dependencies are always ready. When ``include_blocked``
    is false, tasks whose dependencies are blocked are excluded even if
    all other dependencies are satisfied.
    """

    ready: list[TaskSchema] = []

    for task in tasks.values():
        if task.status != TaskStatus.PENDING and task.status != TaskStatus.BLOCKED:
            continue

        statuses = get_dependency_statuses(task, tasks)

        if not statuses:
            ready.append(task)
            continue

        satisfied = all(status in _SATISFIED for status in statuses.values())

        if satisfied:
            ready.append(task)
            continue

        if not include_blocked and any(
            status in _BLOCKED for status in statuses.values()
        ):
            continue

    return ready


def compute_blocked_tasks(
    tasks: dict[str, TaskSchema],
) -> list[TaskSchema]:
    """
    Return tasks currently blocked by a failed dependency.

    These tasks can never run as planned and should be skipped or
    reconsidered during replanning.
    """

    blocked: list[TaskSchema] = []

    for task in tasks.values():
        if task.status in (TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.READY):
            if is_dependency_blocked(task, tasks):
                blocked.append(task)

    return blocked
