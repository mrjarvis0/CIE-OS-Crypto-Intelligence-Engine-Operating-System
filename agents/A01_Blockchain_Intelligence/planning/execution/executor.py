"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.execution.executor

Purpose:
    Single-task executor for the planning subsystem.

Runs one task through a handler, applying timeout, retry, and
execution-record bookkeeping.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from planning.schemas import ExecutionSchema, TaskSchema
from planning.schemas.base import _now
from planning.utils.constants import ExecutionStatus, RetryPolicy
from planning.utils.timers import BackoffConfig, ExponentialBackoff

from .state_machine import ExecutionStateMachine

logger = logging.getLogger("a01.planning.execution")

Handler = Callable[[TaskSchema], Awaitable[Any]]


class ExecutionError(Exception):
    """
    Base class for task execution failures.
    """


class ExecutionTimeoutError(ExecutionError):
    """
    Raised when a task exceeds its configured timeout.
    """


class ExecutionExhaustedError(ExecutionError):
    """
    Raised when a task fails after exhausting its retry budget.
    """


class TaskExecutor:
    """
    Executes a single task with timeout and retry handling.

    Responsibilities:
        * Running the task handler
        * Enforcing timeouts
        * Applying the retry policy
        * Maintaining an ExecutionSchema record
    """

    def __init__(
        self,
        handler: Handler,
        *,
        default_retries: int = 0,
    ) -> None:
        if not callable(handler):
            raise ExecutionError("handler must be callable")

        self._handler = handler
        self._default_retries = default_retries

    @property
    def handler(self) -> Handler:
        """The task handler."""
        return self._handler

    async def execute(
        self,
        task: TaskSchema,
        *,
        execution: ExecutionSchema | None = None,
        max_retries: int | None = None,
    ) -> ExecutionSchema:
        """
        Execute a task, returning its execution record.

        Raises
        ------
        ExecutionTimeoutError
            When the task exceeds ``task.timeout_seconds``.
        ExecutionExhaustedError
            When all retries are exhausted.
        """

        if execution is not None:
            record = execution
        else:
            record = ExecutionSchema(
                task_id=task.id,
                plan_id=task.plan_id,
                max_retries=(
                    max_retries
                    if max_retries is not None
                    else self._default_retries
                ),
            )

        if max_retries is not None:
            record.max_retries = max_retries
        elif record.max_retries == 0 and task.max_retries > 0:
            record.max_retries = task.max_retries

        record.touch()

        self._start(record)

        started = _now()
        attempt = 0
        max_attempts = 1 + record.max_retries

        while attempt < max_attempts:
            attempt += 1
            record.attempt = attempt
            started = _now()

            self._run(record)
            try:
                result = await asyncio.wait_for(
                    self._handler(task),
                    timeout=task.timeout_seconds,
                )
            except asyncio.TimeoutError:
                remaining = max_attempts - attempt

                if remaining > 0:
                    ExecutionStateMachine.mark_retrying(record)
                    await self._sleep_retry(task, attempt)
                    continue

                raise ExecutionTimeoutError(
                    f"task {task.id} timed out after "
                    f"{task.timeout_seconds}s"
                ) from None
            except Exception as exc:
                remaining = max_attempts - attempt

                if remaining > 0:
                    ExecutionStateMachine.mark_retrying(record)
                    await self._sleep_retry(task, attempt)
                    continue

                record.error = str(exc)
                ExecutionStateMachine.mark_failed(record)
                record.duration_ms = self._duration_ms(started)
                raise ExecutionExhaustedError(
                    f"task {task.id} failed after {attempt} attempts: {exc}"
                ) from exc

            record.result = result
            record.duration_ms = self._duration_ms(started)
            ExecutionStateMachine.mark_succeeded(record)
            logger.info(
                "task %s succeeded in %d attempt(s)",
                task.id,
                attempt,
            )
            return record

        raise ExecutionExhaustedError(
            f"task {task.id} exhausted retry budget"
        )

    def _start(self, record: ExecutionSchema) -> None:
        """Walk a fresh record through the initial lifecycle states."""
        if record.status == ExecutionStatus.CREATED:
            ExecutionStateMachine.transition(
                record,
                ExecutionStatus.SCHEDULED,
            )

        ExecutionStateMachine.transition(
            record,
            ExecutionStatus.RUNNING,
        )

    def _run(self, record: ExecutionSchema) -> None:
        """Ensure the record is in the RUNNING state."""
        if record.status != ExecutionStatus.RUNNING:
            ExecutionStateMachine.transition(
                record,
                ExecutionStatus.RUNNING,
            )

    async def _sleep_retry(self, task: TaskSchema, attempt: int) -> None:
        """Sleep according to the task's retry policy."""
        policy = task.retry_policy

        if policy in (RetryPolicy.NONE, RetryPolicy.ALWAYS):
            await asyncio.sleep(0.0)
            return

        delay = self._delay_for(policy, attempt)
        await asyncio.sleep(delay)

    def _delay_for(self, policy: RetryPolicy, attempt: int) -> float:
        """Compute a retry delay from the policy."""
        backoff = ExponentialBackoff(
            BackoffConfig(base_seconds=1.0, factor=2.0, max_seconds=60.0)
        )

        if policy == RetryPolicy.FIXED:
            return 1.0

        if policy == RetryPolicy.JITTERED:
            return backoff.next_delay(attempt, jittered=True)

        return backoff.next_delay(attempt, jittered=False)

    @staticmethod
    def _duration_ms(started: datetime) -> float:
        """Elapsed milliseconds since a start timestamp."""
        return (_now() - started).total_seconds() * 1000.0
