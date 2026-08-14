"""
Tests for planning.core.

Covers the lifecycle, context, planner, executor, coordinator,
orchestrator, dispatcher, and runtime.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.core import (
    Coordinator,
    Dispatcher,
    ExecutionReport,
    InvalidTransitionError,
    PlanExecutor,
    PlanLifecycle,
    Planner,
    PlanningContext,
    PlanningRuntime,
)
from planning.goals import GoalManager
from planning.schemas import GoalSchema
from planning.tasks import build_chain_tasks
from planning.utils.constants import GoalStatus, PlanningState, TaskStatus
from planning.tests import check, summary


async def test_lifecycle() -> None:
    ctx = PlanningContext()
    lifecycle = PlanLifecycle(ctx)
    state = lifecycle.register(plan_id="plan-a")
    check("lifecycle created", state.state == PlanningState.CREATED)

    lifecycle.transition("plan-a", PlanningState.PLANNING)
    lifecycle.transition("plan-a", PlanningState.SCHEDULED)
    lifecycle.transition("plan-a", PlanningState.EXECUTING)
    check("lifecycle executing", lifecycle.get("plan-a").state == PlanningState.EXECUTING)

    try:
        lifecycle.transition("plan-a", PlanningState.REFLECTING)
        raise AssertionError("expected invalid transition")
    except InvalidTransitionError:
        pass

    lifecycle.transition("plan-a", PlanningState.VALIDATING)
    lifecycle.transition("plan-a", PlanningState.REFLECTING)
    lifecycle.transition("plan-a", PlanningState.COMPLETED)
    check("lifecycle completed", lifecycle.get("plan-a").state == PlanningState.COMPLETED)

    lifecycle.reset()
    check("lifecycle reset", lifecycle.get("plan-a") is None)


async def test_planner() -> None:
    ctx = PlanningContext()

    def decomposer(goal: GoalSchema):
        return build_chain_tasks(goal, ["fetch", "analyze", "report"])

    ctx.decomposer.set_decomposer(decomposer)

    goals = GoalManager()
    goal = await goals.create("build an indexer")
    planner = Planner(ctx)
    plan = await planner.plan_from_goal(goal)

    check("planner goal id", plan.goal_id == goal.id)
    check("planner task count", len(plan.tasks) == 3)
    order = [task.name for task in plan.tasks]
    check("planner order", order == ["fetch", "analyze", "report"])
    check("planner deps", plan.tasks[1].dependencies == [plan.tasks[0].id])

    stored = await ctx.tasks.list(plan_id=plan.id)
    check("planner stored", len(stored) == 3)


async def test_executor() -> None:
    async def handler(task):
        return {"handled": task.name}

    def decomposer(goal: GoalSchema):
        return build_chain_tasks(goal, ["a", "b"])

    runtime = PlanningRuntime(task_handler=handler)
    runtime.context.decomposer.set_decomposer(decomposer)
    goal = await runtime.context.goals.create("run pipeline")
    plan = await runtime.planner.plan_from_goal(goal)
    executor = PlanExecutor(runtime.context)
    report = await executor.execute(plan)

    check("executor report type", isinstance(report, ExecutionReport))
    check("executor all succeeded", report.all_succeeded)
    check("executor succeeded count", report.succeeded == 2)
    check("executor result", report.results[plan.tasks[0].id] == {"handled": "a"})
    check(
        "executor task statuses",
        all(t.status == TaskStatus.SUCCEEDED for t in plan.tasks),
    )


async def test_coordinator() -> None:
    async def handler(task):
        return {"ok": task.id}

    runtime = PlanningRuntime(task_handler=handler)

    def decomposer(goal: GoalSchema):
        return build_chain_tasks(goal, ["x", "y"])

    runtime.context.decomposer.set_decomposer(decomposer)

    goal = await runtime.context.goals.create("coordinate")
    outcome = await runtime.coordinator.run_goal(goal)

    check("coordinator plan", outcome.plan is not None)
    check("coordinator execution", outcome.execution is not None)
    check("coordinator all succeeded", outcome.execution.all_succeeded)
    check("coordinator state", outcome.state == PlanningState.COMPLETED)
    check("coordinator valid", outcome.valid)
    check("coordinator reflection", "2 succeeded" in outcome.reflection_outcome)

    lifecycle = runtime.lifecycle.get(outcome.plan.id)
    check("coordinator lifecycle", lifecycle is not None)
    check("coordinator lifecycle state", lifecycle.state == PlanningState.COMPLETED)


async def test_orchestrator_goal_status() -> None:
    async def handler(task):
        return "done"

    runtime = PlanningRuntime(task_handler=handler)

    def decomposer(goal: GoalSchema):
        return build_chain_tasks(goal, ["only"])

    runtime.context.decomposer.set_decomposer(decomposer)

    goal = await runtime.context.goals.create("orchestrate")
    outcome = await runtime.orchestrator.run_goal(goal)

    updated = await runtime.context.goals.get(goal.id)
    check("orchestrator goal completed", updated.status == GoalStatus.COMPLETED)
    check("orchestrator state", outcome.state == PlanningState.COMPLETED)


async def test_dispatcher() -> None:
    ctx = PlanningContext()

    class Tool:
        def __init__(self, tool_id: str) -> None:
            self.id = tool_id
            self.description = "scan blockchain data"

    tool = Tool("chain-reader")
    dispatcher = Dispatcher(ctx)
    dispatcher.register_target(tool)

    goal = await GoalManager().create("use a tool")
    task = await ctx.tasks.create("scan", goal_id=goal.id)

    selected = await dispatcher.dispatch(task)
    check("dispatcher selected", selected.id == "chain-reader")


async def test_runtime_close() -> None:
    async def handler(task):
        return "ok"

    runtime = PlanningRuntime(task_handler=handler)
    await runtime.close()
    snapshot = runtime.snapshot
    check("runtime snapshot", "metrics" in snapshot)


async def main() -> int:
    print("core tests")
    await test_lifecycle()
    await test_planner()
    await test_executor()
    await test_coordinator()
    await test_orchestrator_goal_status()
    await test_dispatcher()
    await test_runtime_close()
    return summary("core")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
