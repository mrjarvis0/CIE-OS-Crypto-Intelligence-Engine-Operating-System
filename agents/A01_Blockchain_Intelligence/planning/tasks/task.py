"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.task

Purpose:
    Task lifecycle management for the planning subsystem.

Owns task records, enforces status transitions, and provides
create / read / update / delete operations over ``TaskSchema``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from planning.schemas import TaskSchema
from planning.schemas.base import SchemaValidationError
from planning.utils.constants import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    MAX_RETRY,
    Priority,
    RetryPolicy,
    TaskStatus,
)
from planning.utils.ids import generate_task_id

logger = logging.getLogger("a01.planning.tasks")


class TaskError(Exception):
    """
    Base class for task lifecycle failures.
    """


class TaskNotFoundError(TaskError):
    """
    Raised when a task does not exist.
    """


class InvalidTaskTransitionError(TaskError):
    """
    Raised when a task status transition is not allowed.
    """


# Allowed status transitions for a task.
_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.READY,
        TaskStatus.BLOCKED,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    },
    TaskStatus.BLOCKED: {
        TaskStatus.READY,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    },
    TaskStatus.READY: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.RETRYING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RETRYING: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.SKIPPED: set(),
    TaskStatus.CANCELLED: set(),
}


class TaskManager:
    """
    In-memory lifecycle manager for planning tasks.

    Responsibilities:
        * Task CRUD
        * Status transition enforcement
        * Task retrieval and listing
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSchema] = {}
        self._lock = asyncio.Lock()

    @property
    def tasks(self) -> dict[str, TaskSchema]:
        """Read-only view of managed tasks by id."""
        return dict(self._tasks)

    async def create(
        self,
        name: str,
        *,
        description: str = "",
        plan_id: str | None = None,
        goal_id: str | None = None,
        dependencies: Iterable[str] = (),
        priority: Priority | None = None,
        retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
        tool: str | None = None,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> TaskSchema:
        """
        Create and register a new task.

        Raises
        ------
        SchemaValidationError
            When the task contract is invalid.
        """

        schema = TaskSchema(
            name=name,
            description=description,
            plan_id=plan_id,
            goal_id=goal_id,
            dependencies=list(dependencies),
            priority=priority if priority is not None else Priority.NORMAL,
            retry_policy=retry_policy,
            max_retries=(
                max_retries if max_retries is not None else MAX_RETRY
            ),
            timeout_seconds=(
                timeout_seconds
                if timeout_seconds is not None
                else DEFAULT_TASK_TIMEOUT_SECONDS
            ),
            tool=tool,
            input_data=input_data,
            metadata=metadata or {},
            id=task_id or generate_task_id(),
        )
        schema.validate()

        async with self._lock:
            if schema.id in self._tasks:
                raise TaskError(f"task already exists: {schema.id}")
            self._tasks[schema.id] = schema

        logger.info("task created: %s", schema.id)
        return schema

    async def register(self, task: TaskSchema) -> TaskSchema:
        """
        Register an existing, validated task schema.

        Unlike ``create``, the given schema is stored directly so that
        status updates made elsewhere (e.g. during plan execution) are
        reflected in the manager's records.
        """

        task.validate()

        async with self._lock:
            if task.id in self._tasks:
                raise TaskError(f"task already exists: {task.id}")
            self._tasks[task.id] = task

        logger.info("task registered: %s", task.id)
        return task

    async def get(self, task_id: str) -> TaskSchema:
        """Return a task by id."""
        task = self._tasks.get(task_id)

        if task is None:
            raise TaskNotFoundError(f"task not found: {task_id}")

        return task

    async def get_many(self, task_ids: Iterable[str]) -> list[TaskSchema]:
        """Return multiple tasks by id, preserving order."""
        return [await self.get(task_id) for task_id in task_ids]

    async def list(
        self,
        *,
        plan_id: str | None = None,
        status: TaskStatus | None = None,
    ) -> list[TaskSchema]:
        """Return tasks, optionally filtered by plan and status."""
        tasks = list(self._tasks.values())

        if plan_id is not None:
            tasks = [task for task in tasks if task.plan_id == plan_id]

        if status is not None:
            tasks = [task for task in tasks if task.status == status]

        return tasks

    async def update(self, task_id: str, **changes: Any) -> TaskSchema:
        """Update mutable fields on an existing task."""
        task = await self.get(task_id)
        mutable = {
            "name",
            "description",
            "dependencies",
            "priority",
            "retry_policy",
            "max_retries",
            "timeout_seconds",
            "tool",
            "input_data",
            "metadata",
        }

        for key, value in changes.items():
            if key not in mutable:
                raise TaskError(f"cannot update read-only field: {key}")
            setattr(task, key, value)

        task.touch()
        task.validate()
        logger.info("task updated: %s", task_id)
        return task

    async def delete(self, task_id: str) -> None:
        """Remove a task from the manager."""
        async with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(f"task not found: {task_id}")
            del self._tasks[task_id]

        logger.info("task deleted: %s", task_id)

    async def set_status(self, task_id: str, status: TaskStatus) -> TaskSchema:
        """
        Transition a task to a new status.

        Raises
        ------
        InvalidTaskTransitionError
            When the transition is not allowed.
        """

        task = await self.get(task_id)

        if status == task.status:
            return task

        allowed = _TASK_TRANSITIONS.get(task.status, set())

        if status not in allowed:
            raise InvalidTaskTransitionError(
                f"invalid transition: {task.status.value} -> {status.value}"
            )

        task.status = status
        task.touch()
        task.validate()
        logger.info("task %s transitioned: %s", task_id, status.value)
        return task

    async def record_result(self, task_id: str, result: Any) -> TaskSchema:
        """Attach a result to a task."""
        task = await self.get(task_id)
        task.result = result
        task.touch()
        return task

    async def record_error(self, task_id: str, error: str) -> TaskSchema:
        """Attach an error message to a task."""
        task = await self.get(task_id)
        task.error = error
        task.touch()
        return task

    async def clear(self) -> None:
        """Remove all managed tasks."""
        async with self._lock:
            self._tasks.clear()

        logger.info("tasks cleared")

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return serializable snapshots of all tasks."""
        return [task.to_dict() for task in self._tasks.values()]

    async def restore(self, snapshots: Iterable[dict[str, Any]]) -> int:
        """Restore tasks from serialized snapshots."""
        restored = 0

        async with self._lock:
            for snapshot in snapshots:
                try:
                    schema = TaskSchema.from_dict(snapshot)
                except SchemaValidationError:
                    continue

                self._tasks[schema.id] = schema
                restored += 1

        logger.info("tasks restored: %d", restored)
        return restored
