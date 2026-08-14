"""
Tests for planning.reasoning.

Covers critic, evaluator, reflection, validator, verifier,
retry analysis, and replanning.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.reasoning import (
    Critic,
    Evaluator,
    PlanValidator,
    Replanner,
    RetryAnalyzer,
    Reflector,
    Severity,
    Verifier,
)
from planning.schemas import PlanSchema, TaskSchema
from planning.utils.constants import RetryPolicy, TaskStatus
from planning.tests import check, summary


def test_critic() -> None:
    critic = Critic()

    bad_task = TaskSchema(name="", description="")
    report = critic.critique_task(bad_task)
    check("critic rejects blank", not report.passed)
    check("critic critical finding", report.critical_count >= 1)
    check(
        "critic severity",
        any(f.severity == Severity.CRITICAL for f in report.findings),
    )

    good_task = TaskSchema(name="scan chain", description="query the ledger")
    good_report = critic.critique_task(good_task)
    check("critic accepts good", good_report.critical_count == 0)

    plan = PlanSchema(
        goal_id="goal-1",
        name="p",
        tasks=[
            TaskSchema(name="a", description="d"),
            TaskSchema(name="b", description="d", dependencies=["ghost"]),
        ],
    )
    plan_report = critic.critique_plan(plan)
    check("critic catches ghost dep", plan_report.critical_count >= 1)
    check(
        "critic ghost message",
        any("ghost" in f.message for f in plan_report.findings),
    )


def test_evaluator() -> None:
    evaluator = Evaluator()

    result = evaluator.evaluate("task-1", expected=42, actual=42)
    check("evaluator exact pass", result.passed)
    check("evaluator exact score", result.score == 1.0)

    result = evaluator.evaluate("task-2", expected=42, actual=41)
    check("evaluator mismatch fail", not result.passed)
    check("evaluator mismatch score", result.score == 0.0)

    result = evaluator.evaluate(
        "task-3",
        expected=10,
        actual=10,
        criteria={
            "positive": lambda e, a: a > 0,
            "equal": lambda e, a: a == e,
        },
    )
    check("evaluator criteria pass", result.passed)
    check("evaluator criteria score", result.score == 1.0)


def test_reflection() -> None:
    reflector = Reflector()
    plan = PlanSchema(
        goal_id="goal-1",
        name="p",
        tasks=[
            TaskSchema(name="a", description="d"),
            TaskSchema(name="b", description="d"),
            TaskSchema(name="c", description="d"),
        ],
    )
    reflection = reflector.reflect(
        plan,
        outcomes={
            plan.tasks[0].id: {"status": "succeeded"},
            plan.tasks[1].id: {"status": "failed"},
            plan.tasks[2].id: {"status": "succeeded"},
        },
    )
    check("reflection outcome text", "2 succeeded, 1 failed" in reflection.outcome)
    check("reflection strengths", bool(reflection.strengths))
    check("reflection suggestions", bool(reflection.suggestions))
    check("reflection plan id", reflection.plan_id == plan.id)


def test_validator() -> None:
    validator = PlanValidator()

    empty = PlanSchema(goal_id="g", name="empty")
    report = validator.validate(empty)
    check("validator rejects empty", not report.valid)

    dup = PlanSchema(
        goal_id="g",
        name="dup",
        tasks=[
            TaskSchema(name="a", description="d"),
            TaskSchema(name="b", description="d"),
        ],
    )
    dup.tasks[1].id = dup.tasks[0].id
    dup_report = validator.validate(dup)
    check("validator rejects duplicate", not dup_report.valid)
    check(
        "validator duplicate issue",
        any("duplicate" in i.message for i in dup_report.issues),
    )

    cyclic = PlanSchema(
        goal_id="g",
        name="cyc",
        tasks=[
            TaskSchema(name="a", description="d"),
            TaskSchema(name="b", description="d"),
        ],
    )
    a, b = cyclic.tasks
    a.dependencies = [b.id]
    b.dependencies = [a.id]
    cycle_report = validator.validate(cyclic)
    check("validator rejects cycle", not cycle_report.valid)
    check(
        "validator cycle issue",
        any("cycle" in i.message for i in cycle_report.issues),
    )

    missing = PlanSchema(
        goal_id="g",
        name="miss",
        tasks=[
            TaskSchema(name="a", description="d", dependencies=["nope"]),
        ],
    )
    miss_report = validator.validate(missing)
    check("validator rejects unknown dep", not miss_report.valid)
    check(
        "validator unknown dep issue",
        any("unknown dependency" in i.message for i in miss_report.issues),
    )


def test_verifier() -> None:
    verifier = Verifier()
    verifier.register("non_empty", lambda out: bool(out))
    verifier.register("is_list", lambda out: isinstance(out, list))

    result = verifier.verify("task-1", output=[1, 2, 3])
    check("verifier passes", result.verified)

    bad = verifier.verify("task-2", output={})
    check("verifier fails", not bad.verified)

    bare = Verifier()
    try:
        bare.verify("task-3", output=5)
        raise AssertionError("expected ValueError")
    except ValueError:
        check("verifier bare raises", True)


def test_retry() -> None:
    analyzer = RetryAnalyzer()

    no_retry = TaskSchema(name="t", description="d")
    no_retry.retry_policy = RetryPolicy.NONE
    decision = analyzer.decide(no_retry, error="boom", attempts_used=1)
    check("retry policy none", not decision.should_retry)

    budget = TaskSchema(name="t", description="d")
    decision = analyzer.decide(
        budget,
        error="boom",
        attempts_used=budget.max_retries,
    )
    check("retry budget exhausted", not decision.should_retry)

    transient = TaskSchema(name="t", description="d")
    decision = analyzer.decide(
        transient,
        error="connection timed out",
        attempts_used=1,
    )
    check("retry transient", decision.should_retry)
    check(
        "retry remaining",
        decision.remaining_attempts == transient.max_retries - 1,
    )

    permanent = TaskSchema(name="t", description="d")
    decision = analyzer.decide(
        permanent,
        error="permission denied",
        attempts_used=1,
    )
    check("retry permanent", not decision.should_retry)


def test_replanner() -> None:
    replanner = Replanner()
    task = TaskSchema(name="a", description="d")
    ok = TaskSchema(name="b", description="d")
    ok.status = TaskStatus.SUCCEEDED

    plan = PlanSchema(goal_id="g", name="p", tasks=[task, ok])
    result = replanner.replan(plan, failures={task.id: "boom"})
    check("replanner task count", len(result.tasks) == 2)
    check("replanner reset status", result.tasks[0].status == TaskStatus.PENDING)
    check("replanner error kept", result.tasks[0].error == "boom")
    check("replanner keep succeeded", result.tasks[1].status == TaskStatus.SUCCEEDED)
    check("replanner revisions", len(result.revisions) == 2)
    check("replanner reset kind", any(r.kind == "reset" for r in result.revisions))
    check("replanner keep kind", any(r.kind == "keep" for r in result.revisions))


def main() -> int:
    print("reasoning tests")
    test_critic()
    test_evaluator()
    test_reflection()
    test_validator()
    test_verifier()
    test_retry()
    test_replanner()
    return summary("reasoning")


if __name__ == "__main__":
    raise SystemExit(main())
