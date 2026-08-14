"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.executor

Purpose:
    Plan execution driver for the planning subsystem.

Runs the tasks of a plan to completion using the execution subsystem,
tracking task statuses, timing, and per-task results.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.schemas import PlanSchema, TaskSchema
from planning.utils.constants import TaskStatus

from .context import PlanningContext

logger = logging.getLogger("a01.planning.core")


class ExecutionReport:
    """
    Outcome of executing a plan.

    Fields:
        * Plan identifier
        * Per-task results
        * Aggregate counters
    """

    def __init__(
        self,
        plan_id: str,
        results: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        self.plan_id = plan_id
        self.results = dict(results or {})
        self.errors = dict(errors or {})

    @property
    def succeeded(self) -> int:
        """Number of tasks that produced results."""
        return len(self.results)

    @property
    def failed(self) -> int:
        """Number of tasks that raised errors."""
        return len(self.errors)

    @property
    def all_succeeded(self) -> bool:
        """Whether every task succeeded."""
        return not self.errors and bool(self.results)


class PlanExecutor:
    """
    Executes plans against a task handler.

    Responsibilities:
        * Iterating plan tasks
        * Delegating to the task handler
        * Recording results and errors
    """

    def __init__(self, context: PlanningContext) -> None:
        self._context = context

    @property
    def context(self) -> PlanningContext:
        """The bound planning context."""
        return self._context

    async def execute(self, plan: PlanSchema) -> ExecutionReport:
        """
        Execute all tasks of a plan sequentially.

        Task order follows the plan's task list. Dependencies are
        assumed to be satisfied by ordering.
        """

        report = ExecutionReport(plan.id)

        for task in plan.tasks:
            await self._start(task)
            await self._context.events.emit(
                task_event("task_started", task)
            )
            try:
                result = await self._context.task_executor.execute(task)
                task.result = result.result
                task.status = TaskStatus.SUCCEEDED
                task.touch()
                report.results[task.id] = result.result
                self._context.metrics.inc("tasks_succeeded")
                await self._context.events.emit(
                    task_event("task_succeeded", task)
                )
            except Exception as exc:
                logger.warning("task %s failed: %s", task.id, exc)
                task.error = str(exc)
                task.status = TaskStatus.FAILED
                task.touch()
                report.errors[task.id] = str(exc)
                self._context.metrics.inc("tasks_failed")
                await self._context.events.emit(
                    task_event("task_failed", task)
                )

        await self._context.events.emit(
            plan_event("plan_completed", plan)
        )
        return report

    @staticmethod
    async def _start(task: TaskSchema) -> None:
        """Mark a task as running."""
        task.status = TaskStatus.RUNNING
        task.touch()


def task_event(event_type: str, task: TaskSchema) -> Any:
    """Build a task-scoped PlanEvent."""
    from planning.monitoring import PlanEvent

    return PlanEvent(
        type=task_event_type(event_type),
        plan_id=task.plan_id,
        task_id=task.id,
        source="executor",
    )


def plan_event(event_type: str, plan: PlanSchema) -> Any:
    """Build a plan-scoped PlanEvent."""
    from planning.monitoring import PlanEvent

    return PlanEvent(
        type=task_event_type(event_type),
        plan_id=plan.id,
        source="executor",
    )


def task_event_type(event_type: str) -> Any:
    """Resolve an event type string to an EventType member."""
    from planning.utils.constants import EventType

    mapping = {
        "task_started": EventType.TASK_STARTED,
        "task_succeeded": EventType.TASK_SUCCEEDED,
        "task_failed": EventType.TASK_FAILED,
        "plan_completed": EventType.PLAN_COMPLETED,
    }
    return mapping[event_type]
