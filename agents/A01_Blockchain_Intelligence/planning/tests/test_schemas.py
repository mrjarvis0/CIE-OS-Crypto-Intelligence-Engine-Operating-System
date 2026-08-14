"""
Tests for planning.schemas.

Covers schema validation, dict serialization round-trips, and the
schema error hierarchy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.schemas import (
    SCHEMA_VERSION,
    ExecutionSchema,
    GoalSchema,
    PlanSchema,
    PlanStateSchema,
    SchemaSerializationError,
    SchemaValidationError,
    TaskSchema,
)
from planning.utils.constants import (
    ExecutionStatus,
    GoalStatus,
    PlanningState,
    Priority,
    RetryPolicy,
    TaskStatus,
)
from planning.tests import check, summary


def test_schema_version() -> None:
    check("schema version", SCHEMA_VERSION == 1)
    check("error hierarchy", issubclass(SchemaValidationError, Exception))
    check("serialization error", issubclass(SchemaSerializationError, Exception))


def test_goal_schema() -> None:
    goal = GoalSchema(
        description="build an indexer",
        objective="index the chain",
        constraints=["no RPC spam"],
        acceptance_criteria=["index produced"],
        priority=Priority.HIGH,
    )
    goal.validate()
    check("goal default status", goal.status == GoalStatus.NEW)
    check("goal id prefixed", goal.id.startswith("goal_"))

    payload = goal.to_dict()
    restored = GoalSchema.from_dict(payload)
    check("goal round trip", restored.description == goal.description)
    check("goal round trip status", restored.status == GoalStatus.NEW)
    check("goal round trip constraints", restored.constraints == ["no RPC spam"])

    try:
        GoalSchema(description="").validate()
        raise AssertionError("expected validation error")
    except SchemaValidationError:
        pass


def test_task_schema() -> None:
    task = TaskSchema(
        name="fetch blocks",
        description="pull recent blocks",
        dependencies=[],
        max_retries=2,
        timeout_seconds=10.0,
    )
    task.validate()
    check("task default status", task.status == TaskStatus.PENDING)
    check("task default retry policy", task.retry_policy == RetryPolicy.EXPONENTIAL)

    payload = task.to_dict()
    restored = TaskSchema.from_dict(payload)
    check("task round trip name", restored.name == "fetch blocks")
    check("task round trip retries", restored.max_retries == 2)
    check("task round trip timeout", restored.timeout_seconds == 10.0)

    try:
        TaskSchema(name="", description="").validate()
        raise AssertionError("expected validation error")
    except SchemaValidationError:
        pass

    self_dep = TaskSchema(name="x", description="d", dependencies=["x"])
    try:
        self_dep.id = "x"
        self_dep.validate()
        raise AssertionError("expected self-dependency error")
    except SchemaValidationError:
        pass


def test_plan_schema() -> None:
    tasks = [
        TaskSchema(name="a", description="d"),
        TaskSchema(name="b", description="d"),
    ]
    plan = PlanSchema(goal_id="goal-1", name="pipeline", tasks=tasks)
    plan.validate()
    check("plan default state", plan.state == PlanningState.CREATED)
    check("plan task count", len(plan.tasks) == 2)

    payload = plan.to_dict()
    restored = PlanSchema.from_dict(payload)
    check("plan round trip name", restored.name == "pipeline")
    check("plan round trip tasks", len(restored.tasks) == 2)

    try:
        PlanSchema(goal_id="", name="p").validate()
        raise AssertionError("expected validation error")
    except SchemaValidationError:
        pass


def test_plan_state_schema() -> None:
    state = PlanStateSchema(plan_id="plan-1")
    state.set_task_status("task-1", TaskStatus.SUCCEEDED)
    state.increment_attempt("task-2")
    check("plan state task status", state.task_statuses["task-1"] == TaskStatus.SUCCEEDED)
    check("plan state attempt", state.attempt_counts["task-2"] == 1)

    payload = state.to_dict()
    restored = PlanStateSchema.from_dict(payload)
    check("state round trip status", restored.task_statuses["task-1"] == TaskStatus.SUCCEEDED)
    check("state round trip attempt", restored.attempt_counts["task-2"] == 1)


def test_execution_schema() -> None:
    record = ExecutionSchema(task_id="task-1", plan_id="plan-1")
    check("execution default status", record.status == ExecutionStatus.CREATED)

    payload = record.to_dict()
    restored = ExecutionSchema.from_dict(payload)
    check("execution round trip task", restored.task_id == "task-1")
    check("execution round trip status", restored.status == ExecutionStatus.CREATED)

    try:
        ExecutionSchema(task_id="").validate()
        raise AssertionError("expected validation error")
    except SchemaValidationError:
        pass


def main() -> int:
    print("schemas tests")
    test_schema_version()
    test_goal_schema()
    test_task_schema()
    test_plan_schema()
    test_plan_state_schema()
    test_execution_schema()
    return summary("schemas")


if __name__ == "__main__":
    raise SystemExit(main())
