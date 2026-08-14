"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.task_graph

Purpose:
    Dependency graph construction and analysis for tasks.

Builds a ``DiGraph`` from task dependencies and provides DAG
validation, topological ordering, levels, and cycle detection.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from planning.schemas import TaskSchema
from planning.utils.graph import DiGraph, find_cycles, is_dag, topological_sort

logger = logging.getLogger("a01.planning.tasks")


class TaskGraphError(Exception):
    """
    Base class for task graph failures.
    """


class CyclicDependencyError(TaskGraphError):
    """
    Raised when task dependencies form a cycle.
    """


class MissingDependencyError(TaskGraphError):
    """
    Raised when a dependency references an unknown task.
    """


class TaskGraph:
    """
    Dependency graph over a collection of tasks.

    Responsibilities:
        * Graph construction from tasks
        * DAG validation and cycle detection
        * Topological order and level computation
    """

    def __init__(self, tasks: Iterable[TaskSchema] | None = None) -> None:
        self._graph = DiGraph[str]()
        self._tasks: dict[str, TaskSchema] = {}

        if tasks is not None:
            self.add_tasks(tasks)

    @property
    def graph(self) -> DiGraph[str]:
        """The underlying directed graph keyed by task id."""
        return self._graph

    @property
    def tasks(self) -> dict[str, TaskSchema]:
        """Tasks keyed by id."""
        return dict(self._tasks)

    @property
    def task_ids(self) -> list[str]:
        """All task ids in the graph."""
        return self._graph.nodes()

    def add_task(self, task: TaskSchema) -> None:
        """Add a task and its dependency edges to the graph."""
        self._graph.add_node(task.id)
        self._tasks[task.id] = task

    def add_tasks(self, tasks: Iterable[TaskSchema]) -> None:
        """Add multiple tasks to the graph."""
        for task in tasks:
            self.add_task(task)

        self._wire_dependencies()

    def _wire_dependencies(self) -> None:
        """Connect dependency edges after all nodes are registered."""
        for task_id, task in self._tasks.items():
            for dependency in task.dependencies:
                if dependency not in self._graph:
                    raise MissingDependencyError(
                        f"task {task_id} depends on unknown task {dependency}"
                    )
                self._graph.add_edge(dependency, task_id)

    def validate_dag(self) -> None:
        """
        Validate that the graph is acyclic and fully connected.

        Raises
        ------
        CyclicDependencyError
            When a dependency cycle exists.
        """

        cycles = find_cycles(self._graph)

        if cycles:
            raise CyclicDependencyError(
                f"cyclic task dependencies: {cycles}"
            )

    @property
    def is_dag(self) -> bool:
        """Whether the graph contains no cycles."""
        return is_dag(self._graph)

    def topological_order(self) -> list[str]:
        """Return task ids in dependency order."""
        self.validate_dag()
        return list(topological_sort(self._graph))

    def execution_levels(self) -> list[list[str]]:
        """
        Group task ids into parallel execution levels.

        Level 0 contains tasks with no dependencies; each subsequent
        level contains tasks whose dependencies are all in earlier levels.
        """

        self.validate_dag()

        order = self.topological_order()
        levels: list[list[str]] = []
        level_index: dict[str, int] = {}

        for task_id in order:
            dependencies = self._tasks[task_id].dependencies

            if not dependencies:
                level = 0
            else:
                level = max(level_index[dep] for dep in dependencies) + 1

            while len(levels) <= level:
                levels.append([])

            levels[level].append(task_id)
            level_index[task_id] = level

        return levels

    def successors(self, task_id: str) -> list[str]:
        """Return immediate dependents of a task."""
        return list(self._graph.successors(task_id))

    def predecessors(self, task_id: str) -> list[str]:
        """Return immediate dependencies of a task."""
        return list(self._graph.predecessors(task_id))

    def get(self, task_id: str) -> TaskSchema:
        """Return the task associated with an id."""
        return self._tasks[task_id]

    def size(self) -> int:
        """Return the number of tasks."""
        return len(self._tasks)
