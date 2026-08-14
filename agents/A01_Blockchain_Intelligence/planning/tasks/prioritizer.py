"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.prioritizer

Purpose:
    Task prioritization for the planning subsystem.

Produces an execution order for ready tasks based on priority,
dependency depth, and optional custom scoring.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from planning.schemas import TaskSchema
from planning.utils.constants import Priority

logger = logging.getLogger("a01.planning.tasks")

Scorer = Callable[[TaskSchema], float]


@dataclass(slots=True)
class PrioritizedTask:
    """
    A task with its computed scheduling weight.

    Fields:
        * Task reference
        * Weight (higher = higher scheduling priority)
        * Human-readable rationale
    """

    task: TaskSchema
    weight: float
    rationale: str = ""


class TaskPrioritizer:
    """
    Orders tasks by scheduling weight.

    Responsibilities:
        * Weight computation from priority, depth, and scoring
        * Stable ordering of candidate tasks
    """

    def __init__(
        self,
        *,
        custom_scorer: Scorer | None = None,
        depth_bias: float = 0.5,
    ) -> None:
        self._custom_scorer = custom_scorer
        self._depth_bias = depth_bias

    def set_scorer(self, scorer: Scorer) -> None:
        """Install a custom scoring function."""
        self._custom_scorer = scorer

    def _weight(self, task: TaskSchema, depth: int) -> float:
        """
        Compute the scheduling weight of a task.

        Weight = priority_score + depth_bias * depth (+ custom score).
        """

        priority_score = self._priority_score(task.priority)
        weight = priority_score + self._depth_bias * depth

        if self._custom_scorer is not None:
            try:
                weight += self._custom_scorer(task)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("custom scorer failed for %s: %s", task.id, exc)

        return weight

    def prioritize(
        self,
        tasks: list[TaskSchema],
        *,
        depth_map: dict[str, int] | None = None,
    ) -> list[PrioritizedTask]:
        """
        Return tasks ordered by descending weight.

        Parameters
        ----------
        tasks
            Candidate tasks to order.
        depth_map
            Optional mapping of task id to dependency depth. Depth is
            defaulted to the maximum known depth plus one.
        """

        max_depth = max(depth_map.values()) if depth_map else 0

        prioritized: list[PrioritizedTask] = []

        for task in tasks:
            depth = depth_map.get(task.id, max_depth) if depth_map else 0
            weight = self._weight(task, depth)

            rationale = (
                f"priority={task.priority.value}, depth={depth}, "
                f"weight={weight:.2f}"
            )
            prioritized.append(
                PrioritizedTask(task=task, weight=weight, rationale=rationale)
            )

        prioritized.sort(key=lambda item: item.weight, reverse=True)
        return prioritized

    @staticmethod
    def _priority_score(priority: Priority) -> float:
        """Normalize an enum priority to a [0, 1] score."""
        return priority.value / 100.0
