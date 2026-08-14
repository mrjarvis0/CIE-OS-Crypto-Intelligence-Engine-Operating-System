"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.goals.goal

Purpose:
    Goal lifecycle management for the planning subsystem.

Owns goal records, enforces status transitions, and provides
create / read / update / delete operations over ``GoalSchema``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from planning.schemas import GoalSchema
from planning.schemas.base import SchemaValidationError
from planning.utils.constants import GoalStatus, Priority
from planning.utils.helpers import iso_now
from planning.utils.ids import generate_goal_id

logger = logging.getLogger("a01.planning.goals")


class GoalError(Exception):
    """
    Base class for goal lifecycle failures.
    """


class GoalNotFoundError(GoalError):
    """
    Raised when a goal does not exist.
    """


class InvalidGoalTransitionError(GoalError):
    """
    Raised when a goal status transition is not allowed.
    """


# Allowed status transitions for a goal.
_GOAL_TRANSITIONS: dict[GoalStatus, set[GoalStatus]] = {
    GoalStatus.NEW: {
        GoalStatus.UNDERSTOOD,
        GoalStatus.CANCELLED,
        GoalStatus.FAILED,
    },
    GoalStatus.UNDERSTOOD: {
        GoalStatus.CONSTRAINED,
        GoalStatus.CANCELLED,
        GoalStatus.FAILED,
    },
    GoalStatus.CONSTRAINED: {
        GoalStatus.DECOMPOSED,
        GoalStatus.CANCELLED,
        GoalStatus.FAILED,
    },
    GoalStatus.DECOMPOSED: {
        GoalStatus.READY,
        GoalStatus.CANCELLED,
        GoalStatus.FAILED,
    },
    GoalStatus.READY: {
        GoalStatus.IN_PROGRESS,
        GoalStatus.CANCELLED,
        GoalStatus.FAILED,
    },
    GoalStatus.IN_PROGRESS: {
        GoalStatus.COMPLETED,
        GoalStatus.FAILED,
        GoalStatus.CANCELLED,
    },
    GoalStatus.COMPLETED: set(),
    GoalStatus.FAILED: set(),
    GoalStatus.CANCELLED: set(),
}


class GoalManager:
    """
    In-memory lifecycle manager for planning goals.

    Responsibilities:
        * Goal CRUD
        * Status transition enforcement
        * Goal retrieval and listing
    """

    def __init__(self) -> None:
        self._goals: dict[str, GoalSchema] = {}
        self._lock = asyncio.Lock()

    @property
    def goals(self) -> dict[str, GoalSchema]:
        """Read-only view of managed goals by id."""
        return dict(self._goals)

    async def create(
        self,
        description: str,
        *,
        objective: str = "",
        constraints: Iterable[str] = (),
        acceptance_criteria: Iterable[str] = (),
        priority: Any = None,
        metadata: dict[str, Any] | None = None,
        goal_id: str | None = None,
    ) -> GoalSchema:
        """
        Create and register a new goal.

        Raises
        ------
        SchemaValidationError
            When the goal contract is invalid.
        """

        schema = GoalSchema(
            description=description,
            objective=objective,
            constraints=list(constraints),
            acceptance_criteria=list(acceptance_criteria),
            priority=priority if priority is not None else Priority.NORMAL,
            metadata=metadata or {},
            id=goal_id or generate_goal_id(),
        )
        schema.validate()

        async with self._lock:
            if schema.id in self._goals:
                raise GoalError(f"goal already exists: {schema.id}")
            self._goals[schema.id] = schema

        logger.info("goal created: %s", schema.id)
        return schema

    async def get(self, goal_id: str) -> GoalSchema:
        """Return a goal by id."""
        goal = self._goals.get(goal_id)

        if goal is None:
            raise GoalNotFoundError(f"goal not found: {goal_id}")

        return goal

    async def get_many(self, goal_ids: Iterable[str]) -> list[GoalSchema]:
        """Return multiple goals by id, preserving order."""
        return [await self.get(goal_id) for goal_id in goal_ids]

    async def list(
        self,
        *,
        status: GoalStatus | None = None,
    ) -> list[GoalSchema]:
        """Return all goals, optionally filtered by status."""
        goals = list(self._goals.values())

        if status is not None:
            goals = [goal for goal in goals if goal.status == status]

        return goals

    async def update(self, goal_id: str, **changes: Any) -> GoalSchema:
        """Update mutable fields on an existing goal."""
        goal = await self.get(goal_id)
        mutable = {
            "description",
            "objective",
            "constraints",
            "acceptance_criteria",
            "priority",
            "metadata",
        }

        for key, value in changes.items():
            if key not in mutable:
                raise GoalError(f"cannot update read-only field: {key}")
            setattr(goal, key, value)

        goal.touch()
        goal.validate()
        logger.info("goal updated: %s", goal_id)
        return goal

    async def delete(self, goal_id: str) -> None:
        """Remove a goal from the manager."""
        async with self._lock:
            if goal_id not in self._goals:
                raise GoalNotFoundError(f"goal not found: {goal_id}")
            del self._goals[goal_id]

        logger.info("goal deleted: %s", goal_id)

    async def set_status(self, goal_id: str, status: GoalStatus) -> GoalSchema:
        """
        Transition a goal to a new status.

        Raises
        ------
        InvalidGoalTransitionError
            When the transition is not allowed.
        """

        goal = await self.get(goal_id)

        if status == goal.status:
            return goal

        allowed = _GOAL_TRANSITIONS.get(goal.status, set())

        if status not in allowed:
            raise InvalidGoalTransitionError(
                f"invalid transition: {goal.status.value} -> {status.value}"
            )

        goal.status = status
        goal.touch()
        goal.validate()
        logger.info("goal %s transitioned: %s", goal_id, status.value)
        return goal

    async def attach_sub_goal(self, goal_id: str, sub_goal_id: str) -> GoalSchema:
        """Register a sub-goal under a parent goal."""
        goal = await self.get(goal_id)
        sub_goal = await self.get(sub_goal_id)

        if sub_goal.id in goal.sub_goal_ids:
            return goal

        if sub_goal.parent_id is not None:
            raise GoalError(f"sub-goal already has parent: {sub_goal.id}")

        goal.sub_goal_ids.append(sub_goal.id)
        sub_goal.parent_id = goal.id
        goal.touch()
        sub_goal.touch()
        goal.validate()
        logger.info("sub-goal %s attached to %s", sub_goal_id, goal_id)
        return goal

    async def clear(self) -> None:
        """Remove all managed goals."""
        async with self._lock:
            self._goals.clear()

        logger.info("goals cleared")

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return serializable snapshots of all goals."""
        return [goal.to_dict() for goal in self._goals.values()]

    async def restore(self, snapshots: Iterable[dict[str, Any]]) -> int:
        """Restore goals from serialized snapshots."""
        restored = 0

        async with self._lock:
            for snapshot in snapshots:
                try:
                    schema = GoalSchema.from_dict(snapshot)
                except SchemaValidationError:
                    continue

                self._goals[schema.id] = schema
                restored += 1

        logger.info("goals restored: %d", restored)
        return restored

    def to_dict(self, goal_id: str) -> dict[str, Any]:
        """Serialize a single goal. Exists for API parity."""
        return self._goals[goal_id].to_dict()


def now_iso() -> str:
    """Return the current UTC time as ISO-8601."""
    return iso_now()
