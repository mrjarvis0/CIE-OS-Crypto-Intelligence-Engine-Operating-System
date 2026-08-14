# planning.execution

Task execution subsystem for the planning stack.

## Files

| Module              | Purpose                                                        |
| ------------------- | -------------------------------------------------------------- |
| `state_machine.py`  | `ExecutionStateMachine` — enforces execution lifecycle         |
| `executor.py`       | `TaskExecutor` — single task run with timeout and retry        |
| `runners.py`        | `SequentialExecutor`, `ParallelExecutor`, `AsyncRunner` — sequential, bounded-concurrent batch, and level-by-level async execution |
| `checkpoint.py`     | `Checkpoint` / `CheckpointManager` — plan snapshots            |
| `recovery.py`       | `RecoveryService` — resume from the latest checkpoint          |

## Execution lifecycle

The state machine permits the following transitions:

```
CREATED → SCHEDULED → RUNNING → SUCCEEDED
                         ├──> RETRYING → RUNNING
                         ├──> INTERRUPTED → RECOVERED / RUNNING
                         └──> FAILED / CANCELLED
```

Invalid transitions raise `InvalidExecutionTransitionError`.

## Usage

```python
import asyncio
from planning.execution import TaskExecutor, SequentialExecutor
from planning.schemas import TaskSchema

async def handler(task: TaskSchema):
    return {"echo": task.name}

async def main():
    tasks = [TaskSchema(name="alpha"), TaskSchema(name="beta")]
    runner = SequentialExecutor(TaskExecutor(handler))
    results = await runner.execute(tasks)

asyncio.run(main())
```

## Retry and timeout

Each task may carry its own `retry_policy`, `max_retries`, and
`timeout_seconds`. The `TaskExecutor`:

* wraps handler calls with `asyncio.wait_for` to enforce the timeout;
* retries according to the task's `RetryPolicy`
  (`NONE`, `FIXED`, `EXPONENTIAL`, `JITTERED`, `ALWAYS`);
* raises `ExecutionTimeoutError` on timeout exhaustion and
  `ExecutionExhaustedError` when the retry budget is spent.

## Checkpoints and recovery

`CheckpointManager` stores `Checkpoint` snapshots keyed by plan, with an
optional external saver callback. `RecoveryService` restores the latest
payload and filters already-`SUCCEEDED` tasks so a plan can resume after
an interruption without redundant work.
