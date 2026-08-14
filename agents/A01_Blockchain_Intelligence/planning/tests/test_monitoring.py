"""
Tests for planning.monitoring.

Covers the event bus, metrics registry, tracing, timeline,
progress tracking, and diagnostics.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.monitoring import (
    Diagnostics,
    EventBus,
    MetricsRegistry,
    PlanEvent,
    ProgressTracker,
    Span,
    Timeline,
    Tracer,
    Timer,
)
from planning.schemas import PlanSchema, TaskSchema
from planning.utils.constants import EventType, TaskStatus
from planning.tests import check, summary


async def test_events() -> None:
    bus = EventBus(history_limit=100)
    received: list[str] = []

    def on_task_succeeded(event: dict) -> None:
        received.append(event["type"])

    async def on_any(event: dict) -> None:
        received.append(f"any:{event['type']}")

    bus.subscribe(EventType.TASK_SUCCEEDED, on_task_succeeded)
    bus.subscribe_all(on_any)

    await bus.emit(
        PlanEvent(
            type=EventType.TASK_SUCCEEDED,
            plan_id="plan-1",
            task_id="task-1",
            payload={"ok": True},
        )
    )
    await bus.emit(PlanEvent(type=EventType.PLAN_STARTED, plan_id="plan-1"))

    check("event sync handler", "task_succeeded" in received)
    check("event async handler", "any:task_succeeded" in received)
    check("event subscribe_all", "any:plan_started" in received)

    history = await bus.history(event_type=EventType.TASK_SUCCEEDED)
    check("event history count", len(history) == 1)
    check("event history payload", history[0].payload == {"ok": True})
    check("event correlation id", bool(history[0].correlation_id))

    await bus.clear()
    check("event cleared", await bus.history() == [])


async def test_metrics() -> None:
    registry = MetricsRegistry()

    registry.inc("tasks_created", 3)
    registry.inc("tasks_created")
    check("metrics counter", registry.counter("tasks_created").value == 4)

    gauge = registry.gauge("queue_depth")
    gauge.set(5.0)
    gauge.add(-2.0)
    check("metrics gauge", gauge.value == 3.0)

    with Timer(registry, "task_run"):
        time.sleep(0.01)

    stats = registry.duration_stats("task_run")
    check("metrics timer count", stats["count"] == 1.0)
    check("metrics timer mean", stats["mean"] > 0.0)

    snapshot = registry.snapshot()
    check("metrics snapshot counter", snapshot["counters"]["tasks_created"] == 4)
    check("metrics snapshot gauge", snapshot["gauges"]["queue_depth"] == 3.0)
    check("metrics snapshot timer", snapshot["timers"]["task_run"]["count"] == 1.0)

    registry.reset()
    check("metrics reset", registry.counter("tasks_created").value == 0)


def test_tracing() -> None:
    tracer = Tracer()

    root = tracer.start_span("plan")
    child = tracer.start_span("task")
    check("tracing child parent", child.parent_id == root.id)
    check("tracing same trace", child.trace_id == root.trace_id)

    tracer.end_span(child)
    child.end()
    check("tracing duration", child.duration_ms is not None)

    tracer.end_span(root)

    spans = tracer.spans_for_trace(root.trace_id)
    check("tracing span count", len(spans) == 2)
    check("tracing no errors", not tracer.trace_has_errors(root.trace_id))

    orphan = Span("task", "orphan-trace")
    orphan.end()
    check("tracing standalone", isinstance(orphan.duration_ms, float))


def test_timeline() -> None:
    timeline = Timeline(limit=10)

    timeline.record("plan-1", TaskStatus.RUNNING.value, message="plan started")
    timeline.record(
        "plan-1",
        TaskStatus.SUCCEEDED.value,
        message="task task-1 done",
    )
    timeline.record(
        "plan-1",
        TaskStatus.SUCCEEDED.value,
        message="task task-2 done",
    )
    timeline.record("plan-2", TaskStatus.FAILED.value, message="boom")

    check("timeline count", len(timeline.entries) == 4)
    check("timeline succeeded count", timeline.succeeded_count("plan-1") == 2)
    check("timeline by status", len(timeline.for_status(TaskStatus.SUCCEEDED.value)) == 2)
    check("timeline task events", len(timeline.task_events("task-1")) == 1)
    check("timeline by plan", len(timeline.for_plan("plan-2")) == 1)

    timeline.clear()
    check("timeline cleared", timeline.entries == [])


def test_progress() -> None:
    tracker = ProgressTracker()
    tasks = [
        TaskSchema(name="a", description="d", status=TaskStatus.SUCCEEDED),
        TaskSchema(name="b", description="d", status=TaskStatus.SUCCEEDED),
        TaskSchema(name="c", description="d", status=TaskStatus.PENDING),
        TaskSchema(name="d", description="d", status=TaskStatus.FAILED),
    ]
    plan = PlanSchema(goal_id="g", name="p", tasks=tasks)

    report = tracker.report(plan)
    check("progress total", report.total == 4)
    check("progress completed", report.completed == 2)
    check("progress failed", report.failed == 1)
    check("progress pending", report.pending == 1)
    check("progress percent", report.percent == 50.0)
    check("progress summary", "50.0%" in report.summary())

    payload = report.to_dict()
    check("progress to_dict", payload["percent"] == 50.0)

    batch = ProgressTracker.batch_report(
        [TaskStatus.SUCCEEDED, TaskStatus.PENDING]
    )
    check("progress batch", batch.completed == 1)


def test_diagnostics() -> None:
    diagnostics = Diagnostics()
    diagnostics.register("test_ok", lambda: (True, "all good"))

    tasks = [
        TaskSchema(name="a", description="d"),
        TaskSchema(name="b", description="d"),
    ]
    plan = PlanSchema(goal_id="g", name="p", tasks=tasks)

    report = diagnostics.run_plan_checks(plan)
    check("diagnostics healthy", report.healthy)
    check(
        "diagnostics unique ids",
        any(c.name == "task_ids_unique" and c.passed for c in report.checks),
    )
    check(
        "diagnostics named",
        any(c.name == "tasks_named" and c.passed for c in report.checks),
    )
    check(
        "diagnostics custom",
        any(c.name == "test_ok" and c.passed for c in report.checks),
    )

    empty = PlanSchema(goal_id="", name="")
    empty_report = diagnostics.run_plan_checks(empty)
    check("diagnostics rejects empty", not empty_report.healthy)


async def main() -> int:
    print("monitoring tests")
    await test_events()
    await test_metrics()
    test_tracing()
    test_timeline()
    test_progress()
    test_diagnostics()
    return summary("monitoring")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
