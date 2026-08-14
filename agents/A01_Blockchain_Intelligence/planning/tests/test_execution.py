"""
Tests for planning.execution.

Covers the execution state machine, task executor, sequential and
parallel runners, async runner, checkpoints, and recovery.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.execution import (
    AsyncRunner,
    CheckpointManager,
    ExecutionStateMachine,
    ExecutionTimeoutError,
    InvalidExecutionTransitionError,
    ParallelExecutor,
    RecoveryService,
    SequentialExecutor,
    TaskExecutor,
)
from planning.schemas import ExecutionSchema, TaskSchema
from planning.utils.constants import ExecutionStatus, RetryPolicy, TaskStatus
from planning.tests import check, summary


def test_state_machine() -> None:
    record = ExecutionSchema(task_id="t1", plan_id="p1")
    check("state machine created", record.status == ExecutionStatus.CREATED)

    ExecutionStateMachine.transition(record, ExecutionStatus.SCHEDULED)
    ExecutionStateMachine.transition(record, ExecutionStatus.RUNNING)
    ExecutionStateMachine.mark_succeeded(record, result="ok")
    check("state machine succeeded", record.status == ExecutionStatus.SUCCEEDED)
    check("state machine result", record.result == "ok")

    interrupted = ExecutionSchema(task_id="t2")
    ExecutionStateMachine.transition(interrupted, ExecutionStatus.SCHEDULED)
    ExecutionStateMachine.transition(interrupted, ExecutionStatus.RUNNING)
    ExecutionStateMachine.mark_interrupted(interrupted)
    check("state machine interrupted", interrupted.status == ExecutionStatus.INTERRUPTED)
    ExecutionStateMachine.mark_failed(interrupted, error="boom")
    check("state machine error", interrupted.error == "boom")

    try:
        ExecutionStateMachine.transition(interrupted, ExecutionStatus.SUCCEEDED)
        raise AssertionError("expected invalid transition")
    except InvalidExecutionTransitionError:
        pass


async def test_executor_success() -> None:
    async def ok_handler(task: TaskSchema) -> str:
        return f"done:{task.id}"

    executor = TaskExecutor(ok_handler)
    task = TaskSchema(name="t", description="d")
    record = await executor.execute(task)
    check("executor succeeded", record.status == ExecutionStatus.SUCCEEDED)
    check("executor result", record.result == f"done:{task.id}")
    check("executor duration", record.duration_ms is not None)


async def test_executor_retry_then_success() -> None:
    calls = {"n": 0}

    async def flaky(task: TaskSchema) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    executor = TaskExecutor(flaky)
    task = TaskSchema(
        name="t",
        description="d",
        retry_policy=RetryPolicy.NONE,
        max_retries=3,
    )
    record = await executor.execute(task)
    check("executor retry succeeded", record.status == ExecutionStatus.SUCCEEDED)
    check("executor attempt count", record.attempt == 3)


async def test_executor_exhausted() -> None:
    async def always_fails(task: TaskSchema) -> str:
        raise RuntimeError("nope")

    executor = TaskExecutor(always_fails)
    task = TaskSchema(
        name="t",
        description="d",
        retry_policy=RetryPolicy.NONE,
        max_retries=1,
    )
    try:
        await executor.execute(task)
        raise AssertionError("expected exhaustion")
    except Exception as exc:
        check("executor exhausted", "nope" in str(exc))


async def test_executor_timeout() -> None:
    async def slow(task: TaskSchema) -> str:
        await asyncio.sleep(5)
        return "late"

    executor = TaskExecutor(slow)
    task = TaskSchema(
        name="t",
        description="d",
        timeout_seconds=0.05,
        max_retries=0,
    )
    try:
        await executor.execute(task)
        raise AssertionError("expected timeout")
    except ExecutionTimeoutError:
        pass


async def test_sequential() -> None:
    order: list[str] = []

    async def handler(task: TaskSchema) -> str:
        order.append(task.id)
        return task.id

    runner = SequentialExecutor(TaskExecutor(handler))
    tasks = [TaskSchema(name=f"t{i}", description="d") for i in range(3)]
    results = await runner.execute(tasks)
    check("sequential results", results == {t.id: t.id for t in tasks})
    check("sequential order", order == [t.id for t in tasks])
    check("sequential statuses", all(t.status == TaskStatus.SUCCEEDED for t in tasks))


async def test_parallel() -> None:
    async def handler(task: TaskSchema) -> str:
        await asyncio.sleep(0.01)
        return task.id

    runner = ParallelExecutor(TaskExecutor(handler), max_concurrent=2)
    tasks = [TaskSchema(name=f"t{i}", description="d") for i in range(6)]
    results = await runner.execute(tasks)
    check("parallel results", set(results) == {t.id for t in tasks})
    check("parallel statuses", all(t.status == TaskStatus.SUCCEEDED for t in tasks))


async def test_async_runner_levels() -> None:
    async def handler(task: TaskSchema) -> str:
        return task.id

    runner = AsyncRunner(TaskExecutor(handler), max_concurrent=3)
    tasks = [TaskSchema(name=f"t{i}", description="d") for i in range(4)]
    results = await runner.execute_levels([tasks[:2], tasks[2:]])
    check("async runner results", set(results) == {t.id for t in tasks})


async def test_checkpoint_recovery() -> None:
    cm = CheckpointManager()
    first = await cm.create("plan-1", {"done": ["a"]}, step=1)
    second = await cm.create("plan-1", {"done": ["a", "b"]}, step=2)

    latest = await cm.latest("plan-1")
    check("latest checkpoint", latest is not None and latest.id == second.id)

    tasks = [
        TaskSchema(name="a", description="d", status=TaskStatus.SUCCEEDED),
        TaskSchema(name="b", description="d", status=TaskStatus.SUCCEEDED),
        TaskSchema(name="c", description="d", status=TaskStatus.PENDING),
    ]
    recovery = RecoveryService(cm)
    result = await recovery.recover("plan-1", tasks)
    check("recovery payload", result.checkpoint_payload == {"done": ["a", "b"]})
    check("recovery skipped", result.skipped_count == 2)
    check("recovery resumed", result.resumed_count == 1)
    check("recovery resumed task", result.resumed[0].id == tasks[2].id)

    checkpoint = await cm.restore("plan-1")
    check("restore payload", checkpoint == {"done": ["a", "b"]})
    check("checkpoint step", first.step == 1)


async def main() -> int:
    print("execution tests")
    test_state_machine()
    await test_executor_success()
    await test_executor_retry_then_success()
    await test_executor_exhausted()
    await test_executor_timeout()
    await test_sequential()
    await test_parallel()
    await test_async_runner_levels()
    await test_checkpoint_recovery()
    return summary("execution")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
