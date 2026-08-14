"""
Tests for planning.tasks.

Covers the task lifecycle, dependency graph, dependency resolution,
decomposition, prioritization, scheduling, workflows, and plan state.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.schemas import GoalSchema, PlanSchema, TaskSchema
from planning.tasks import (
    ConcurrencyLimitError,
    CyclicDependencyError,
    DecompositionService,
    InvalidTaskTransitionError,
    MissingDependencyError,
    PlannerStateManager,
    TaskGraph,
    TaskManager,
    TaskPrioritizer,
    TaskScheduler,
    TaskNotFoundError,
    UnknownDependencyError,
    WorkflowDefinition,
    WorkflowRegistry,
    WorkflowStep,
    are_dependencies_satisfied,
    build_chain_tasks,
    build_parallel_tasks,
    compute_blocked_tasks,
    resolve_ready_tasks,
)
from planning.utils.constants import (
    PlanningState,
    Priority,
    TaskStatus,
)
from planning.tests import check, summary


async def test_task_manager() -> None:
    manager = TaskManager()
    task = await manager.create("fetch", goal_id="goal-1")
    check("task created", task.status == TaskStatus.PENDING)

    fetched = await manager.get(task.id)
    check("task fetched", fetched.id == task.id)

    try:
        await manager.get("missing")
        raise AssertionError("expected not found")
    except TaskNotFoundError:
        pass

    await manager.set_status(task.id, TaskStatus.READY)
    await manager.set_status(task.id, TaskStatus.RUNNING)
    await manager.set_status(task.id, TaskStatus.SUCCEEDED)
    succeeded = await manager.get(task.id)
    check("task succeeded", succeeded.status == TaskStatus.SUCCEEDED)

    try:
        await manager.set_status(task.id, TaskStatus.PENDING)
        raise AssertionError("expected invalid transition")
    except InvalidTaskTransitionError:
        pass

    await manager.record_result(task.id, {"ok": True})
    check("task result", (await manager.get(task.id)).result == {"ok": True})
    await manager.record_error(task.id, "boom")
    check("task error", (await manager.get(task.id)).error == "boom")


async def test_task_graph() -> None:
    tasks = [
        TaskSchema(name="a", description="d"),
        TaskSchema(name="b", description="d"),
        TaskSchema(name="c", description="d"),
    ]
    tasks[1].dependencies = [tasks[0].id]
    tasks[2].dependencies = [tasks[0].id]

    graph = TaskGraph(tasks)
    graph.validate_dag()
    check("graph is dag", graph.is_dag)
    check("graph size", graph.size() == 3)
    check("topological order", graph.topological_order()[0] == tasks[0].id)
    check("execution levels", graph.execution_levels() == [[tasks[0].id], [tasks[1].id, tasks[2].id]])
    check("successors", sorted(graph.successors(tasks[0].id)) == sorted([tasks[1].id, tasks[2].id]))

    cyclic = [
        TaskSchema(name="x", description="d"),
        TaskSchema(name="y", description="d"),
    ]
    cyclic[0].dependencies = [cyclic[1].id]
    cyclic[1].dependencies = [cyclic[0].id]
    try:
        TaskGraph(cyclic).validate_dag()
        raise AssertionError("expected cycle error")
    except CyclicDependencyError:
        pass

    missing = [
        TaskSchema(name="a", description="d", dependencies=["ghost"]),
    ]
    try:
        TaskGraph(missing)
        raise AssertionError("expected missing dependency error")
    except MissingDependencyError:
        pass


async def test_dependency_resolution() -> None:
    tasks = {
        "a": TaskSchema(name="a", description="d", id="a", status=TaskStatus.SUCCEEDED),
        "b": TaskSchema(name="b", description="d", id="b"),
        "c": TaskSchema(name="c", description="d", id="c"),
    }
    tasks["b"].dependencies = ["a"]
    tasks["c"].dependencies = ["b"]

    check("deps satisfied", are_dependencies_satisfied(tasks["b"], tasks))
    check("deps not satisfied", not are_dependencies_satisfied(tasks["c"], tasks))
    check("ready tasks", {t.id for t in resolve_ready_tasks(tasks)} == {"b"})

    tasks["a"].status = TaskStatus.FAILED
    check("blocked tasks", {t.id for t in compute_blocked_tasks(tasks)} == {"b"})

    try:
        are_dependencies_satisfied(tasks["b"], {"a": None})
        raise AssertionError("expected unknown dependency error")
    except UnknownDependencyError:
        pass


async def test_decomposition() -> None:
    goal = GoalSchema(description="build a tool")
    service = DecompositionService()
    service.set_decomposer(lambda g: build_chain_tasks(g, ["fetch", "analyze", "report"]))

    graph = await service.decompose(goal)
    check("decomposed chain", graph.size() == 3)
    tasks = list(graph.tasks.values())
    check("chain has dependencies", tasks[1].dependencies == [tasks[0].id])
    check("goal id attached", all(t.goal_id == goal.id for t in tasks))

    service.set_decomposer(lambda g: [])
    try:
        await service.decompose(goal)
        raise AssertionError("expected no tasks error")
    except Exception as exc:
        check("empty decomposition raises", "no tasks" in str(exc))

    parallel = build_parallel_tasks(goal, ["a", "b", "c"])
    check("parallel tasks independent", all(not t.dependencies for t in parallel))


async def test_prioritizer() -> None:
    low = TaskSchema(name="low", description="d", priority=Priority.LOW)
    high = TaskSchema(name="high", description="d", priority=Priority.HIGH)
    critical = TaskSchema(name="critical", description="d", priority=Priority.CRITICAL)

    prioritizer = TaskPrioritizer()
    prioritized = prioritizer.prioritize([low, high, critical])
    check("prioritizer orders by priority", prioritized[0].task.id == critical.id)
    check("prioritizer highest weight", prioritized[0].weight > prioritized[-1].weight)


async def test_scheduler() -> None:
    tasks = {
        "a": TaskSchema(name="a", description="d", id="a"),
        "b": TaskSchema(name="b", description="d", id="b"),
        "c": TaskSchema(name="c", description="d", id="c"),
    }
    tasks["b"].dependencies = ["a"]

    scheduler = TaskScheduler(max_concurrent=2)
    batch = scheduler.schedule(tasks)
    check("scheduler ready tasks", {item.task.id for item in batch} == {"a", "c"})

    batch = scheduler.schedule(tasks, slots=1)
    check("scheduler slot limit", len(batch) == 1)

    try:
        scheduler.schedule(tasks, running_count=5)
        raise AssertionError("expected concurrency error")
    except ConcurrencyLimitError:
        pass

    depths = scheduler.depth_map(tasks)
    check("scheduler depth a", depths["a"] == 0)
    check("scheduler depth b", depths["b"] == 1)


async def test_workflow() -> None:
    workflow = WorkflowDefinition(
        name="pipeline",
        steps=[
            WorkflowStep(name="fetch", tool="chain-reader"),
            WorkflowStep(name="analyze", dependencies=["fetch"]),
            WorkflowStep(name="report", dependencies=["analyze"]),
        ],
    )
    workflow.validate()

    registry = WorkflowRegistry()
    await registry.register(workflow)
    check("workflow registered", len(await registry.list()) == 1)

    goal = GoalSchema(description="run the pipeline")
    graph = await registry.instantiate(workflow.id, goal)
    check("workflow instantiated", graph.size() == 3)
    check("workflow tasks ordered", graph.topological_order()[0] != graph.topological_order()[-1])

    bad = WorkflowDefinition(
        name="bad",
        steps=[
            WorkflowStep(name="a", dependencies=["nope"]),
        ],
    )
    try:
        bad.validate()
        raise AssertionError("expected validation error")
    except Exception as exc:
        check("workflow invalid dep", "unknown step" in str(exc))


async def test_planner_state() -> None:
    manager = PlannerStateManager()
    state = await manager.create("plan-1")
    check("planner state created", state.state == PlanningState.CREATED)

    await manager.record_task_status("plan-1", "task-1", TaskStatus.RUNNING)
    await manager.record_attempt("plan-1", "task-1")
    await manager.set_plan_state("plan-1", PlanningState.EXECUTING)
    await manager.set_checkpoint("plan-1", "ckpt-1")

    record = await manager.get("plan-1")
    check("state task recorded", record.task_statuses["task-1"] == TaskStatus.RUNNING)
    check("state attempt recorded", record.attempt_counts["task-1"] == 1)
    check("state plan executing", record.state == PlanningState.EXECUTING)
    check("state checkpoint", record.checkpoint_count == 1)

    task = TaskSchema(name="t", description="d")
    task.plan_id = "plan-1"
    await manager.apply_task(task)
    check("state applied task", (await manager.get("plan-1")).task_statuses[task.id] == TaskStatus.PENDING)


async def main() -> int:
    print("tasks tests")
    await test_task_manager()
    await test_task_graph()
    await test_dependency_resolution()
    await test_decomposition()
    await test_prioritizer()
    await test_scheduler()
    await test_workflow()
    await test_planner_state()
    return summary("tasks")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
