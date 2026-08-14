# A01 Blockchain Intelligence Agent — Planning / Schemas

## Purpose

`planning/schemas/` defines the canonical data models (contracts) for the
planning subsystem. Business logic never consumes raw external payloads
directly — every payload is validated, normalized, and converted into one
of these schema objects first (coding standard §15).

## Schema Inventory

| Module       | Class              | Responsibility                                        |
| ------------ | ------------------ | ----------------------------------------------------- |
| `base.py`    | —                  | `SchemaError` hierarchy, `SCHEMA_VERSION`, time utils |
| `goal.py`    | `GoalSchema`       | Intent, constraints, acceptance criteria, hierarchy   |
| `task.py`    | `TaskSchema`       | Unit of work: deps, retry, timeout, routing, result   |
| `plan.py`    | `PlanSchema`       | Decomposed goal → ordered task list + strategy        |
| `state.py`   | `PlanStateSchema`  | Live execution position, per-task status, attempts    |
| `execution.py` | `ExecutionSchema` | One task run: status, duration, result, error         |

## Common Contract

Every schema class provides:

- `validate()` — raises `SchemaValidationError` on invalid state.
- `touch()` — refreshes `updated_at` (execution also derives timestamps).
- `to_dict()` — JSON-safe plain dict (enums serialized to values, datetimes
  to ISO-8601).
- `from_dict(payload)` — lenient deserialization: missing timestamps default
  to now, enums coerce by value, and validation runs after construction.
- A stable `id` generated via `planning.utils.ids` namespace generators
  (`goal_…`, `task_…`, `plan_…`, `exec_…`).

## Dependencies

```
planning.utils        (constants, ids, validation)
planning.schemas.base (errors, time helpers)
```

`PlanSchema` embeds `GoalSchema | None` and a list of `TaskSchema`, making a
serialized plan fully self-contained. `PlanStateSchema` and `ExecutionSchema`
track runtime position separately from static definitions.

## Usage

```python
from planning.schemas import GoalSchema, PlanSchema, TaskSchema
from planning.utils.constants import ExecutionMode

goal = GoalSchema(description="Track a whale wallet's activity")
task = TaskSchema(name="fetch transactions", tool="etherscan")
plan = PlanSchema(goal_id=goal.id, name="whale watch",
                  execution_mode=ExecutionMode.PARALLEL, tasks=[task])

plan.validate()
blob = plan.to_dict()            # persist anywhere
restored = PlanSchema.from_dict(blob)
```

## Verification

```
python -m compileall agents/A01_Blockchain_Intelligence/planning/schemas
```

Round-trip `to_dict()` → `from_dict()` must preserve equality for every
schema, and invalid payloads must raise `SchemaValidationError`.
