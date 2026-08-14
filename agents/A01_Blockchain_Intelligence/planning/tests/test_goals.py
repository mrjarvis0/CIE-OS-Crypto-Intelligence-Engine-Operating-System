"""
Tests for planning.goals.

Covers the goal lifecycle, objectives, assumptions, constraints, and
success evaluation.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.goals import (
    AssumptionManager,
    ConstraintManager,
    GoalManager,
    GoalNotFoundError,
    InvalidGoalTransitionError,
    ObjectiveManager,
    SuccessError,
    SuccessEvaluator,
)
from planning.schemas import GoalSchema
from planning.utils.constants import GoalStatus, Priority
from planning.tests import check, summary


async def test_goal_manager() -> None:
    manager = GoalManager()
    goal = await manager.create(
        "build an indexer",
        objective="index chain data",
        constraints=["no spam"],
        acceptance_criteria=["index ready"],
        priority=Priority.HIGH,
    )

    check("goal created", goal.status == GoalStatus.NEW)
    check("goal listed", len(await manager.list()) == 1)

    fetched = await manager.get(goal.id)
    check("goal fetched", fetched.id == goal.id)

    try:
        await manager.get("missing")
        raise AssertionError("expected not found")
    except GoalNotFoundError:
        pass

    await manager.set_status(goal.id, GoalStatus.UNDERSTOOD)
    await manager.set_status(goal.id, GoalStatus.CONSTRAINED)
    await manager.set_status(goal.id, GoalStatus.DECOMPOSED)
    await manager.set_status(goal.id, GoalStatus.READY)
    await manager.set_status(goal.id, GoalStatus.IN_PROGRESS)
    await manager.set_status(goal.id, GoalStatus.COMPLETED)

    completed = await manager.get(goal.id)
    check("goal completed", completed.status == GoalStatus.COMPLETED)

    try:
        await manager.set_status(goal.id, GoalStatus.NEW)
        raise AssertionError("expected invalid transition")
    except InvalidGoalTransitionError:
        pass

    snapshots = await manager.snapshot()
    check("goal snapshot count", len(snapshots) == 1)
    await manager.clear()
    check("goal cleared", len(await manager.list()) == 0)
    restored = await manager.restore(snapshots)
    check("goal restored", restored == 1)


async def test_goal_transition_order() -> None:
    manager = GoalManager()
    goal = await manager.create("walk the path")

    # The orchestrator path must be walkable sequentially.
    path = [
        GoalStatus.UNDERSTOOD,
        GoalStatus.CONSTRAINED,
        GoalStatus.DECOMPOSED,
        GoalStatus.READY,
        GoalStatus.IN_PROGRESS,
        GoalStatus.COMPLETED,
    ]

    for status in path:
        await manager.set_status(goal.id, status)

    final = await manager.get(goal.id)
    check("goal walked full path", final.status == GoalStatus.COMPLETED)


async def test_goals_status_to_completed_blocked() -> None:
    manager = GoalManager()
    goal = await manager.create("cannot jump")
    try:
        await manager.set_status(goal.id, GoalStatus.IN_PROGRESS)
        raise AssertionError("expected invalid transition")
    except InvalidGoalTransitionError:
        pass


async def test_objectives() -> None:
    manager = ObjectiveManager()
    goal = GoalSchema(description="d")
    first = await manager.create(goal.id, "index data")
    second = await manager.create(goal.id, "verify data")

    check("objectives for goal", len(await manager.list_for_goal(goal.id)) == 2)
    await manager.mark_completed(first.id)
    completed = await manager.get(first.id)
    check("objective completed", completed.completed)

    snapshots = await manager.snapshot()
    await manager.clear()
    check("objectives cleared", len(await manager.list_for_goal(goal.id)) == 0)
    restored = await manager.restore(snapshots)
    check("objectives restored", restored == 2)


async def test_assumptions() -> None:
    manager = AssumptionManager()
    goal = GoalSchema(description="d")
    assumption = await manager.create(goal.id, "chain is reachable", confidence=0.8)

    check("assumption created", assumption.confidence == 0.8)
    check("assumption unverified", len(await manager.unverified()) == 1)

    await manager.verify(assumption.id)
    updated = await manager.get(assumption.id)
    check("assumption verified", updated.verified)
    check("assumption verified note", updated.note == "verified")


async def test_constraints() -> None:
    manager = ConstraintManager()
    goal = GoalSchema(description="d")

    await manager.create(
        goal.id,
        "budget must fit",
        predicate=lambda candidate: None
        if candidate.get("cost", 0) <= 100
        else "budget exceeded",
    )
    await manager.create(goal.id, "no predicate constraint")

    report = await manager.evaluate(goal.id, {"cost": 50})
    check("constraints pass", report.passed)
    check("constraint no violations", len(report.violations) == 0)

    report = await manager.evaluate(goal.id, {"cost": 500})
    check("constraints fail", not report.passed)
    check("constraint violation", len(report.violations) == 1)


async def test_success() -> None:
    goal = GoalSchema(
        description="d",
        acceptance_criteria=["index built", "data verified"],
    )
    evaluator = SuccessEvaluator()
    evaluator.register(
        goal.id,
        "data verified",
        lambda g, result: (result.get("verified") is True, "verified"),
    )

    report = await evaluator.evaluate(
        goal,
        {"index": True, "verified": True},
    )
    check("success report passed", report.passed)
    check("success passed criteria", len(report.passed_criteria) == 2)
    check("success failed criteria", len(report.failed_criteria) == 0)

    report = await evaluator.evaluate(
        goal,
        {"index": True, "verified": False},
    )
    check("success report failed", not report.passed)
    check("success failed criteria", report.failed_criteria == ["data verified"])

    payload = report.to_dict()
    check("success report dict", payload["goal_id"] == goal.id)

    empty = GoalSchema(description="d")
    try:
        await evaluator.evaluate(empty, True)
        raise AssertionError("expected success error")
    except SuccessError:
        pass


async def main() -> int:
    print("goals tests")
    await test_goal_manager()
    await test_goal_transition_order()
    await test_goals_status_to_completed_blocked()
    await test_objectives()
    await test_assumptions()
    await test_constraints()
    await test_success()
    return summary("goals")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
