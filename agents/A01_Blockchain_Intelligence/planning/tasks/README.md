# A01 Blockchain Intelligence Agent — Planning / Tasks

## Purpose

`planning/tasks/` owns everything between a decomposed goal and an
executable task set: task lifecycle, dependency graphs, readiness,
prioritization, scheduling, reusable workflows, and plan-state tracking.

## Module Inventory

| Module             | Responsibility                                          |
| ------------------ | ------------------------------------------------------- |
| `task.py`          | `TaskManager` — task CRUD + status transitions          |
| `task_graph.py`    | `TaskGraph` — DAG from deps, topo order, levels         |
| `dependency.py`    | Readiness / blocked classification, ready-task resolve  |
| `decomposition.py` | `DecompositionService` — goal → task graph              |
| `prioritizer.py`   | `TaskPrioritizer` — scheduling weights + ordering       |
| `scheduler.py`     | `TaskScheduler` — batches ready tasks within limits     |
| `workflow.py`      | `WorkflowRegistry` — reusable step templates            |
| `planner_state.py` | `PlannerStateManager` — runtime `PlanStateSchema`       |

## Task Lifecycle

`TaskManager.set_status()` enforces a transition table over `TaskStatus`:

```
PENDING → READY → RUNNING → SUCCEEDED        (terminal)
   │        │       │   │
   ▼        ▼       │   ├──→ RETRYING → RUNNING
  BLOCKED  CANCELLED│   ▼
   │        ▲       │  FAILED  (terminal)
   ▼        │       │
  READY ────┘       └── CANCELLED / SKIPPED (terminal)
```

## Readiness & Scheduling

- `dependency.resolve_ready_tasks()` returns tasks whose dependencies all
  succeeded (no deps ⇒ ready).
- `TaskGraph.execution_levels()` groups tasks into parallel batches;
  `topological_order()` gives a valid execution sequence.
- `TaskScheduler.schedule(tasks, running_count=...)` returns the next batch
  of ready tasks, capped at `max_concurrent`, ordered by weight.
- `TaskPrioritizer` weights tasks by `priority/100 + depth_bias·depth`
  plus an optional custom scorer.

## Decomposition

`DecompositionService.decompose(goal)` runs a configurable
`Decomposer = Callable[[GoalSchema], list[TaskSchema]]`. Helpers:

- `build_chain_tasks` — linear pipeline (each task depends on previous)
- `build_parallel_tasks` — independent tasks (single execution level)

Produced graphs are validated for cycles (`CyclicDependencyError`) and
unknown dependencies (`MissingDependencyError` / `UnknownDependencyError`).

## Workflows

`WorkflowDefinition` is a reusable template of `WorkflowStep`s. Step
dependencies reference step *names*; `WorkflowRegistry.instantiate()`
turns a template + goal into a validated `TaskGraph` of `TaskSchema`
records.

## Plan State

`PlannerStateManager` maintains one `PlanStateSchema` per plan, recording
per-task statuses, attempt counts, the current task, checkpoints, and the
overall `PlanningState`.

## Dependencies

```
planning.utils     (constants, ids, graph, helpers)
planning.schemas   (TaskSchema, PlanStateSchema, GoalSchema)
```

## Usage

```python
from planning.tasks import TaskManager, TaskScheduler, TaskGraph
from planning.utils.constants import TaskStatus

tasks = TaskManager()
t1 = await tasks.create("fetch txs", plan_id="p1")
t2 = await tasks.create("analyze", plan_id="p1", dependencies=[t1.id])

await tasks.set_status(t1.id, TaskStatus.RUNNING)
await tasks.set_status(t1.id, TaskStatus.SUCCEEDED)

graph = TaskGraph(await tasks.list(plan_id="p1"))
scheduler = TaskScheduler(max_concurrent=2)
batch = scheduler.schedule(graph.tasks)   # [analyze]
```

## Verification

```
python -m compileall agents/A01_Blockchain_Intelligence/planning/tasks
```

Smoke tests cover: lifecycle transitions + guards, DAG/topo/levels,
missing-dependency and cycle errors, decomposition, prioritization,
scheduling caps, workflow round-trip, and plan-state tracking.
