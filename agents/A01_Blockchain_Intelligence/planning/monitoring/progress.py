"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.monitoring.progress

Purpose:
    Progress tracking for the planning subsystem.

Computes completion percentages and summaries for plans and task
batches so progress can be reported to a user or UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas import PlanSchema
from planning.schemas.base import _now
from planning.utils.constants import TaskStatus

logger = logging.getLogger("a01.planning.monitoring")

_TERMINAL_SUCCESS = (TaskStatus.SUCCEEDED,)
_TERMINAL_FAILURE = (
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.SKIPPED,
)


@dataclass(slots=True)
class ProgressReport:
    """
    Completion status for a plan.

    Fields:
        * Counts per task status
        * Percentages and summary line
        * Report timestamp
    """

    plan_id: str
    counts: dict[str, int] = field(default_factory=dict)
    total: int = 0
    generated_at: datetime = field(default_factory=_now)

    @property
    def completed(self) -> int:
        """Number of terminal-success tasks."""
        return self._sum(*_TERMINAL_SUCCESS)

    @property
    def failed(self) -> int:
        """Number of terminal-failure tasks."""
        return self._sum(*_TERMINAL_FAILURE)

    @property
    def pending(self) -> int:
        """Number of not-yet-terminal tasks."""
        return self.total - self.completed - self.failed

    @property
    def percent(self) -> float:
        """Percentage of tasks completed."""
        if self.total == 0:
            return 0.0
        return (self.completed / self.total) * 100.0

    def _sum(self, *statuses: TaskStatus) -> int:
        return sum(
            self.counts.get(status.value, 0) for status in statuses
        )

    def summary(self) -> str:
        """A human-readable summary line."""
        return (
            f"{self.percent:.1f}% complete "
            f"({self.completed}/{self.total} tasks done, "
            f"{self.pending} pending, {self.failed} failed)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "counts": dict(self.counts),
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "pending": self.pending,
            "percent": self.percent,
            "summary": self.summary(),
        }


class ProgressTracker:
    """
    Tracks completion of plan tasks.

    Responsibilities:
        * Status counting
        * Progress report generation
    """

    def report(self, plan: PlanSchema) -> ProgressReport:
        """Build a progress report from a plan's task statuses."""
        counts: dict[str, int] = {}

        for task in plan.tasks:
            status = task.status.value
            counts[status] = counts.get(status, 0) + 1

        report = ProgressReport(
            plan_id=plan.id,
            counts=counts,
            total=len(plan.tasks),
        )
        logger.info(
            "progress for plan %s: %s",
            plan.id,
            report.summary(),
        )
        return report

    @staticmethod
    def batch_report(
        task_statuses: list[TaskStatus],
        *,
        label: str = "batch",
    ) -> ProgressReport:
        """Build a progress report from a list of task statuses."""
        counts: dict[str, int] = {}

        for status in task_statuses:
            counts[status.value] = counts.get(status.value, 0) + 1

        return ProgressReport(
            plan_id=label,
            counts=counts,
            total=len(task_statuses),
        )
