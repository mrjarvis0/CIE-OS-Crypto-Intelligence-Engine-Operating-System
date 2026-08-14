# planning.reasoning

Reasoning subsystem for the planning stack.

## Files

| Module         | Purpose                                                          |
| -------------- | ---------------------------------------------------------------- |
| `critic.py`    | `Critic` — reviews tasks/plans with severity findings            |
| `evaluator.py` | `Evaluator` — scores results against expectations                |
| `reflection.py`| `Reflector` — lessons learned from a plan run                    |
| `replanner.py` | `Replanner` — revises a plan after failures or feedback          |
| `retry.py`     | `RetryAnalyzer` — decides whether a failure should be retried    |
| `validator.py` | `PlanValidator` — structural validation of plans and task graphs |
| `verifier.py`  | `Verifier` — verifies outputs against acceptance criteria        |

## Typical flow

```
PlanValidator  → structural sanity of the plan
Critic         → quality / completeness review
Verifier       → check each task output
Evaluator      → score results against expectations
RetryAnalyzer  → decide on failures
Replanner      → revise plan if needed
Reflector      → capture lessons for the next cycle
```

## Severity

`critic.Severity` is a `StrEnum` with `INFO`, `WARNING`, and
`CRITICAL`. A `CritiqueReport`/`ValidationReport` is only considered
passed when no critical findings are present.

## Retry decisioning

`RetryAnalyzer.decide()` refuses retries when:

* the task's `RetryPolicy` is `NONE`;
* the retry budget (`task.max_retries`) is exhausted.

It always retries under `RetryPolicy.ALWAYS`, and otherwise only
retries transient failures (timeouts, connection errors, rate limits,
etc.).
