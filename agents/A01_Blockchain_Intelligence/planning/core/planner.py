"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.planner

Purpose:
    Plan construction for the planning subsystem.

Decomposes a goal into a validated task graph, creates the associated
tasks, and assembles a plan with dependency ordering.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.schemas import GoalSchema, PlanSchema
from planning.utils.ids import generate_plan_id

from ..tasks.decomposition import (
    DecompositionError,
    DecompositionService,
)
from ..tasks.task_graph import (
    CyclicDependencyError,
    MissingDependencyError,
    TaskGraph,
)
from .context import PlanningContext

logger = logging.getLogger("a01.planning.core")


class PlannerError(Exception):
    """
    Base class for planner failures.
    """


class PlanConstructionError(PlannerError):
    """
    Raised when a plan cannot be constructed.
    """


class Planner:
    """
    Builds plans from goals.

    Responsibilities:
        * Goal decomposition
        * Task registration
        * Plan assembly
    """

    def __init__(self, context: PlanningContext) -> None:
        self._context = context

    @property
    def context(self) -> PlanningContext:
        """The bound planning context."""
        return self._context

    @property
    def decomposer(self) -> DecompositionService:
        """The active decomposition service."""
        return self._context.decomposer

    async def plan_from_goal(
        self,
        goal: GoalSchema,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlanSchema:
        """
        Decompose a goal and construct a plan.

        Raises
        ------
        PlanConstructionError
            When decomposition or plan assembly fails.
        """

        generated_plan_id = plan_id or generate_plan_id()

        try:
            graph = await self.decomposer.decompose(
                goal,
                plan_id=generated_plan_id,
            )
        except (
            DecompositionError,
            CyclicDependencyError,
            MissingDependencyError,
        ) as exc:
            raise PlanConstructionError(
                f"goal decomposition failed: {exc}"
            ) from exc

        await self._register_tasks(graph)
        return await self._build_plan(
            goal,
            graph,
            plan_id=generated_plan_id,
            name=name,
            metadata=metadata,
        )

    async def _register_tasks(
        self,
        graph: TaskGraph,
    ) -> None:
        for task in graph.tasks.values():
            await self._context.tasks.register(task)

    async def _build_plan(
        self,
        goal: GoalSchema,
        graph: TaskGraph,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlanSchema:
        task_ids = graph.topological_order()
        plan = PlanSchema(
            goal_id=goal.id,
            name=name or f"plan for {goal.description[:40]}",
            tasks=[graph.get(task_id) for task_id in task_ids],
            id=plan_id or generate_plan_id(),
            metadata=metadata or {},
        )
        plan.validate()
        return plan
