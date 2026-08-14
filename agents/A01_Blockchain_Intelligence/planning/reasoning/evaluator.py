"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.evaluator

Purpose:
    Result evaluation for the planning subsystem.

Evaluates task execution results against expected outcomes or
acceptance criteria, producing a scored evaluation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import _now

logger = logging.getLogger("a01.planning.reasoning")

CriterionCheck = Callable[[Any, Any], bool]


@dataclass(slots=True)
class EvaluationResult:
    """
    Outcome of evaluating an execution result.

    Fields:
        * Reference (task/plan) and result evaluated
        * Passed flag and score
        * Feedback items
        * Evaluation timestamp
    """

    reference_id: str
    passed: bool
    score: float = 0.0
    feedback: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "passed": self.passed,
            "score": self.score,
            "feedback": list(self.feedback),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


def _default_check(expected: Any, actual: Any) -> bool:
    """Default equality-based criterion check."""
    return expected == actual


class Evaluator:
    """
    Evaluates results against expectations.

    Responsibilities:
        * Criterion registration
        * Single- and multi-criterion evaluation
    """

    def __init__(self) -> None:
        self._criteria: dict[str, CriterionCheck] = {}

    def register(self, name: str, check: CriterionCheck) -> None:
        """Register a named criterion check."""
        self._criteria[name] = check

    def evaluate(
        self,
        reference_id: str,
        *,
        expected: Any = None,
        actual: Any = None,
        criteria: dict[str, CriterionCheck] | None = None,
    ) -> EvaluationResult:
        """
        Evaluate an actual result against expectations.

        When ``criteria`` is provided, each named criterion is evaluated
        against ``(expected, actual)``. Otherwise the expected/actual
        values are compared with the default check.
        """

        if criteria:
            return self._evaluate_many(
                reference_id,
                expected=expected,
                actual=actual,
                criteria=criteria,
            )

        return self._evaluate_one(reference_id, expected, actual)

    def _evaluate_one(
        self,
        reference_id: str,
        expected: Any,
        actual: Any,
    ) -> EvaluationResult:
        check = self._criteria.get("default", _default_check)

        try:
            passed = bool(check(expected, actual))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("default evaluation failed: %s", exc)
            passed = False

        feedback = (
            ["result matches expectation"]
            if passed
            else [f"expected {expected!r}, got {actual!r}"]
        )

        return EvaluationResult(
            reference_id=reference_id,
            passed=passed,
            score=1.0 if passed else 0.0,
            feedback=feedback,
        )

    def _evaluate_many(
        self,
        reference_id: str,
        *,
        expected: Any,
        actual: Any,
        criteria: dict[str, CriterionCheck],
    ) -> EvaluationResult:
        results: dict[str, bool] = {}
        feedback: list[str] = []

        for name, check in criteria.items():
            try:
                passed = bool(check(expected, actual))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("criterion %r evaluation failed: %s", name, exc)
                passed = False

            results[name] = passed
            feedback.append(
                f"{name}: {'passed' if passed else 'failed'}"
            )

        passed = all(results.values())
        score = (
            sum(results.values()) / len(results) if results else 0.0
        )

        return EvaluationResult(
            reference_id=reference_id,
            passed=passed,
            score=score,
            feedback=feedback,
        )
