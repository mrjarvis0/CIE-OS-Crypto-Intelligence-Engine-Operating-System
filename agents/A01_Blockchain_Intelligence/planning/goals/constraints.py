"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.goals.constraints

Purpose:
    Constraint tracking and enforcement for the planning subsystem.

Constraints are hard or soft limits a goal must respect, such as
budgets, deadlines, permitted tools, or forbidden chains.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import SchemaValidationError, _now
from planning.utils.ids import generate_objective_id

logger = logging.getLogger("a01.planning.goals")

ConstraintCheck = Callable[[dict[str, Any]], str | None]


class ConstraintError(Exception):
    """
    Base class for constraint failures.
    """


class ConstraintNotFoundError(ConstraintError):
    """
    Raised when a constraint does not exist.
    """


@dataclass(slots=True)
class Constraint:
    """
    A limit the planner must honor.

    Fields:
        * Identifier and owning goal
        * Human-readable rule
        * Optional predicate returning an error message
        * Whether the constraint is hard or soft
        * Timestamps
    """

    goal_id: str
    rule: str
    predicate: ConstraintCheck | None = None
    hard: bool = True
    id: str = field(default_factory=generate_objective_id)
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """Validate the constraint contract."""
        if not self.goal_id or not self.goal_id.strip():
            raise SchemaValidationError("constraint.goal_id must be non-empty.")

        if not self.rule or not self.rule.strip():
            raise SchemaValidationError("constraint.rule must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("constraint.id must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "rule": self.rule,
            "hard": self.hard,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Constraint":
        try:
            constraint = cls(
                goal_id=str(payload["goal_id"]),
                rule=str(payload["rule"]),
                hard=bool(payload.get("hard", True)),
                id=str(payload.get("id", generate_objective_id())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid constraint payload: {exc}") from exc
        constraint.validate()
        return constraint

    def __repr__(self) -> str:
        return f"Constraint(id={self.id!r}, hard={self.hard!r})"


@dataclass(slots=True)
class ConstraintReport:
    """
    Result of evaluating constraints against a candidate plan.

    Fields:
        * Per-constraint results
        * Aggregated violation flags
    """

    results: dict[str, str | None] = field(default_factory=dict)

    @property
    def violations(self) -> list[str]:
        return [
            message
            for message in self.results.values()
            if message is not None
        ]

    @property
    def passed(self) -> bool:
        return not self.violations


class ConstraintManager:
    """
    In-memory manager for goal constraints.

    Responsibilities:
        * Constraint CRUD
        * Constraint evaluation against candidate plans
    """

    def __init__(self) -> None:
        self._constraints: dict[str, Constraint] = {}
        self._lock = asyncio.Lock()

    @property
    def constraints(self) -> dict[str, Constraint]:
        """Read-only view of managed constraints."""
        return dict(self._constraints)

    async def create(
        self,
        goal_id: str,
        rule: str,
        *,
        predicate: ConstraintCheck | None = None,
        hard: bool = True,
        constraint_id: str | None = None,
    ) -> Constraint:
        """Create and register a constraint for a goal."""
        constraint = Constraint(
            goal_id=goal_id,
            rule=rule,
            predicate=predicate,
            hard=hard,
            id=constraint_id or generate_objective_id(),
        )
        constraint.validate()

        async with self._lock:
            if constraint.id in self._constraints:
                raise ConstraintError(f"constraint already exists: {constraint.id}")
            self._constraints[constraint.id] = constraint

        logger.info("constraint created: %s", constraint.id)
        return constraint

    async def get(self, constraint_id: str) -> Constraint:
        """Return a constraint by id."""
        constraint = self._constraints.get(constraint_id)

        if constraint is None:
            raise ConstraintNotFoundError(f"constraint not found: {constraint_id}")

        return constraint

    async def list_for_goal(self, goal_id: str) -> list[Constraint]:
        """Return all constraints attached to a goal."""
        return [
            constraint
            for constraint in self._constraints.values()
            if constraint.goal_id == goal_id
        ]

    async def evaluate(
        self,
        goal_id: str,
        candidate: dict[str, Any],
    ) -> ConstraintReport:
        """
        Evaluate all constraints for a goal against a candidate.

        Constraints with no predicate pass by default.
        """

        report = ConstraintReport()
        constraints = await self.list_for_goal(goal_id)

        for constraint in constraints:
            if constraint.predicate is None:
                report.results[constraint.id] = None
                continue

            try:
                report.results[constraint.id] = constraint.predicate(candidate)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("constraint %s evaluation failed: %s", constraint.id, exc)
                report.results[constraint.id] = str(exc)

        return report

    async def delete(self, constraint_id: str) -> None:
        """Remove a constraint from the manager."""
        async with self._lock:
            if constraint_id not in self._constraints:
                raise ConstraintNotFoundError(f"constraint not found: {constraint_id}")
            del self._constraints[constraint_id]

        logger.info("constraint deleted: %s", constraint_id)

    async def clear(self) -> None:
        """Remove all constraints."""
        async with self._lock:
            self._constraints.clear()

        logger.info("constraints cleared")

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return serializable snapshots of all constraints."""
        return [constraint.to_dict() for constraint in self._constraints.values()]

    async def restore(self, snapshots: Iterable[dict[str, Any]]) -> int:
        """Restore constraints from serialized snapshots."""
        restored = 0

        async with self._lock:
            for snapshot in snapshots:
                try:
                    constraint = Constraint.from_dict(snapshot)
                except SchemaValidationError:
                    continue

                self._constraints[constraint.id] = constraint
                restored += 1

        logger.info("constraints restored: %d", restored)
        return restored
