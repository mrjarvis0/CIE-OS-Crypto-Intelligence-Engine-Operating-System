"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.schemas.execution

Purpose:
    Canonical data model for a single task execution attempt.

Captures one run of a task: lifecycle status, attempt and retry
counters, duration, result, and error information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from planning.utils.constants import (
    DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    ExecutionMode,
    ExecutionStatus,
)
from planning.utils.ids import generate_execution_id

from .base import (
    SchemaValidationError,
    _coerce_datetime,
    _now,
    _to_iso,
)


@dataclass(slots=True)
class ExecutionSchema:
    """
    Canonical task execution data model.

    Fields:
        * Identifier and task/plan association
        * Lifecycle status and mode
        * Attempt and retry counters
        * Duration, result, and error
        * Timestamps
    """

    task_id: str
    plan_id: str | None = None
    id: str = field(default_factory=generate_execution_id)
    status: ExecutionStatus = ExecutionStatus.CREATED
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    attempt: int = 1
    max_retries: int = 0
    timeout_seconds: float = DEFAULT_EXECUTION_TIMEOUT_SECONDS
    result: Any = None
    error: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.task_id or not self.task_id.strip():
            raise SchemaValidationError("execution.task_id must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("execution.id must be non-empty.")

        if self.status not in ExecutionStatus:
            raise SchemaValidationError(f"invalid execution status: {self.status!r}")

        if self.mode not in ExecutionMode:
            raise SchemaValidationError(f"invalid execution mode: {self.mode!r}")

        if self.attempt < 1:
            raise SchemaValidationError("attempt must be >= 1.")

        if self.max_retries < 0:
            raise SchemaValidationError("max_retries must be non-negative.")

        if self.timeout_seconds <= 0:
            raise SchemaValidationError("timeout_seconds must be positive.")

        if self.duration_ms is not None and self.duration_ms < 0:
            raise SchemaValidationError("duration_ms must be non-negative.")

        if self.completed_at is not None and self.started_at is None:
            raise SchemaValidationError(
                "completed_at requires started_at to be set."
            )

    def touch(self) -> None:
        """Refresh the started/completed timestamps from the status."""
        if self.status in (
            ExecutionStatus.RUNNING,
            ExecutionStatus.RETRYING,
        ):
            if self.started_at is None:
                self.started_at = _now()

        if self.status in (
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.INTERRUPTED,
            ExecutionStatus.RECOVERED,
        ):
            self.completed_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "status": self.status.value,
            "mode": self.mode.value,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
            "created_at": _to_iso(self.created_at),
            "started_at": _to_iso(self.started_at),
            "completed_at": _to_iso(self.completed_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionSchema":
        try:
            schema = cls(
                task_id=str(payload["task_id"]),
                plan_id=payload.get("plan_id"),
                id=str(payload.get("id", generate_execution_id())),
                status=ExecutionStatus(
                    str(payload.get("status", ExecutionStatus.CREATED.value))
                ),
                mode=ExecutionMode(
                    str(payload.get("mode", ExecutionMode.SEQUENTIAL.value))
                ),
                attempt=int(payload.get("attempt", 1)),
                max_retries=int(payload.get("max_retries", 0)),
                timeout_seconds=float(
                    payload.get("timeout_seconds", DEFAULT_EXECUTION_TIMEOUT_SECONDS)
                ),
                result=payload.get("result"),
                error=payload.get("error"),
                duration_ms=payload.get("duration_ms"),
                metadata=dict(payload.get("metadata", {})),
                created_at=_coerce_datetime(
                    payload.get("created_at") or _now(), "created_at"
                ),
                started_at=(
                    _coerce_datetime(payload["started_at"], "started_at")
                    if payload.get("started_at")
                    else None
                ),
                completed_at=(
                    _coerce_datetime(payload["completed_at"], "completed_at")
                    if payload.get("completed_at")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid execution payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"ExecutionSchema(id={self.id!r}, status={self.status.value!r})"
