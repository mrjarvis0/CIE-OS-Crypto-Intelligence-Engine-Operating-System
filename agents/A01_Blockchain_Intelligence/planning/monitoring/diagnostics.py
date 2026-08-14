"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.monitoring.diagnostics

Purpose:
    Diagnostic checks for the planning subsystem.

Runs self-checks over the planning stack (dependencies, graphs,
schema validity) and reports health status.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas import PlanSchema
from planning.schemas.base import _now
from planning.utils.ids import generate_correlation_id

logger = logging.getLogger("a01.planning.monitoring")

Check = Callable[[], tuple[bool, str]]


@dataclass(slots=True)
class CheckResult:
    """
    Outcome of a single diagnostic check.

    Fields:
        * Name and pass flag
        * Detail message
    """

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(slots=True)
class DiagnosticReport:
    """
    Aggregated diagnostics for a planning run.

    Fields:
        * Correlation identifier
        * Individual check results
        * Overall healthy flag
    """

    correlation_id: str = field(default_factory=generate_correlation_id)
    checks: list[CheckResult] = field(default_factory=list)
    generated_at: datetime = field(default_factory=_now)

    @property
    def healthy(self) -> bool:
        """Whether all checks passed."""
        return bool(self.checks) and all(
            check.passed for check in self.checks
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "healthy": self.healthy,
            "checks": [check.to_dict() for check in self.checks],
            "generated_at": self.generated_at.isoformat(),
        }


class Diagnostics:
    """
    Runs registered diagnostic checks.

    Responsibilities:
        * Check registration
        * Standard plan checks
        * Report generation
    """

    def __init__(self) -> None:
        self._checks: dict[str, Check] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._checks["task_ids_unique"] = lambda: (True, "ok")

    def register(self, name: str, check: Check) -> None:
        """Register a named diagnostic check."""
        self._checks[name] = check

    def run_plan_checks(self, plan: PlanSchema) -> DiagnosticReport:
        """Run the standard plan diagnostics."""
        report = DiagnosticReport()

        task_ids = [task.id for task in plan.tasks]
        unique = len(task_ids) == len(set(task_ids))
        report.checks.append(
            CheckResult(
                "task_ids_unique",
                unique,
                "no duplicates" if unique else f"{len(task_ids) - len(set(task_ids))} duplicate(s)",
            )
        )

        all_named = all(task.name.strip() for task in plan.tasks)
        report.checks.append(
            CheckResult(
                "tasks_named",
                all_named,
                "all tasks named" if all_named else "unnamed task(s) present",
            )
        )

        valid_goal = plan.goal is not None or bool(plan.goal_id)
        report.checks.append(
            CheckResult(
                "goal_attached",
                valid_goal,
                "goal present" if valid_goal else "no goal attached",
            )
        )

        for name, check in self._checks.items():
            if any(c.name == name for c in report.checks):
                continue

            try:
                passed, detail = check()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("diagnostic %r failed: %s", name, exc)
                passed, detail = False, str(exc)

            report.checks.append(CheckResult(name, passed, detail))

        logger.info(
            "diagnostics for plan %s: healthy=%s",
            plan.id,
            report.healthy,
        )
        return report
