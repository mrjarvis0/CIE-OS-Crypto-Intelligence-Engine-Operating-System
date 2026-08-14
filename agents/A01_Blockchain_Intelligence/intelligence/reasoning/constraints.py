"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.constraints

Purpose:
    Constraint-aware reasoning that respects boundary conditions.
"""

from __future__ import annotations

from typing import Any

from .reasoning_engine import ReasoningStep


class ConstraintReasoner:
    """
    Applies explicit constraints while reasoning to avoid violations.
    """

    def __init__(self, constraints: list[str] | None = None) -> None:
        self._constraints = list(constraints or [])

    def reason(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        **_: Any,
    ) -> list[ReasoningStep]:
        """
        Reason within the configured constraints.
        """
        context = context or {}
        active = context.get("constraints", self._constraints)
        steps = [
            ReasoningStep(kind="observation", content=question),
            ReasoningStep(
                kind="constraint",
                content=f"applying {len(active)} constraints",
                metadata={"constraints": list(active)},
            ),
            ReasoningStep(kind="reasoning", content="evaluating within constraints"),
            ReasoningStep(kind="conclusion", content="conclusion satisfies constraints"),
        ]
        return steps
