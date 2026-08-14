# A01 Blockchain Intelligence Agent — Planning / Routing

## Purpose

`planning/routing/` decides *who does what*: it routes a scheduled task to
the best-matching tool or agent using a configured strategy, subject to
policy constraints.

## Module Inventory

| Module             | Responsibility                                         |
| ------------------ | ------------------------------------------------------ |
| `strategy.py`      | Strategy impls + `RouteResult`, scorer, `build_strategy` |
| `router.py`        | `Router` — target registry + strategy/policy dispatch  |
| `selector.py`      | `ToolSelector`, `AgentSelector` — task → tool/agent routing |
| `policy.py`        | `RoutingPolicy` — allow/deny, capacity, custom checks  |

## Strategies

Each strategy maps to a `RoutingStrategy` value and is built via
`build_strategy()`:

| Strategy            | Behavior                                   |
| ------------------- | ------------------------------------------ |
| `FIRST_MATCH`       | First candidate scoring above zero         |
| `BEST_SCORE`        | Highest-scoring candidate                  |
| `ROUND_ROBIN`       | Rotation across candidates (load balance)  |
| `RANDOM`            | Uniform random selection                   |
| `FALLBACK`          | Best score, else first candidate           |

The default scorer matches tokens in the task name/description against a
candidate's description. Custom scorers can be installed via
`Router.set_scorer()` (`Scorer = Callable[[TaskSchema, Any], float]`).

## Router

`Router` owns the target registry. Targets must expose an `id` (and
ideally a `description`):

```python
router = Router(strategy=RoutingStrategy.BEST_SCORE)
router.register(tool)              # any object with .id
result = router.route(task, strict=True)   # raises NoRouteFoundError on miss
```

`RouteResult` carries `candidate_id`, `strategy`, `score`, and the
candidates considered.

## Policies

`RoutingPolicy` filters candidates before the strategy runs:

- `allow_only({ids})` — restrict to an allow-list (`None` = no limit)
- `deny({ids})` — forbid targets
- `set_capacity(id, n)` / `record_usage(id)` — concurrency caps
- `add_check(check)` — custom `PolicyCheck` returning `PolicyDecision`

A filtered-out route yields `RouteResult(None, ...)` unless `strict=True`.

## Selectors

`ToolSelector` and `AgentSelector` wrap a `Router` with tool/agent-specific
registration and `select(task)` semantics. Both default to
`BEST_SCORE` and support `strict=True`.

## Dependencies

```
planning.schemas   (TaskSchema)
planning.utils     (constants.RoutingStrategy)
```

## Verification

```
python -m compileall agents/A01_Blockchain_Intelligence/planning/routing
```

Smoke tests cover: strategy selection (best-score, round-robin, random,
fallback), allow/deny policy, capacity blocking, strict `NoRouteFoundError`,
tool/agent selectors, and register/unregister errors.
