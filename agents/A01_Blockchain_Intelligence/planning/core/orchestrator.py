"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.orchestrator

Purpose:
    Top-level orchestration for the planning subsystem.

Provides the primary public entry point for running a goal through
the planning pipeline, wrapping the coordinator with goal lifecycle
and event emission.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.schemas import GoalSchema
from planning.utils.constants import GoalStatus, PlanningState

from .context import PlanningContext
from .coordinator import Coordinator, PlanOutcome

logger = logging.getLogger("a01.planning.core")


class OrchestratorError(Exception):
    """
    Base class for orchestration failures.
    """


class Orchestrator:
    """
    Entry point for goal-driven planning runs.

    Responsibilities:
        * Goal status driving
        * Delegation to the coordinator
        * Event emission and result reporting
    """

    def __init__(self, context: PlanningContext) -> None:
        self._context = context
        self._coordinator = Coordinator(context)

    @property
    def coordinator(self) -> Coordinator:
        """The bound coordinator."""
        return self._coordinator

    async def run_goal(
        self,
        goal: GoalSchema,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlanOutcome:
        """
        Run a goal through planning to completion.

        The goal is marked IN_PROGRESS during the run and COMPLETED or
        FAILED afterwards, mirroring the plan outcome.
        """

        await self._set_goal_status(
            goal.id,
            [
                GoalStatus.UNDERSTOOD,
                GoalStatus.CONSTRAINED,
                GoalStatus.DECOMPOSED,
                GoalStatus.READY,
                GoalStatus.IN_PROGRESS,
            ],
        )
        outcome = await self._coordinator.run_goal(
            goal,
            plan_id=plan_id,
            name=name,
            metadata=metadata,
        )

        final_goal_status = (
            GoalStatus.COMPLETED
            if outcome.state == PlanningState.COMPLETED
            else GoalStatus.FAILED
        )
        await self._set_goal_status(goal.id, [final_goal_status])

        logger.info(
            "goal %s finished with plan state %s",
            goal.id,
            outcome.state.value,
        )
        return outcome

    async def _set_goal_status(
        self,
        goal_id: str,
        path: list[GoalStatus],
    ) -> None:
        """
        Walk a goal through a status path, applying each transition.
        """
        for status in path:
            try:
                await self._context.goals.set_status(goal_id, status)
            except Exception:
                pass
