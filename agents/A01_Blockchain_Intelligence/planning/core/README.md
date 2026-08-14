# planning.core

Core orchestration for the planning stack.

## Files

| Module          | Purpose                                                            |
| --------------- | ------------------------------------------------------------------ |
| `context.py`    | `PlanningContext` — dependency container for all subsystems        |
| `planner.py`    | `Planner` — decompose a goal into a validated plan                 |
| `dispatcher.py` | `Dispatcher` — route tasks to tools/agents via the router          |
| `executor.py`   | `PlanExecutor` — run a plan's tasks with the task handler          |
| `lifecycle.py`  | `PlanLifecycle` — enforce `PlanningState` transitions              |
| `coordinator.py`| `Coordinator` — drive plan → execute → validate → reflect          |
| `orchestrator.py`| `Orchestrator` — goal-scoped entry point with goal status flow     |
| `runtime.py`    | `PlanningRuntime` — composed public entry point                    |

## Plan lifecycle

`PlanLifecycle` enforces the `PlanningState` transition table:

```
CREATED → UNDERSTANDING → PLANNING → SCHEDULED → EXECUTING
              └→ PLANNING          └→ REPLANNING ┘
EXECUTING → VALIDATING → REFLECTING → COMPLETED
    └→ REPLANNING ┘  └→ REPLANNING ┘  └→ FAILED / CANCELLED
```

Invalid transitions raise `InvalidTransitionError`.

## Usage

```python
import asyncio
from planning.core import PlanningRuntime

async def handler(task):
    return {"processed": task.name}

async def main():
    runtime = PlanningRuntime(task_handler=handler)
    runtime.context.decomposer.set_decomposer(
        lambda goal: build_chain_tasks(goal, ["fetch", "analyze", "report"])
    )

    goal = await runtime.context.goals.create("build an indexer")
    outcome = await runtime.run_goal(goal)

    print(outcome.state)      # PlanningState.COMPLETED
    await runtime.close()

asyncio.run(main())
```

## Component wiring

`PlanningRuntime` builds a `PlanningContext` and binds the planner,
dispatcher, executor, lifecycle, coordinator, and orchestrator to it.
The lifecycle is shared through the context so both `Coordinator` and
`PlanningRuntime.lifecycle` observe the same transitions.
