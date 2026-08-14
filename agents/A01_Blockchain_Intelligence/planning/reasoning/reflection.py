"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.reflection

Purpose:
    Post-execution reflection for the planning subsystem.

Captures lessons learned from a plan run and produces improvement
suggestions for future planning cycles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas import PlanSchema
from planning.schemas.base import _now

logger = logging.getLogger("a01.planning.reasoning")


@dataclass(slots=True)
class Reflection:
    """
    Structured reflection on a plan run.

    Fields:
        * Plan reference and outcome
        * Strengths and weaknesses
        * Improvement suggestions
        * Reflection timestamp
    """

    plan_id: str
    outcome: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reflected_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "outcome": self.outcome,
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "suggestions": list(self.suggestions),
            "reflected_at": self.reflected_at.isoformat(),
        }


class Reflector:
    """
    Produces reflections from plan execution records.

    Responsibilities:
        * Analyzing execution statistics
        * Deriving strengths and weaknesses
        * Generating improvement suggestions
    """

    def reflect(
        self,
        plan: PlanSchema,
        *,
        outcomes: dict[str, Any] | None = None,
    ) -> Reflection:
        """
        Reflect on a plan run.

        Parameters
        ----------
        plan
            The executed plan.
        outcomes
            Optional mapping of task id to execution outcome (dict
            with keys such as ``status`` or ``success``).
        """

        outcomes = outcomes or {}
        reflection = Reflection(plan_id=plan.id)

        if outcomes:
            self._analyze(plan, outcomes, reflection)
        else:
            reflection.outcome = "no execution outcomes provided"

        self._derive_suggestions(reflection)
        logger.info(
            "reflection produced for plan %s: %d suggestions",
            plan.id,
            len(reflection.suggestions),
        )
        return reflection

    @staticmethod
    def _analyze(
        plan: PlanSchema,
        outcomes: dict[str, Any],
        reflection: Reflection,
    ) -> None:
        succeeded = 0
        failed = 0

        for task in plan.tasks:
            outcome = outcomes.get(task.id, {})

            if isinstance(outcome, dict):
                status = outcome.get("status", outcome.get("success"))
                success = (
                    status is True
                    or str(status).lower() in ("succeeded", "success")
                )
            else:
                success = bool(outcome)

            if success:
                succeeded += 1
            else:
                failed += 1

        reflection.outcome = (
            f"{succeeded} succeeded, {failed} failed"
        )

        if succeeded > failed:
            reflection.strengths.append("majority of tasks succeeded")
        elif failed > succeeded:
            reflection.weaknesses.append("majority of tasks failed")
        else:
            reflection.weaknesses.append("mixed success across tasks")

    @staticmethod
    def _derive_suggestions(reflection: Reflection) -> None:
        if reflection.weaknesses:
            reflection.suggestions.append(
                "investigate failed tasks before planning the next cycle"
            )
            return

        reflection.suggestions.append(
            "carry validated patterns forward into the next cycle"
        )
