"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.goals.assumptions

Purpose:
    Assumption tracking for the planning subsystem.

Assumptions capture beliefs the planner relies on while decomposing
a goal, along with confidence and verification state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import SchemaValidationError, _now
from planning.utils.ids import generate_objective_id

logger = logging.getLogger("a01.planning.goals")


class AssumptionError(Exception):
    """
    Base class for assumption failures.
    """


class AssumptionNotFoundError(AssumptionError):
    """
    Raised when an assumption does not exist.
    """


@dataclass(slots=True)
class Assumption:
    """
    A belief the plan depends on.

    Fields:
        * Identifier and owning goal
        * Statement and confidence (0.0 - 1.0)
        * Verification state and note
        * Timestamps
    """

    goal_id: str
    statement: str
    confidence: float = 0.5
    verified: bool = False
    note: str = ""
    id: str = field(default_factory=generate_objective_id)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """Validate the assumption contract."""
        if not self.goal_id or not self.goal_id.strip():
            raise SchemaValidationError("assumption.goal_id must be non-empty.")

        if not self.statement or not self.statement.strip():
            raise SchemaValidationError("assumption.statement must be non-empty.")

        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaValidationError("assumption.confidence must be in [0.0, 1.0].")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("assumption.id must be non-empty.")

    def touch(self) -> None:
        """Refresh the updated_at timestamp."""
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "statement": self.statement,
            "confidence": self.confidence,
            "verified": self.verified,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Assumption":
        try:
            assumption = cls(
                goal_id=str(payload["goal_id"]),
                statement=str(payload["statement"]),
                confidence=float(payload.get("confidence", 0.5)),
                verified=bool(payload.get("verified", False)),
                note=str(payload.get("note", "")),
                id=str(payload.get("id", generate_objective_id())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid assumption payload: {exc}") from exc
        assumption.validate()
        return assumption

    def __repr__(self) -> str:
        return f"Assumption(id={self.id!r}, verified={self.verified!r})"


class AssumptionManager:
    """
    In-memory manager for goal assumptions.

    Responsibilities:
        * Assumption CRUD
        * Confidence and verification tracking
    """

    def __init__(self) -> None:
        self._assumptions: dict[str, Assumption] = {}
        self._lock = asyncio.Lock()

    @property
    def assumptions(self) -> dict[str, Assumption]:
        """Read-only view of managed assumptions."""
        return dict(self._assumptions)

    async def create(
        self,
        goal_id: str,
        statement: str,
        *,
        confidence: float = 0.5,
        note: str = "",
        assumption_id: str | None = None,
    ) -> Assumption:
        """Create and register an assumption for a goal."""
        assumption = Assumption(
            goal_id=goal_id,
            statement=statement,
            confidence=confidence,
            note=note,
            id=assumption_id or generate_objective_id(),
        )
        assumption.validate()

        async with self._lock:
            if assumption.id in self._assumptions:
                raise AssumptionError(f"assumption already exists: {assumption.id}")
            self._assumptions[assumption.id] = assumption

        logger.info("assumption created: %s", assumption.id)
        return assumption

    async def get(self, assumption_id: str) -> Assumption:
        """Return an assumption by id."""
        assumption = self._assumptions.get(assumption_id)

        if assumption is None:
            raise AssumptionNotFoundError(f"assumption not found: {assumption_id}")

        return assumption

    async def list_for_goal(self, goal_id: str) -> list[Assumption]:
        """Return all assumptions attached to a goal."""
        return [
            assumption
            for assumption in self._assumptions.values()
            if assumption.goal_id == goal_id
        ]

    async def update(
        self,
        assumption_id: str,
        *,
        confidence: float | None = None,
        verified: bool | None = None,
        note: str | None = None,
    ) -> Assumption:
        """Update mutable fields on an assumption."""
        assumption = await self.get(assumption_id)

        if confidence is not None:
            assumption.confidence = confidence
        if verified is not None:
            assumption.verified = verified
        if note is not None:
            assumption.note = note

        assumption.validate()
        assumption.touch()
        logger.info("assumption updated: %s", assumption_id)
        return assumption

    async def verify(self, assumption_id: str, note: str = "") -> Assumption:
        """Mark an assumption as verified."""
        return await self.update(
            assumption_id,
            verified=True,
            note=note or "verified",
        )

    async def delete(self, assumption_id: str) -> None:
        """Remove an assumption from the manager."""
        async with self._lock:
            if assumption_id not in self._assumptions:
                raise AssumptionNotFoundError(f"assumption not found: {assumption_id}")
            del self._assumptions[assumption_id]

        logger.info("assumption deleted: %s", assumption_id)

    async def clear(self) -> None:
        """Remove all assumptions."""
        async with self._lock:
            self._assumptions.clear()

        logger.info("assumptions cleared")

    async def unverified(self, goal_id: str | None = None) -> list[Assumption]:
        """Return assumptions that are not yet verified."""
        assumptions = (
            await self.list_for_goal(goal_id)
            if goal_id
            else list(self._assumptions.values())
        )
        return [assumption for assumption in assumptions if not assumption.verified]
