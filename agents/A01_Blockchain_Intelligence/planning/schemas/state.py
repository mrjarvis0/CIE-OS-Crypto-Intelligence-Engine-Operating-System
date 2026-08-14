"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.schemas.state

Purpose:
    Canonical data model for plan execution state.

Tracks the lifecycle position of a plan: overall planning state,
per-task statuses, execution attempt counts, and checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from planning.utils.constants import PlanningState, TaskStatus

from .base import (
    SchemaValidationError,
    _coerce_datetime,
    _now,
    _to_iso,
)


@dataclass(slots=True)
class PlanStateSchema:
    """
    Canonical plan execution state model.

    Fields:
        * Plan identifier and lifecycle state
        * Per-task status map
        * Attempt counts and current task
        * Checkpoint and timestamp metadata
    """

    plan_id: str
    state: PlanningState = PlanningState.CREATED
    task_statuses: dict[str, TaskStatus] = field(default_factory=dict)
    attempt_counts: dict[str, int] = field(default_factory=dict)
    current_task_id: str | None = None
    last_checkpoint_id: str | None = None
    checkpoint_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.plan_id or not self.plan_id.strip():
            raise SchemaValidationError("state.plan_id must be non-empty.")

        if self.state not in PlanningState:
            raise SchemaValidationError(f"invalid plan state: {self.state!r}")

        for task_id, status in self.task_statuses.items():
            if status not in TaskStatus:
                raise SchemaValidationError(
                    f"invalid task status for {task_id!r}: {status!r}"
                )

        for task_id, count in self.attempt_counts.items():
            if count < 0:
                raise SchemaValidationError(
                    f"attempt count must be non-negative for {task_id!r}"
                )

        if self.checkpoint_count < 0:
            raise SchemaValidationError("checkpoint_count must be non-negative.")

    def touch(self) -> None:
        """Refresh the updated_at timestamp."""
        self.updated_at = _now()

    def set_task_status(self, task_id: str, status: TaskStatus) -> None:
        """Record a task status and refresh the timestamp."""
        self.task_statuses[task_id] = status
        self.touch()

    def increment_attempt(self, task_id: str) -> int:
        """Increment and return the attempt count for a task."""
        current = self.attempt_counts.get(task_id, 0)
        self.attempt_counts[task_id] = current + 1
        self.touch()
        return self.attempt_counts[task_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "state": self.state.value,
            "task_statuses": {
                task_id: status.value
                for task_id, status in self.task_statuses.items()
            },
            "attempt_counts": dict(self.attempt_counts),
            "current_task_id": self.current_task_id,
            "last_checkpoint_id": self.last_checkpoint_id,
            "checkpoint_count": self.checkpoint_count,
            "metadata": dict(self.metadata),
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanStateSchema":
        try:
            schema = cls(
                plan_id=str(payload["plan_id"]),
                state=PlanningState(
                    str(payload.get("state", PlanningState.CREATED.value))
                ),
                task_statuses={
                    str(task_id): TaskStatus(str(status))
                    for task_id, status in payload.get("task_statuses", {}).items()
                },
                attempt_counts={
                    str(task_id): int(count)
                    for task_id, count in payload.get("attempt_counts", {}).items()
                },
                current_task_id=payload.get("current_task_id"),
                last_checkpoint_id=payload.get("last_checkpoint_id"),
                checkpoint_count=int(payload.get("checkpoint_count", 0)),
                metadata=dict(payload.get("metadata", {})),
                created_at=_coerce_datetime(
                    payload.get("created_at") or _now(), "created_at"
                ),
                updated_at=_coerce_datetime(
                    payload.get("updated_at") or _now(), "updated_at"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid state payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"PlanStateSchema(plan_id={self.plan_id!r}, state={self.state.value!r})"
