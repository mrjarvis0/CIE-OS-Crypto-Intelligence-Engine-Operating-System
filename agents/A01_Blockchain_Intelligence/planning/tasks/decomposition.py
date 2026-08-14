"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.decomposition

Purpose:
    Goal decomposition for the planning subsystem.

Splits a goal into an ordered collection of tasks, optionally using a
decomposer strategy, and produces a validated task graph.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from planning.schemas import GoalSchema, TaskSchema
from planning.utils.constants import MAX_DEPTH, Priority

from .dependency import UnknownDependencyError
from .task_graph import TaskGraph

logger = logging.getLogger("a01.planning.tasks")

Decomposer = Callable[[GoalSchema], list[TaskSchema]]


class DecompositionError(Exception):
    """
    Base class for decomposition failures.
    """


class NoTasksProducedError(DecompositionError):
    """
    Raised when a decomposer produces no tasks.
    """


class ExceededDepthError(DecompositionError):
    """
    Raised when decomposition exceeds the allowed depth.
    """


class DecompositionService:
    """
    Splits goals into validated task graphs.

    Responsibilities:
        * Running a user-supplied decomposer
        * Validating the produced task set
        * Building a DAG and detecting cycles
    """

    def __init__(self, decomposer: Decomposer | None = None) -> None:
        self._decomposer = decomposer

    @property
    def decomposer(self) -> Decomposer | None:
        """The active decomposer strategy."""
        return self._decomposer

    def set_decomposer(self, decomposer: Decomposer) -> None:
        """Replace the active decomposer strategy."""
        self._decomposer = decomposer

    async def decompose(
        self,
        goal: GoalSchema,
        *,
        plan_id: str | None = None,
        depth: int = 0,
    ) -> TaskGraph:
        """
        Decompose a goal into a validated task graph.

        Raises
        ------
        ExceededDepthError
            When ``depth`` exceeds the maximum allowed.
        NoTasksProducedError
            When the decomposer produces no tasks.
        CyclicDependencyError
            When tasks form a dependency cycle.
        """

        if depth > MAX_DEPTH:
            raise ExceededDepthError(
                f"decomposition depth {depth} exceeds max {MAX_DEPTH}"
            )

        if self._decomposer is None:
            raise DecompositionError("no decomposer strategy configured")

        tasks = list(self._decomposer(goal))

        if not tasks:
            raise NoTasksProducedError(
                f"decomposer produced no tasks for goal {goal.id}"
            )

        for task in tasks:
            if task.goal_id is None:
                task.goal_id = goal.id
            if task.plan_id is None:
                task.plan_id = plan_id
            task.validate()

        graph = TaskGraph(tasks)
        graph.validate_dag()
        logger.info(
            "goal %s decomposed into %d tasks", goal.id, len(tasks)
        )
        return graph


def build_chain_tasks(
    goal: GoalSchema,
    names: Iterable[str],
    *,
    priority: Priority = Priority.NORMAL,
    plan_id: str | None = None,
) -> list[TaskSchema]:
    """
    Build a linear chain of dependent tasks.

    Each task depends on the previous task, producing a sequential
    pipeline. Useful as a default decomposer for simple goals.
    """

    name_list = list(names)
    tasks: list[TaskSchema] = []
    previous: str | None = None

    for name in name_list:
        task = TaskSchema(
            name=name,
            plan_id=plan_id,
            goal_id=goal.id,
            priority=priority,
        )

        if previous is not None:
            task.dependencies = [previous]

        tasks.append(task)
        previous = task.id

    return tasks


def build_parallel_tasks(
    goal: GoalSchema,
    names: Iterable[str],
    *,
    priority: Priority = Priority.NORMAL,
    plan_id: str | None = None,
) -> list[TaskSchema]:
    """
    Build independent parallel tasks.

    No task depends on another; the produced graph is a star with a
    single execution level.
    """

    return [
        TaskSchema(
            name=name,
            plan_id=plan_id,
            goal_id=goal.id,
            priority=priority,
        )
        for name in names
    ]


def verify_task_connectivity(
    tasks: Iterable[TaskSchema],
    known_ids: set[str],
) -> None:
    """
    Verify that all dependencies reference known tasks.

    Raises
    ------
    UnknownDependencyError
        When a dependency references an unknown task.
    """

    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in known_ids:
                raise UnknownDependencyError(
                    f"task {task.id} depends on unknown task {dependency}"
                )
