"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.scheduler

Purpose:
    Task scheduling for the planning subsystem.

Determines which tasks are runnable at any moment, respecting
dependencies, concurrency limits, and priority ordering.
"""

from __future__ import annotations

import logging

from planning.schemas import TaskSchema
from planning.utils.constants import DEFAULT_MAX_CONCURRENT_TASKS

from .dependency import (
    UnknownDependencyError,
    resolve_ready_tasks,
)
from .prioritizer import PrioritizedTask, TaskPrioritizer

logger = logging.getLogger("a01.planning.tasks")


class SchedulerError(Exception):
    """
    Base class for scheduler failures.
    """


class ConcurrencyLimitError(SchedulerError):
    """
    Raised when a scheduling request exceeds the concurrency limit.
    """


class TaskScheduler:
    """
    Schedules tasks against dependency and concurrency constraints.

    Responsibilities:
        * Resolving ready tasks
        * Applying priority ordering
        * Enforcing the concurrency limit
        * Reporting scheduling decisions
    """

    def __init__(
        self,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT_TASKS,
        prioritizer: TaskPrioritizer | None = None,
    ) -> None:
        if max_concurrent < 1:
            raise SchedulerError("max_concurrent must be >= 1")

        self._max_concurrent = max_concurrent
        self._prioritizer = prioritizer or TaskPrioritizer()

    @property
    def max_concurrent(self) -> int:
        """The configured concurrency limit."""
        return self._max_concurrent

    def set_max_concurrent(self, limit: int) -> None:
        """Update the concurrency limit."""
        if limit < 1:
            raise SchedulerError("max_concurrent must be >= 1")
        self._max_concurrent = limit

    def schedule(
        self,
        tasks: dict[str, TaskSchema],
        *,
        running_count: int = 0,
        slots: int | None = None,
    ) -> list[PrioritizedTask]:
        """
        Return the next batch of tasks to execute.

        Parameters
        ----------
        tasks
            All known tasks keyed by id.
        running_count
            Tasks currently executing.
        slots
            Override the number of available slots (defaults to
            ``max_concurrent - running_count``).

        Raises
        ------
        UnknownDependencyError
            When a dependency references an unknown task.
        ConcurrencyLimitError
            When ``running_count`` already exceeds the limit.
        """

        if running_count > self._max_concurrent:
            raise ConcurrencyLimitError(
                f"running_count {running_count} exceeds limit {self._max_concurrent}"
            )

        available = slots if slots is not None else self._max_concurrent - running_count

        if available < 1:
            return []

        ready = resolve_ready_tasks(tasks, include_blocked=False)
        prioritized = self._prioritize(ready)

        logger.info(
            "scheduled %d of %d ready tasks (%d slots)",
            min(len(prioritized), available),
            len(ready),
            available,
        )
        return prioritized[:available]

    def _prioritize(self, ready: list[TaskSchema]) -> list[PrioritizedTask]:
        """Order ready tasks using the prioritizer."""
        return self._prioritizer.prioritize(ready)

    def depth_map(self, tasks: dict[str, TaskSchema]) -> dict[str, int]:
        """
        Compute the dependency depth of every task.

        A task with no dependencies has depth 0; otherwise depth is one
        plus the maximum depth of its dependencies.
        """

        depths: dict[str, int] = {}

        def compute(task_id: str) -> int:
            if task_id in depths:
                return depths[task_id]

            task = tasks.get(task_id)

            if task is None:
                raise UnknownDependencyError(f"unknown task: {task_id}")

            if not task.dependencies:
                depths[task_id] = 0
                return 0

            max_dependency_depth = max(
                compute(dependency) for dependency in task.dependencies
            )
            depths[task_id] = max_dependency_depth + 1
            return depths[task_id]

        for task_id in tasks:
            compute(task_id)

        return depths

    def schedule_with_depth(
        self,
        tasks: dict[str, TaskSchema],
        *,
        running_count: int = 0,
    ) -> list[PrioritizedTask]:
        """
        Schedule ready tasks using dependency depth in prioritization.

        Runs the same pipeline as ``schedule`` but passes a depth map to
        the prioritizer for depth-aware ordering.
        """

        if running_count > self._max_concurrent:
            raise ConcurrencyLimitError(
                f"running_count {running_count} exceeds limit {self._max_concurrent}"
            )

        available = self._max_concurrent - running_count

        if available < 1:
            return []

        ready = resolve_ready_tasks(tasks, include_blocked=False)
        depth_map = self.depth_map(tasks)
        prioritized = self._prioritizer.prioritize(ready, depth_map=depth_map)

        return prioritized[:available]
