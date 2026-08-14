"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.planner_state

Purpose:
    Plan execution state tracking for the planning subsystem.

Maintains the runtime ``PlanStateSchema`` for a plan, updating
per-task statuses, attempt counts, and the overall plan state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from planning.schemas import PlanStateSchema, TaskSchema
from planning.schemas.base import SchemaValidationError
from planning.utils.constants import PlanningState, TaskStatus
from planning.utils.ids import generate_plan_id

logger = logging.getLogger("a01.planning.tasks")


class PlannerStateError(Exception):
    """
    Base class for planner state failures.
    """


class PlannerStateNotFoundError(PlannerStateError):
    """
    Raised when no state exists for a plan.
    """


class PlannerStateManager:
    """
    Tracks runtime state for plans.

    Responsibilities:
        * Plan state creation
        * Per-task status updates
        * Attempt count tracking
        * Checkpoint bookkeeping
    """

    def __init__(self) -> None:
        self._states: dict[str, PlanStateSchema] = {}
        self._lock = asyncio.Lock()

    @property
    def states(self) -> dict[str, PlanStateSchema]:
        """Read-only view of plan states by plan id."""
        return dict(self._states)

    async def create(
        self,
        plan_id: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> PlanStateSchema:
        """Create and register a state record for a plan."""
        state = PlanStateSchema(
            plan_id=plan_id or generate_plan_id(),
            metadata=metadata or {},
        )
        state.validate()

        async with self._lock:
            if state.plan_id in self._states:
                raise PlannerStateError(f"state already exists: {state.plan_id}")
            self._states[state.plan_id] = state

        logger.info("plan state created: %s", state.plan_id)
        return state

    async def get(self, plan_id: str) -> PlanStateSchema:
        """Return the state record for a plan."""
        state = self._states.get(plan_id)

        if state is None:
            raise PlannerStateNotFoundError(f"state not found: {plan_id}")

        return state

    async def set_plan_state(self, plan_id: str, state: PlanningState) -> PlanStateSchema:
        """Update the overall planning state of a plan."""
        record = await self.get(plan_id)
        record.state = state
        record.touch()
        record.validate()
        logger.info("plan %s state -> %s", plan_id, state.value)
        return record

    async def record_task_status(
        self,
        plan_id: str,
        task_id: str,
        status: TaskStatus,
    ) -> PlanStateSchema:
        """Record a task status for a plan."""
        record = await self.get(plan_id)
        record.set_task_status(task_id, status)
        record.validate()
        return record

    async def record_attempt(
        self,
        plan_id: str,
        task_id: str,
    ) -> int:
        """Increment and return the attempt count for a task."""
        record = await self.get(plan_id)
        attempt = record.increment_attempt(task_id)
        record.validate()
        return attempt

    async def set_current_task(
        self,
        plan_id: str,
        task_id: str | None,
    ) -> PlanStateSchema:
        """Set the currently executing task for a plan."""
        record = await self.get(plan_id)
        record.current_task_id = task_id
        record.touch()
        return record

    async def set_checkpoint(
        self,
        plan_id: str,
        checkpoint_id: str,
    ) -> PlanStateSchema:
        """Record the latest checkpoint for a plan."""
        record = await self.get(plan_id)
        record.last_checkpoint_id = checkpoint_id
        record.checkpoint_count += 1
        record.touch()
        return record

    async def apply_task(
        self,
        task: TaskSchema,
        *,
        plan_id: str | None = None,
    ) -> PlanStateSchema:
        """Synchronize a task's status and attempts into plan state."""
        target_plan = plan_id or task.plan_id

        if target_plan is None:
            raise PlannerStateError("cannot apply task without a plan_id")

        record = await self.get(target_plan)
        record.set_task_status(task.id, task.status)
        record.touch()
        return record

    async def delete(self, plan_id: str) -> None:
        """Remove the state record for a plan."""
        async with self._lock:
            if plan_id not in self._states:
                raise PlannerStateNotFoundError(f"state not found: {plan_id}")
            del self._states[plan_id]

        logger.info("plan state deleted: %s", plan_id)

    async def clear(self) -> None:
        """Remove all plan states."""
        async with self._lock:
            self._states.clear()

        logger.info("plan states cleared")

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return serializable snapshots of all plan states."""
        return [state.to_dict() for state in self._states.values()]

    async def restore(self, snapshots: list[dict[str, Any]]) -> int:
        """Restore plan states from serialized snapshots."""
        restored = 0

        async with self._lock:
            for snapshot in snapshots:
                try:
                    state = PlanStateSchema.from_dict(snapshot)
                except SchemaValidationError:
                    continue

                self._states[state.plan_id] = state
                restored += 1

        logger.info("plan states restored: %d", restored)
        return restored
