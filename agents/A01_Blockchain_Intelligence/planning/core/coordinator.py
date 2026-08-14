"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.coordinator

Purpose:
    Plan coordination for the planning subsystem.

Drives a goal through planning, scheduling, execution, validation,
and reflection using the planner, executor, validator, and reflector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from planning.schemas import GoalSchema, PlanSchema
from planning.utils.constants import PlanningState, TaskStatus

from .context import PlanningContext
from .executor import ExecutionReport, PlanExecutor
from .lifecycle import PlanLifecycle
from .planner import Planner

logger = logging.getLogger("a01.planning.core")


@dataclass(slots=True)
class PlanOutcome:
    """
    Final outcome of a coordinated plan run.

    Fields:
        * Plan reference
        * Execution report
        * Validation verdict
        * Reflection outcome
        * Final plan state
    """

    plan: PlanSchema | None = None
    execution: ExecutionReport | None = None
    valid: bool = True
    reflection_outcome: str = ""
    state: PlanningState = PlanningState.CREATED
    details: dict[str, Any] = field(default_factory=dict)


class Coordinator:
    """
    Coordinates a full plan lifecycle.

    Responsibilities:
        * Goal to plan pipeline
        * Lifecycle state driving
        * Execution, validation, and reflection
    """

    def __init__(self, context: PlanningContext) -> None:
        self._context = context
        self._planner = Planner(context)
        self._executor = PlanExecutor(context)
        self._lifecycle = context.lifecycle

    @property
    def planner(self) -> Planner:
        """The bound planner."""
        return self._planner

    @property
    def executor(self) -> PlanExecutor:
        """The bound plan executor."""
        return self._executor

    @property
    def lifecycle(self) -> PlanLifecycle:
        """The bound lifecycle manager."""
        return self._lifecycle

    async def run_goal(
        self,
        goal: GoalSchema,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlanOutcome:
        """
        Drive a goal through the full plan pipeline.

        Returns a PlanOutcome with execution, validation, and
        reflection results.
        """

        plan = await self._planner.plan_from_goal(
            goal,
            plan_id=plan_id,
            name=name,
            metadata=metadata,
        )
        lifecycle = self._lifecycle.register(plan)

        try:
            self._lifecycle.transition(plan.id, PlanningState.PLANNING)
            self._lifecycle.transition(plan.id, PlanningState.SCHEDULED)
            self._lifecycle.transition(plan.id, PlanningState.EXECUTING)

            report = await self._executor.execute(plan)

            self._lifecycle.transition(plan.id, PlanningState.VALIDATING)
            validation = self._context.validator.validate(plan)
            self._lifecycle.transition(plan.id, PlanningState.REFLECTING)

            reflection = self._context.reflector.reflect(
                plan,
                outcomes={
                    task.id: {"success": task.status is TaskStatus.SUCCEEDED}
                    for task in plan.tasks
                },
            )

            final_state = (
                PlanningState.COMPLETED
                if validation.valid and report.all_succeeded
                else PlanningState.FAILED
            )
            self._lifecycle.transition(plan.id, final_state)

            return PlanOutcome(
                plan=plan,
                execution=report,
                valid=validation.valid,
                reflection_outcome=reflection.outcome,
                state=final_state,
                details={
                    "validation_issues": [
                        issue.message for issue in validation.issues
                    ],
                    "reflection_suggestions": reflection.suggestions,
                },
            )
        except Exception as exc:
            logger.warning("plan %s failed during coordination: %s", plan.id, exc)
            try:
                self._lifecycle.transition(plan.id, PlanningState.FAILED)
            except Exception:
                pass

            return PlanOutcome(
                plan=plan,
                valid=False,
                state=PlanningState.FAILED,
                details={"error": str(exc)},
            )
