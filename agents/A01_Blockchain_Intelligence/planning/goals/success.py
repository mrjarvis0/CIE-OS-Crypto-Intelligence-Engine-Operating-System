"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.goals.success

Purpose:
    Success evaluation for the planning subsystem.

Evaluates whether a goal's acceptance criteria have been satisfied
after execution, producing a structured report.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import _now
from planning.schemas import GoalSchema

logger = logging.getLogger("a01.planning.goals")

CriterionCheck = Callable[[GoalSchema, Any], tuple[bool, str]]


class SuccessError(Exception):
    """
    Base class for success evaluation failures.
    """


@dataclass(slots=True)
class SuccessReport:
    """
    Result of evaluating a goal's success.

    Fields:
        * Per-criterion outcomes
        * Aggregate verdict
        * Evaluation timestamp
    """

    goal_id: str
    results: dict[str, tuple[bool, str]] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=_now)

    @property
    def passed(self) -> bool:
        return all(passed for passed, _ in self.results.values())

    @property
    def passed_criteria(self) -> list[str]:
        return [
            criterion
            for criterion, (passed, _) in self.results.items()
            if passed
        ]

    @property
    def failed_criteria(self) -> list[str]:
        return [
            criterion
            for criterion, (passed, _) in self.results.items()
            if not passed
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "passed": self.passed,
            "results": {
                criterion: {"passed": passed, "note": note}
                for criterion, (passed, note) in self.results.items()
            },
            "evaluated_at": self.evaluated_at.isoformat(),
        }


def _default_check(goal: GoalSchema, result: Any) -> tuple[bool, str]:
    """
    Default criterion check.

    A criterion passes when ``result`` is truthy. If ``result`` is a dict
    or list, the criterion passes when it is non-empty.
    """

    if isinstance(result, (dict, list, str)):
        passed = bool(result)
    else:
        passed = result is not None

    note = "non-empty" if passed and isinstance(result, (dict, list, str)) else ""

    if result is True:
        note = "explicitly satisfied"

    return passed, note


class SuccessEvaluator:
    """
    Evaluates acceptance criteria against execution results.

    Responsibilities:
        * Criterion registration per goal
        * Report generation
    """

    def __init__(self) -> None:
        self._checks: dict[tuple[str, str], CriterionCheck] = {}

    def register(
        self,
        goal_id: str,
        criterion: str,
        check: CriterionCheck | None = None,
    ) -> None:
        """Register a check for a goal criterion."""
        self._checks[(goal_id, criterion)] = check or _default_check

    async def evaluate(
        self,
        goal: GoalSchema,
        result: Any,
    ) -> SuccessReport:
        """
        Evaluate all acceptance criteria of a goal against a result.

        Criteria without a registered check use the default truthiness
        check. Raises SuccessError when the goal has no criteria.
        """

        if not goal.acceptance_criteria:
            raise SuccessError(
                f"goal has no acceptance criteria: {goal.id}"
            )

        report = SuccessReport(goal_id=goal.id)

        for criterion in goal.acceptance_criteria:
            check = self._checks.get((goal.id, criterion), _default_check)

            try:
                passed, note = check(goal, result)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("criterion %r evaluation failed: %s", criterion, exc)
                passed, note = False, str(exc)

            report.results[criterion] = (passed, note)

        logger.info(
            "goal %s success evaluated: %s/%s passed",
            goal.id,
            len(report.passed_criteria),
            len(report.results),
        )
        return report
