"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.schemas.task

Purpose:
    Canonical data model for a planning task.

A task is a unit of work derived from a goal during decomposition.
It carries dependency, retry, timeout, routing, and result metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from planning.utils.constants import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    MAX_RETRY,
    Priority,
    RetryPolicy,
    TaskStatus,
)
from planning.utils.ids import generate_task_id

from .base import (
    SchemaValidationError,
    _coerce_datetime,
    _now,
    _to_iso,
)


@dataclass(slots=True)
class TaskSchema:
    """
    Canonical task data model.

    Fields:
        * Identifier and description
        * Plan and goal association
        * Dependencies and priority
        * Retry, timeout, and routing settings
        * Result and error state
        * Timestamps
    """

    name: str
    description: str = ""
    plan_id: str | None = None
    goal_id: str | None = None
    dependencies: list[str] = field(default_factory=list)
    id: str = field(default_factory=generate_task_id)
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.NORMAL
    retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL
    max_retries: int = MAX_RETRY
    timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS
    tool: str | None = None
    input_data: Any = None
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.name or not self.name.strip():
            raise SchemaValidationError("task name must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("task id must be non-empty.")

        if self.status not in TaskStatus:
            raise SchemaValidationError(f"invalid task status: {self.status!r}")

        if self.priority not in Priority:
            raise SchemaValidationError(f"invalid priority: {self.priority!r}")

        if self.retry_policy not in RetryPolicy:
            raise SchemaValidationError(f"invalid retry policy: {self.retry_policy!r}")

        if self.max_retries < 0:
            raise SchemaValidationError("max_retries must be non-negative.")

        if self.timeout_seconds <= 0:
            raise SchemaValidationError("timeout_seconds must be positive.")

        if self.id in self.dependencies:
            raise SchemaValidationError("task cannot depend on itself.")

    def touch(self) -> None:
        """Refresh the updated_at timestamp."""
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "dependencies": list(self.dependencies),
            "status": self.status.value,
            "priority": self.priority.value,
            "retry_policy": self.retry_policy.value,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "tool": self.tool,
            "input_data": self.input_data,
            "result": self.result,
            "error": self.error,
            "metadata": dict(self.metadata),
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskSchema":
        try:
            schema = cls(
                name=str(payload["name"]),
                description=str(payload.get("description", "")),
                plan_id=payload.get("plan_id"),
                goal_id=payload.get("goal_id"),
                dependencies=list(payload.get("dependencies", [])),
                id=str(payload.get("id", generate_task_id())),
                status=TaskStatus(str(payload.get("status", TaskStatus.PENDING.value))),
                priority=Priority(int(payload.get("priority", Priority.NORMAL.value))),
                retry_policy=RetryPolicy(
                    str(payload.get("retry_policy", RetryPolicy.EXPONENTIAL.value))
                ),
                max_retries=int(payload.get("max_retries", MAX_RETRY)),
                timeout_seconds=float(
                    payload.get("timeout_seconds", DEFAULT_TASK_TIMEOUT_SECONDS)
                ),
                tool=payload.get("tool"),
                input_data=payload.get("input_data"),
                result=payload.get("result"),
                error=payload.get("error"),
                metadata=dict(payload.get("metadata", {})),
                created_at=_coerce_datetime(
                    payload.get("created_at") or _now(), "created_at"
                ),
                updated_at=_coerce_datetime(
                    payload.get("updated_at") or _now(), "updated_at"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid task payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"TaskSchema(id={self.id!r}, status={self.status.value!r})"
