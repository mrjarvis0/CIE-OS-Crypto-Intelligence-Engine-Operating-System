# A01 Blockchain Intelligence Agent — Planning / Goals

## Purpose

`planning/goals/` manages the front end of planning: turning user intent
into a structured, constrained, verifiable goal that downstream phases
(tasks, routing, execution) can consume.

## Module Inventory

| Module          | Responsibility                                              |
| --------------- | ----------------------------------------------------------- |
| `goal.py`       | `GoalManager` — goal CRUD + enforced status transitions     |
| `objective.py`  | `Objective` / `ObjectiveManager` — measurable milestones    |
| `assumptions.py` | `Assumption` / `AssumptionManager` — beliefs + verification |
| `constraints.py` | `Constraint` / `ConstraintManager` — limits + evaluation    |
| `success.py`    | `SuccessEvaluator` — acceptance-criteria evaluation         |

## Goal Lifecycle

`GoalManager.set_status()` enforces a transition table over
`GoalStatus`:

```
NEW → UNDERSTOOD → CONSTRAINED → DECOMPOSED → READY → IN_PROGRESS → COMPLETED
        ↘                ↘            ↘         ↘       ↘            FAILED
         CANCELLED ← any active state; terminal states are final
```

Invalid transitions raise `InvalidGoalTransitionError`.

## Managers

All managers are in-memory (dict-backed), async-safe (`asyncio.Lock`),
and provide:

- `create / get / get_many / list / update / delete`
- `snapshot()` / `restore()` for serialization round-trips
- `clear()` for teardown

### GoalManager
Owns `GoalSchema` records, generates `goal_…` ids, and validates every
contract before storing.

### ObjectiveManager
Attaches measurable objectives (`Objective`) to goals, filters by
`goal_id`, and tracks completion.

### AssumptionManager
Records `Assumption`s with a `confidence` in `[0.0, 1.0]`, supports
`verify()`, and exposes `unverified()` for planner gating.

### ConstraintManager
Stores `Constraint`s (hard/soft) with optional predicates
(`predicate(candidate) -> str | None`). `evaluate()` returns a
`ConstraintReport` with `passed` and `violations`.

### SuccessEvaluator
Evaluates `GoalSchema.acceptance_criteria` against an execution result.
Criteria use a default truthiness check or a registered
`CriterionCheck`; produces a `SuccessReport`.

## Dependencies

```
planning.schemas      (GoalSchema, errors)
planning.utils        (constants, ids, helpers)
```

## Usage

```python
from planning.goals import GoalManager, ConstraintManager, SuccessEvaluator

goals = GoalManager()

goal = await goals.create(
    "Monitor whale transfers on Ethereum",
    acceptance_criteria=["transfers detected", "report generated"],
)
await goals.set_status(goal.id, GoalStatus.CONSTRAINED)
```

## Verification

```
python -m compileall agents/A01_Blockchain_Intelligence/planning/goals
```

Smoke tests cover: lifecycle transitions, transition guards, objective
completion, assumption verify/unverified, constraint pass/fail, success
reports, snapshot/restore, and error paths.
