"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.execution.recovery

Purpose:
    Recovery logic for the planning subsystem.

Resumes plan execution after an interruption using the most recent
checkpoint, skipping already-succeeded tasks.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.schemas import TaskSchema
from planning.utils.constants import TaskStatus

from .checkpoint import CheckpointManager

logger = logging.getLogger("a01.planning.execution")


class RecoveryResult:
    """
    Outcome of a recovery attempt.

    Fields:
        * Checkpoint used (if any)
        * Tasks to resume
        * Tasks skipped as already succeeded
        * Number of previously failed tasks
    """

    def __init__(
        self,
        *,
        resumed: list[TaskSchema] | None = None,
        skipped: list[TaskSchema] | None = None,
        checkpoint_payload: dict[str, Any] | None = None,
    ) -> None:
        self.resumed = list(resumed or [])
        self.skipped = list(skipped or [])
        self.checkpoint_payload = checkpoint_payload

    @property
    def skipped_count(self) -> int:
        """Number of skipped tasks."""
        return len(self.skipped)

    @property
    def resumed_count(self) -> int:
        """Number of tasks to resume."""
        return len(self.resumed)


class RecoveryService:
    """
    Resumes plan execution from the latest checkpoint.

    Responsibilities:
        * Loading the latest checkpoint
        * Filtering out already-succeeded tasks
        * Producing a recovery plan
    """

    def __init__(
        self,
        checkpoints: CheckpointManager,
    ) -> None:
        self._checkpoints = checkpoints

    @property
    def checkpoints(self) -> CheckpointManager:
        """The checkpoint manager backing this service."""
        return self._checkpoints

    async def recover(
        self,
        plan_id: str,
        tasks: list[TaskSchema],
    ) -> RecoveryResult:
        """
        Compute the set of tasks to resume for a plan.

        Parameters
        ----------
        plan_id
            The plan being recovered.
        tasks
            The full ordered task list for the plan.

        Returns
        -------
        RecoveryResult
            Tasks to resume, tasks skipped, and checkpoint payload.
        """

        payload = await self._checkpoints.restore(plan_id)
        resumed: list[TaskSchema] = []
        skipped: list[TaskSchema] = []

        for task in tasks:
            if task.status == TaskStatus.SUCCEEDED:
                skipped.append(task)
                continue

            resumed.append(task)

        logger.info(
            "recovery for plan %s: %d to resume, %d skipped",
            plan_id,
            len(resumed),
            len(skipped),
        )
        return RecoveryResult(
            resumed=resumed,
            skipped=skipped,
            checkpoint_payload=payload,
        )
