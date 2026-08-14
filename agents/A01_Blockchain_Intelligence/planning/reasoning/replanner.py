"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.replanner

Purpose:
    Plan revision for the planning subsystem.

Revises an existing plan in response to failures or new feedback,
preserving succeeded work and regenerating failed tasks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas import PlanSchema, TaskSchema
from planning.schemas.base import _now
from planning.utils.constants import TaskStatus

logger = logging.getLogger("a01.planning.reasoning")


@dataclass(slots=True)
class Revision:
    """
    A single plan revision.

    Fields:
        * Task identifier and change kind
        * Change description
    """

    task_id: str
    kind: str
    description: str


@dataclass(slots=True)
class ReplanResult:
    """
    Outcome of a replanning pass.

    Fields:
        * Original plan identifier
        * Revised task list
        * Applied revisions
        * Revision timestamp
    """

    plan_id: str
    tasks: list[TaskSchema] = field(default_factory=list)
    revisions: list[Revision] = field(default_factory=list)
    revised_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_ids": [task.id for task in self.tasks],
            "revisions": [
                {
                    "task_id": revision.task_id,
                    "kind": revision.kind,
                    "description": revision.description,
                }
                for revision in self.revisions
            ],
            "revised_at": self.revised_at.isoformat(),
        }


class Replanner:
    """
    Revises plans in response to feedback.

    Responsibilities:
        * Task regeneration on failure
        * Preserving succeeded work
        * Recording revisions
    """

    def replan(
        self,
        plan: PlanSchema,
        *,
        failures: dict[str, str] | None = None,
    ) -> ReplanResult:
        """
        Revise a plan's tasks.

        Parameters
        ----------
        plan
            The plan to revise.
        failures
            Optional mapping of task id to failure reason; failed tasks
            are reset to PENDING so they run again.
        """

        failures = failures or {}
        revised: list[TaskSchema] = []
        revisions: list[Revision] = []

        for task in plan.tasks:
            failure_reason = failures.get(task.id)

            if failure_reason is not None:
                reset = self._reset_task(task, failure_reason)
                revised.append(reset)
                revisions.append(
                    Revision(
                        task.id,
                        "reset",
                        f"task reset after failure: {failure_reason}",
                    )
                )
            elif task.status == TaskStatus.SUCCEEDED:
                revised.append(task)
                revisions.append(
                    Revision(task.id, "keep", "task already succeeded")
                )
            else:
                revised.append(task)

        logger.info(
            "plan %s replanned: %d task(s), %d revision(s)",
            plan.id,
            len(revised),
            len(revisions),
        )
        return ReplanResult(
            plan_id=plan.id,
            tasks=revised,
            revisions=revisions,
        )

    @staticmethod
    def _reset_task(task: TaskSchema, reason: str) -> TaskSchema:
        task.status = TaskStatus.PENDING
        task.error = reason
        task.result = None
        task.touch()
        return task
