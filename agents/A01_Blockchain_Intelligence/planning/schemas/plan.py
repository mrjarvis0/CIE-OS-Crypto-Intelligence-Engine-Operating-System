"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.schemas.plan

Purpose:
    Canonical data model for a plan.

A plan is a structured, validated decomposition of a goal into a
set of tasks together with execution and routing strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from planning.utils.constants import (
    MAX_TASKS_PER_PLAN,
    ExecutionMode,
    PlanningState,
    Priority,
    RoutingStrategy,
)
from planning.utils.ids import generate_plan_id
from planning.utils.validation import validate_length

from .base import (
    SchemaValidationError,
    _coerce_datetime,
    _now,
    _to_iso,
)
from .goal import GoalSchema
from .task import TaskSchema


@dataclass(slots=True)
class PlanSchema:
    """
    Canonical plan data model.

    Fields:
        * Identifier, name, and goal association
        * Tasks and their order
        * Execution and routing strategy
        * State and priority
        * Timestamps
    """

    goal_id: str
    name: str
    tasks: list[TaskSchema] = field(default_factory=list)
    description: str = ""
    id: str = field(default_factory=generate_plan_id)
    state: PlanningState = PlanningState.CREATED
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    routing_strategy: RoutingStrategy = RoutingStrategy.FIRST_MATCH
    priority: Priority = Priority.NORMAL
    goal: GoalSchema | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.goal_id or not self.goal_id.strip():
            raise SchemaValidationError("plan.goal_id must be non-empty.")

        if not self.name or not self.name.strip():
            raise SchemaValidationError("plan.name must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("plan.id must be non-empty.")

        if self.state not in PlanningState:
            raise SchemaValidationError(f"invalid plan state: {self.state!r}")

        if self.execution_mode not in ExecutionMode:
            raise SchemaValidationError(f"invalid execution mode: {self.execution_mode!r}")

        if self.routing_strategy not in RoutingStrategy:
            raise SchemaValidationError(
                f"invalid routing strategy: {self.routing_strategy!r}"
            )

        result = validate_length(
            self.tasks,
            max_length=MAX_TASKS_PER_PLAN,
            name="plan.tasks",
        )

        if not result.valid:
            raise SchemaValidationError(result.error_message)

        task_ids: set[str] = set()

        for task in self.tasks:
            task.validate()

            if task.id in task_ids:
                raise SchemaValidationError(f"duplicate task id: {task.id}")
            task_ids.add(task.id)

    def touch(self) -> None:
        """Refresh the updated_at timestamp."""
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "name": self.name,
            "description": self.description,
            "tasks": [task.to_dict() for task in self.tasks],
            "state": self.state.value,
            "execution_mode": self.execution_mode.value,
            "routing_strategy": self.routing_strategy.value,
            "priority": self.priority.value,
            "goal": self.goal.to_dict() if self.goal is not None else None,
            "metadata": dict(self.metadata),
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanSchema":
        try:
            goal_payload = payload.get("goal")
            schema = cls(
                goal_id=str(payload["goal_id"]),
                name=str(payload["name"]),
                tasks=[
                    TaskSchema.from_dict(item)
                    for item in payload.get("tasks", [])
                ],
                description=str(payload.get("description", "")),
                id=str(payload.get("id", generate_plan_id())),
                state=PlanningState(
                    str(payload.get("state", PlanningState.CREATED.value))
                ),
                execution_mode=ExecutionMode(
                    str(payload.get("execution_mode", ExecutionMode.SEQUENTIAL.value))
                ),
                routing_strategy=RoutingStrategy(
                    str(
                        payload.get(
                            "routing_strategy",
                            RoutingStrategy.FIRST_MATCH.value,
                        )
                    )
                ),
                priority=Priority(int(payload.get("priority", Priority.NORMAL.value))),
                goal=GoalSchema.from_dict(goal_payload) if goal_payload else None,
                metadata=dict(payload.get("metadata", {})),
                created_at=_coerce_datetime(
                    payload.get("created_at") or _now(), "created_at"
                ),
                updated_at=_coerce_datetime(
                    payload.get("updated_at") or _now(), "updated_at"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid plan payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"PlanSchema(id={self.id!r}, tasks={len(self.tasks)})"
