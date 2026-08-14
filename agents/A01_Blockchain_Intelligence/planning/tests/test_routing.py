"""
Tests for planning.routing.

Covers strategies, the router, policies, and tool/agent selectors.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.routing import (
    AgentSelector,
    BestScoreStrategy,
    NoRouteFoundError,
    RoutingPolicy,
    Router,
    ToolSelector,
    build_strategy,
    default_scorer,
)
from planning.schemas import TaskSchema
from planning.utils.constants import RoutingStrategy
from planning.tests import check, summary


class FakeTarget:
    """Minimal routable target for tests."""

    def __init__(self, target_id: str, description: str) -> None:
        self.id = target_id
        self.description = description

    def __repr__(self) -> str:
        return f"FakeTarget({self.id})"


def task_for(name: str, description: str) -> TaskSchema:
    return TaskSchema(name=name, description=description)


def test_scoring() -> None:
    task = task_for("scan chain", "scan the blockchain for activity")
    target = FakeTarget("chain-scanner", "scan the blockchain for activity")

    score = default_scorer(task, target)
    check("scorer overlap positive", score > 0)

    unrelated = FakeTarget("reporter", "generate reports")
    score = default_scorer(task, unrelated)
    check("scorer unrelated zero", score == 0)


def test_strategies() -> None:
    task = task_for("scan chain", "scan the blockchain for activity")
    targets = [
        FakeTarget("reporter", "generate reports"),
        FakeTarget("scanner", "scan the blockchain for activity"),
    ]

    first = build_strategy(RoutingStrategy.FIRST_MATCH)
    result = first.select(task, targets, scorer=default_scorer)
    check("first match strategy", result.candidate_id == "scanner")

    best = BestScoreStrategy()
    result = best.select(task, targets, scorer=default_scorer)
    check("best score strategy", result.candidate_id == "scanner")
    check("best score > 0", result.score > 0)

    round_robin = build_strategy(RoutingStrategy.ROUND_ROBIN)
    first_route = round_robin.select(task, targets)
    second_route = round_robin.select(task, targets)
    check("round robin rotates", first_route.candidate_id != second_route.candidate_id)

    fallback = build_strategy(RoutingStrategy.FALLBACK)
    result = fallback.select(task, targets, scorer=default_scorer)
    check("fallback selects best", result.candidate_id == "scanner")


def test_router() -> None:
    router = Router()
    scanner = FakeTarget("scanner", "scan the blockchain for activity")
    reporter = FakeTarget("reporter", "generate reports")
    router.register(scanner)
    router.register(reporter)

    task = task_for("scan chain", "scan the blockchain for activity")
    result = router.route(task)
    check("router first match", result.candidate_id == "scanner")
    check("router strategy name", result.strategy == RoutingStrategy.FIRST_MATCH.value)

    result = router.route(task, strict=True)
    check("router strict ok", result.candidate_id == "scanner")

    router.set_strategy(RoutingStrategy.BEST_SCORE)
    result = router.route(task)
    check("router best score", result.candidate_id == "scanner")

    router.unregister("scanner")
    router.unregister("reporter")
    try:
        router.route(task, strict=True)
        raise AssertionError("expected no route error")
    except NoRouteFoundError:
        pass


def test_router_policy() -> None:
    router = Router()
    router.register(FakeTarget("a", "alpha service for scanning"))
    router.register(FakeTarget("b", "beta service for analysis"))

    policy = RoutingPolicy()
    policy.deny({"a"})
    router.set_policy(policy)

    task = task_for("analysis", "perform analysis on the chain")
    result = router.route(task, strict=True)
    check("policy denies a", result.candidate_id == "b")

    policy.allow_only({"a"})
    router.set_policy(policy)
    try:
        router.route(task, strict=True)
        raise AssertionError("expected no route error")
    except NoRouteFoundError:
        pass


def test_policy_capacity() -> None:
    policy = RoutingPolicy()
    policy.set_capacity("a", 1)
    policy.record_usage("a")
    target = FakeTarget("a", "alpha")
    decision = policy.check(task_for("t", "d"), [target])
    check("policy capacity blocks", decision.candidates == [])

    policy = RoutingPolicy()
    policy.set_capacity("a", 2)
    policy.record_usage("a")
    decision = policy.check(task_for("t", "d"), [target])
    check("policy capacity allows", decision.candidates == [target])


def test_tool_selector() -> None:
    selector = ToolSelector()
    tool = FakeTarget("chain-reader", "read the blockchain for analysis")
    selector.register(tool)

    task = task_for("read chain", "read the blockchain for analysis")
    selected = selector.select(task, strict=True)
    check("tool selected", selected.candidate_id == "chain-reader")
    check("tool list", len(selector.list()) == 1)
    check("tool get", selector.get("chain-reader").id == "chain-reader")


def test_agent_selector() -> None:
    selector = AgentSelector()
    agent = FakeTarget("analyst", "analyze blockchain transactions")
    selector.register(agent)

    task = task_for("analyze txn", "analyze blockchain transactions")
    selected = selector.select(task, strict=True)
    check("agent selected", selected.candidate_id == "analyst")
    check("agent list", len(selector.list()) == 1)


def main() -> int:
    print("routing tests")
    test_scoring()
    test_strategies()
    test_router()
    test_router_policy()
    test_policy_capacity()
    test_tool_selector()
    test_agent_selector()
    return summary("routing")


if __name__ == "__main__":
    raise SystemExit(main())
