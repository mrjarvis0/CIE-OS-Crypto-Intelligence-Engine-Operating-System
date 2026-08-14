"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.validator

Purpose:
    Plan validation for the planning subsystem.

Validates plan structure and task graphs for correctness: duplicate
identifiers, missing dependencies, cycles, and invalid references.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas import PlanSchema, TaskSchema
from planning.schemas.base import _now
from planning.utils.constants import MAX_DEPTH

logger = logging.getLogger("a01.planning.reasoning")


@dataclass(slots=True)
class ValidationIssue:
    """
    A single validation finding.

    Fields:
        * Task (or plan) identifier and message
        * Severity flag
    """

    task_id: str | None
    message: str
    critical: bool = True


@dataclass(slots=True)
class ValidationReport:
    """
    Result of validating a plan.

    Fields:
        * Plan identifier
        * Collected issues
        * Validation timestamp
    """

    plan_id: str
    issues: list[ValidationIssue] = field(default_factory=list)
    validated_at: datetime = field(default_factory=_now)

    @property
    def valid(self) -> bool:
        """Whether no critical issues were raised."""
        return not any(issue.critical for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "valid": self.valid,
            "issues": [
                {
                    "task_id": issue.task_id,
                    "message": issue.message,
                    "critical": issue.critical,
                }
                for issue in self.issues
            ],
            "validated_at": self.validated_at.isoformat(),
        }


class PlanValidator:
    """
    Validates plan structure and task graphs.

    Responsibilities:
        * Duplicate task identifier detection
        * Dependency resolution checks
        * Cycle detection
        * Depth limit enforcement
    """

    def validate(self, plan: PlanSchema) -> ValidationReport:
        """Validate a plan, returning a report of all findings."""
        report = ValidationReport(plan_id=plan.id)

        self._check_empty(plan, report)
        self._check_duplicates(plan, report)
        self._check_dependencies(plan, report)
        self._check_cycles(plan, report)
        self._check_depth(plan, report)

        logger.info(
            "plan %s validated: %s",
            plan.id,
            "valid" if report.valid else f"{len(report.issues)} issue(s)",
        )
        return report

    @staticmethod
    def _check_empty(plan: PlanSchema, report: ValidationReport) -> None:
        if not plan.tasks:
            report.issues.append(
                ValidationIssue(None, "plan has no tasks")
            )

    @staticmethod
    def _check_duplicates(
        plan: PlanSchema,
        report: ValidationReport,
    ) -> None:
        seen: set[str] = set()

        for task in plan.tasks:
            if task.id in seen:
                report.issues.append(
                    ValidationIssue(
                        task.id,
                        f"duplicate task id: {task.id}",
                    )
                )
            seen.add(task.id)

    @staticmethod
    def _check_dependencies(
        plan: PlanSchema,
        report: ValidationReport,
    ) -> None:
        task_ids = {task.id for task in plan.tasks}

        for task in plan.tasks:
            for dependency in task.dependencies:
                if dependency not in task_ids:
                    report.issues.append(
                        ValidationIssue(
                            task.id,
                            f"unknown dependency: {dependency}",
                        )
                    )

    @staticmethod
    def _check_cycles(plan: PlanSchema, report: ValidationReport) -> None:
        try:
            cycles = _find_cycles(plan.tasks)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("cycle detection failed: %s", exc)
            return

        for cycle in cycles:
            report.issues.append(
                ValidationIssue(
                    cycle[0] if cycle else None,
                    f"dependency cycle detected: {' -> '.join(cycle)}",
                )
            )

    @staticmethod
    def _check_depth(plan: PlanSchema, report: ValidationReport) -> None:
        depth = _max_depth(plan.tasks)

        if depth > MAX_DEPTH:
            report.issues.append(
                ValidationIssue(
                    None,
                    f"plan exceeds max depth: {depth} > {MAX_DEPTH}",
                    critical=False,
                )
            )


def _find_cycles(tasks: list[TaskSchema]) -> list[list[str]]:
    """Find all elementary cycles in a task dependency graph."""
    graph: dict[str, list[str]] = {
        task.id: list(task.dependencies) for task in tasks
    }
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []
    in_stack: set[str] = set()

    def visit(node: str) -> None:
        if node in in_stack:
            start = stack.index(node)
            cycle = stack[start:] + [node]
            if cycle not in cycles:
                cycles.append(cycle)
            return

        if node in visited:
            return

        visited.add(node)
        stack.append(node)
        in_stack.add(node)

        for neighbor in graph.get(node, []):
            if neighbor in graph:
                visit(neighbor)

        stack.pop()
        in_stack.remove(node)

    for node in graph:
        visit(node)

    return cycles


def _max_depth(tasks: list[TaskSchema]) -> int:
    """Compute the longest dependency chain in a task list."""
    graph: dict[str, list[str]] = {
        task.id: list(task.dependencies) for task in tasks
    }
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(node: str) -> int:
        if node in memo:
            return memo[node]

        if node in visiting:
            return 0

        parents = graph.get(node, [])
        visiting.add(node)

        if not parents:
            memo[node] = 0
        else:
            memo[node] = 1 + max(
                (depth(p) for p in parents if p in graph),
                default=0,
            )

        visiting.remove(node)
        return memo[node]

    return max((depth(task.id) for task in tasks), default=0)
