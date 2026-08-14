# planning.monitoring

Monitoring subsystem for the planning stack.

## Files

| Module         | Purpose                                                          |
| -------------- | ---------------------------------------------------------------- |
| `events.py`    | `EventBus` / `PlanEvent` — pub/sub over `EventType`              |
| `metrics.py`   | `MetricsRegistry`, `Counter`, `Gauge`, `Timer`                   |
| `tracing.py`   | `Tracer` / `Span` — span and trace context tracking              |
| `timeline.py`  | `Timeline` / `TimelineEntry` — chronological activity log        |
| `progress.py`  | `ProgressTracker` / `ProgressReport` — completion percentages    |
| `diagnostics.py`| `Diagnostics` / `DiagnosticReport` — self-checks and health     |

## Events

`EventBus` dispatches `PlanEvent`s to typed subscribers and wildcard
subscribers (async callables are awaited). Event history is retained
up to a configurable limit:

```python
from planning.monitoring import EventBus, PlanEvent
from planning.utils.constants import EventType

bus = EventBus()
bus.subscribe(EventType.TASK_SUCCEEDED, lambda ev: print(ev["type"]))

await bus.emit(PlanEvent(type=EventType.TASK_SUCCEEDED, plan_id="p1"))
```

## Metrics

`MetricsRegistry` tracks counters, gauges, and timer samples.
`Timer` is a context manager that records elapsed seconds:

```python
from planning.monitoring import MetricsRegistry, Timer

registry = MetricsRegistry()
registry.inc("tasks_created", 3)

with Timer(registry, "task_run"):
    run_tasks()

registry.snapshot()  # counters / gauges / timer stats
```

## Tracing

`Tracer.start_span()` nests spans under the current span and keeps
trace ids consistent so a full goal-to-task path is reconstructable:

```python
tracer = Tracer()
root = tracer.start_span("plan")
child = tracer.start_span("task")
tracer.end_span(child)
tracer.end_span(root)
```

## Progress and diagnostics

`ProgressTracker` reports completed/failed/pending counts plus a
percentage. `Diagnostics` runs registered self-checks and the standard
plan checks (unique task ids, named tasks, goal attachment).
