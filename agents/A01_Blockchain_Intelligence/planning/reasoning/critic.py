"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.critic

Purpose:
    Plan and task critique for the planning subsystem.

Reviews a plan or task for quality, feasibility, and completeness,
producing structured critiques with severity levels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from planning.schemas import PlanSchema, TaskSchema
from planning.schemas.base import _now

logger = logging.getLogger("a01.planning.reasoning")


class Severity(StrEnum):
    """
    Severity of a critique finding.
    """

    INFO = "info"

    WARNING = "warning"

    CRITICAL = "critical"


@dataclass(slots=True)
class Critique:
    """
    A single critique finding.

    Fields:
        * Target identifier and kind
        * Message and severity
        * Optional suggestion
    """

    target_id: str
    message: str
    severity: Severity = Severity.WARNING
    kind: str = "task"
    suggestion: str | None = None


@dataclass(slots=True)
class CritiqueReport:
    """
    Result of critiquing a plan or task.

    Fields:
        * Target identifier
        * Collected findings
        * Evaluation timestamp
    """

    target_id: str
    findings: list[Critique] = field(default_factory=list)
    critiqued_at: datetime = field(default_factory=_now)

    @property
    def passed(self) -> bool:
        """Whether no critical findings were raised."""
        return not any(
            finding.severity == Severity.CRITICAL
            for finding in self.findings
        )

    @property
    def critical_count(self) -> int:
        """Number of critical findings."""
        return self._count(Severity.CRITICAL)

    @property
    def warning_count(self) -> int:
        """Number of warning findings."""
        return self._count(Severity.WARNING)

    def _count(self, severity: Severity) -> int:
        return sum(
            1 for finding in self.findings if finding.severity == severity
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "passed": self.passed,
            "findings": [
                {
                    "target_id": finding.target_id,
                    "kind": finding.kind,
                    "severity": finding.severity.value,
                    "message": finding.message,
                    "suggestion": finding.suggestion,
                }
                for finding in self.findings
            ],
            "critiqued_at": self.critiqued_at.isoformat(),
        }


class Critic:
    """
    Reviews tasks and plans for quality issues.

    Responsibilities:
        * Task review
        * Plan review
        * Finding aggregation
    """

    def critique_task(self, task: TaskSchema) -> CritiqueReport:
        """Review a single task for quality and completeness."""
        report = CritiqueReport(target_id=task.id)

        if not task.name.strip():
            report.findings.append(
                Critique(task.id, "task name is empty", Severity.CRITICAL)
            )

        if task.timeout_seconds <= 0:
            report.findings.append(
                Critique(
                    task.id,
                    "task timeout must be positive",
                    Severity.CRITICAL,
                )
            )

        if task.max_retries < 0:
            report.findings.append(
                Critique(
                    task.id,
                    "task max_retries must be non-negative",
                    Severity.CRITICAL,
                )
            )

        if task.description == "" and task.input_data is None:
            report.findings.append(
                Critique(
                    task.id,
                    "task has no description or input data",
                    Severity.WARNING,
                    "provide a description or input to guide execution",
                )
            )

        self._register(report)
        return report

    def critique_plan(self, plan: PlanSchema) -> CritiqueReport:
        """Review a plan and its tasks for quality issues."""
        report = CritiqueReport(target_id=plan.id)

        if not plan.tasks:
            report.findings.append(
                Critique(plan.id, "plan has no tasks", Severity.CRITICAL)
            )

        if plan.goal is None:
            report.findings.append(
                Critique(
                    plan.id,
                    "plan has no associated goal",
                    Severity.WARNING,
                    "attach a goal to provide success criteria",
                )
            )

        task_ids = {task.id for task in plan.tasks}

        for task in plan.tasks:
            for dependency in task.dependencies:
                if dependency not in task_ids:
                    report.findings.append(
                        Critique(
                            task.id,
                            f"dependency {dependency!r} is not in the plan",
                            Severity.CRITICAL,
                        )
                    )

        self._register(report)
        return report

    @staticmethod
    def _register(report: CritiqueReport) -> None:
        logger.info(
            "critique finished for %s: %d findings",
            report.target_id,
            len(report.findings),
        )
