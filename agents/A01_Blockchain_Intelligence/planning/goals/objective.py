"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.goals.objective

Purpose:
    Objective management for the planning subsystem.

An objective is a measurable sub-goal derived from a parent goal.
Objectives partition a goal into verifiable milestones.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import SchemaValidationError, _now
from planning.utils.constants import Priority
from planning.utils.ids import generate_objective_id

logger = logging.getLogger("a01.planning.goals")


class ObjectiveError(Exception):
    """
    Base class for objective failures.
    """


class ObjectiveNotFoundError(ObjectiveError):
    """
    Raised when an objective does not exist.
    """


@dataclass(slots=True)
class Objective:
    """
    Measurable milestone derived from a parent goal.

    Fields:
        * Identifier, goal, and description
        * Measurable target
        * Priority and metadata
        * Timestamps
    """

    goal_id: str
    description: str
    target: Any = None
    id: str = field(default_factory=generate_objective_id)
    priority: Priority = Priority.NORMAL
    completed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """Validate the objective contract."""
        if not self.goal_id or not self.goal_id.strip():
            raise SchemaValidationError("objective.goal_id must be non-empty.")

        if not self.description or not self.description.strip():
            raise SchemaValidationError("objective.description must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("objective.id must be non-empty.")

        if self.priority not in Priority:
            raise SchemaValidationError(f"invalid priority: {self.priority!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "description": self.description,
            "target": self.target,
            "priority": self.priority.value,
            "completed": self.completed,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Objective":
        try:
            objective = cls(
                goal_id=str(payload["goal_id"]),
                description=str(payload["description"]),
                target=payload.get("target"),
                id=str(payload.get("id", generate_objective_id())),
                priority=Priority(int(payload.get("priority", Priority.NORMAL.value))),
                completed=bool(payload.get("completed", False)),
                metadata=dict(payload.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid objective payload: {exc}") from exc
        objective.validate()
        return objective

    def __repr__(self) -> str:
        return f"Objective(id={self.id!r}, completed={self.completed!r})"


class ObjectiveManager:
    """
    In-memory manager for goals-derived objectives.

    Responsibilities:
        * Objective CRUD
        * Filtering by goal
        * Completion tracking
    """

    def __init__(self) -> None:
        self._objectives: dict[str, Objective] = {}
        self._lock = asyncio.Lock()

    @property
    def objectives(self) -> dict[str, Objective]:
        """Read-only view of managed objectives."""
        return dict(self._objectives)

    async def create(
        self,
        goal_id: str,
        description: str,
        *,
        target: Any = None,
        priority: Priority = Priority.NORMAL,
        metadata: dict[str, Any] | None = None,
        objective_id: str | None = None,
    ) -> Objective:
        """Create and register an objective for a goal."""
        objective = Objective(
            goal_id=goal_id,
            description=description,
            target=target,
            priority=priority,
            metadata=metadata or {},
            id=objective_id or generate_objective_id(),
        )
        objective.validate()

        async with self._lock:
            if objective.id in self._objectives:
                raise ObjectiveError(f"objective already exists: {objective.id}")
            self._objectives[objective.id] = objective

        logger.info("objective created: %s", objective.id)
        return objective

    async def get(self, objective_id: str) -> Objective:
        """Return an objective by id."""
        objective = self._objectives.get(objective_id)

        if objective is None:
            raise ObjectiveNotFoundError(f"objective not found: {objective_id}")

        return objective

    async def list_for_goal(self, goal_id: str) -> list[Objective]:
        """Return all objectives attached to a goal."""
        return [
            objective
            for objective in self._objectives.values()
            if objective.goal_id == goal_id
        ]

    async def mark_completed(self, objective_id: str) -> Objective:
        """Mark an objective as completed."""
        objective = await self.get(objective_id)
        objective.completed = True
        logger.info("objective completed: %s", objective_id)
        return objective

    async def delete(self, objective_id: str) -> None:
        """Remove an objective from the manager."""
        async with self._lock:
            if objective_id not in self._objectives:
                raise ObjectiveNotFoundError(f"objective not found: {objective_id}")
            del self._objectives[objective_id]

        logger.info("objective deleted: %s", objective_id)

    async def clear(self) -> None:
        """Remove all objectives."""
        async with self._lock:
            self._objectives.clear()

        logger.info("objectives cleared")

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return serializable snapshots of all objectives."""
        return [objective.to_dict() for objective in self._objectives.values()]

    async def restore(self, snapshots: Iterable[dict[str, Any]]) -> int:
        """Restore objectives from serialized snapshots."""
        restored = 0

        async with self._lock:
            for snapshot in snapshots:
                try:
                    objective = Objective.from_dict(snapshot)
                except SchemaValidationError:
                    continue

                self._objectives[objective.id] = objective
                restored += 1

        logger.info("objectives restored: %d", restored)
        return restored
