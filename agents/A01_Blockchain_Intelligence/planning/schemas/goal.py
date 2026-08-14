"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.schemas.goal

Purpose:
    Canonical data model for a planning goal.

A goal describes intent at a high level: what the user wants to
achieve, under what constraints, and how success is measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from planning.utils.constants import GoalStatus, Priority, MAX_DEPTH
from planning.utils.ids import generate_goal_id

from .base import (
    SchemaValidationError,
    _coerce_datetime,
    _now,
    _to_iso,
)


@dataclass(slots=True)
class GoalSchema:
    """
    Canonical goal data model.

    Fields:
        * Identifier and description
        * Objectives and constraints
        * Success criteria and status
        * Priority and hierarchy
        * Timestamps
    """

    description: str
    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    id: str = field(default_factory=generate_goal_id)
    status: GoalStatus = GoalStatus.NEW
    priority: Priority = Priority.NORMAL
    parent_id: str | None = None
    sub_goal_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.description or not self.description.strip():
            raise SchemaValidationError("goal description must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("goal id must be non-empty.")

        if self.status not in GoalStatus:
            raise SchemaValidationError(f"invalid goal status: {self.status!r}")

        if self.priority not in Priority:
            raise SchemaValidationError(f"invalid priority: {self.priority!r}")

        if len(self.sub_goal_ids) > MAX_DEPTH:
            raise SchemaValidationError(
                f"goal hierarchy exceeds max depth of {MAX_DEPTH}"
            )

    def touch(self) -> None:
        """Refresh the updated_at timestamp."""
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "status": self.status.value,
            "priority": self.priority.value,
            "parent_id": self.parent_id,
            "sub_goal_ids": list(self.sub_goal_ids),
            "metadata": dict(self.metadata),
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalSchema":
        try:
            schema = cls(
                description=str(payload["description"]),
                objective=str(payload.get("objective", "")),
                constraints=list(payload.get("constraints", [])),
                acceptance_criteria=list(payload.get("acceptance_criteria", [])),
                id=str(payload.get("id", generate_goal_id())),
                status=GoalStatus(str(payload.get("status", GoalStatus.NEW.value))),
                priority=Priority(int(payload.get("priority", Priority.NORMAL.value))),
                parent_id=payload.get("parent_id"),
                sub_goal_ids=list(payload.get("sub_goal_ids", [])),
                metadata=dict(payload.get("metadata", {})),
                created_at=_coerce_datetime(
                    payload.get("created_at") or _now(), "created_at"
                ),
                updated_at=_coerce_datetime(
                    payload.get("updated_at") or _now(), "updated_at"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid goal payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"GoalSchema(id={self.id!r}, status={self.status.value!r})"
