"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.execution.runners

Purpose:
    Execution runners for the planning subsystem.

Provides sequential, parallel, and level-by-level async execution of
task graphs over a shared task executor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from planning.schemas import TaskSchema
from planning.utils.constants import TaskStatus

from .executor import ExecutionError, TaskExecutor

logger = logging.getLogger("a01.planning.execution")


class SequentialExecutor:
    """
    Executes tasks one by one in dependency order.

    Responsibilities:
        * Topological execution of a task graph
        * Status updates on each task
        * Result and error collection
    """

    def __init__(
        self,
        executor: TaskExecutor | None = None,
    ) -> None:
        self._executor = executor

    def set_executor(self, executor: TaskExecutor) -> None:
        """Install a task executor."""
        self._executor = executor

    async def execute(
        self,
        tasks: list[TaskSchema],
        *,
        executor: TaskExecutor | None = None,
    ) -> dict[str, Any]:
        """
        Execute tasks in the provided order.

        Parameters
        ----------
        tasks
            Tasks already ordered (e.g. topological order).
        executor
            Optional executor override.

        Returns
        -------
        dict
            Mapping of task id to execution result (or error message).
        """

        runner = executor or self._executor

        if runner is None:
            raise ExecutionError("no task executor configured")

        results: dict[str, Any] = {}

        for task in tasks:
            await self._mark(task, TaskStatus.RUNNING)
            started_task = task

            try:
                record = await runner.execute(task)
                results[task.id] = record.result
                await self._mark(task, TaskStatus.SUCCEEDED)
                task.result = record.result
            except ExecutionError as exc:
                logger.warning("task %s failed: %s", task.id, exc)
                results[task.id] = str(exc)
                await self._mark(task, TaskStatus.FAILED)
                task.error = str(exc)

        logger.info(
            "sequential execution finished: %d tasks", len(tasks)
        )
        return results

    @staticmethod
    async def _mark(task: TaskSchema, status: TaskStatus) -> None:
        """Update a task's status and timestamp."""
        task.status = status
        task.touch()


class ParallelExecutor:
    """
    Executes tasks concurrently with a bounded worker pool.

    Responsibilities:
        * Concurrent task dispatch
        * Concurrency limit enforcement
        * Result and error collection
    """

    def __init__(
        self,
        executor: TaskExecutor | None = None,
        *,
        max_concurrent: int = 10,
    ) -> None:
        if max_concurrent < 1:
            raise ExecutionError("max_concurrent must be >= 1")

        self._executor = executor
        self._max_concurrent = max_concurrent

    @property
    def max_concurrent(self) -> int:
        """The configured concurrency limit."""
        return self._max_concurrent

    def set_executor(self, executor: TaskExecutor) -> None:
        """Install a task executor."""
        self._executor = executor

    async def execute(
        self,
        tasks: list[TaskSchema],
        *,
        executor: TaskExecutor | None = None,
    ) -> dict[str, Any]:
        """
        Execute all tasks concurrently.

        Parameters
        ----------
        tasks
            Tasks to execute. Dependencies are not re-verified here;
            callers should pass a ready batch or level.
        executor
            Optional executor override.

        Returns
        -------
        dict
            Mapping of task id to execution result (or error message).
        """

        runner = executor or self._executor

        if runner is None:
            raise ExecutionError("no task executor configured")

        semaphore = asyncio.Semaphore(self._max_concurrent)
        results: dict[str, Any] = {}
        tasks_lock = asyncio.Lock()

        async def run_one(task: TaskSchema) -> None:
            async with semaphore:
                task.status = TaskStatus.RUNNING
                task.touch()

                try:
                    record = await runner.execute(task)
                    async with tasks_lock:
                        results[task.id] = record.result
                    task.result = record.result
                    task.status = TaskStatus.SUCCEEDED
                except ExecutionError as exc:
                    logger.warning("task %s failed: %s", task.id, exc)
                    async with tasks_lock:
                        results[task.id] = str(exc)
                    task.error = str(exc)
                    task.status = TaskStatus.FAILED
                finally:
                    task.touch()

        await asyncio.gather(*(run_one(task) for task in tasks))

        logger.info(
            "parallel execution finished: %d tasks (limit %d)",
            len(tasks),
            self._max_concurrent,
        )
        return results


class AsyncRunner:
    """
    Executes a task graph level-by-level with concurrency.

    Responsibilities:
        * Level-by-level dependency scheduling
        * Parallel execution within a level
        * Progress and result collection
    """

    def __init__(
        self,
        executor: TaskExecutor | None = None,
        *,
        max_concurrent: int = 10,
    ) -> None:
        self._executor = executor
        self._parallel = ParallelExecutor(
            executor=executor,
            max_concurrent=max_concurrent,
        )

    @property
    def max_concurrent(self) -> int:
        """The configured concurrency limit."""
        return self._parallel.max_concurrent

    def set_executor(self, executor: TaskExecutor) -> None:
        """Install a task executor."""
        self._executor = executor
        self._parallel.set_executor(executor)

    async def execute_levels(
        self,
        levels: list[list[TaskSchema]],
        *,
        executor: TaskExecutor | None = None,
    ) -> dict[str, Any]:
        """
        Execute task levels in order.

        Parameters
        ----------
        levels
            Task batches where each level may run concurrently and later
            levels wait for earlier ones.
        executor
            Optional executor override.

        Returns
        -------
        dict
            Mapping of task id to execution result (or error message).
        """

        runner = executor or self._executor

        if runner is None:
            raise ExecutionError("no task executor configured")

        results: dict[str, Any] = {}
        failed: list[str] = []

        for index, level in enumerate(levels):
            level_results = await self._parallel.execute(
                level,
                executor=runner,
            )
            results.update(level_results)
            failed.extend(
                task_id
                for task_id, value in level_results.items()
                if isinstance(value, str)
            )
            logger.info("level %d finished (%d tasks)", index, len(level))

        logger.info(
            "async run finished: %d tasks, %d failed",
            len(results),
            len(failed),
        )
        return results

    async def execute_batch(
        self,
        tasks: list[TaskSchema],
        *,
        executor: TaskExecutor | None = None,
    ) -> dict[str, Any]:
        """
        Execute a single ready batch concurrently.
        """

        runner = executor or self._executor

        if runner is None:
            raise ExecutionError("no task executor configured")

        return await self._parallel.execute(tasks, executor=runner)
