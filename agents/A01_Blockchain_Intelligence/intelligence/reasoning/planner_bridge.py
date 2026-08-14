"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.planner_bridge

Purpose:
    Bridge between the reasoning layer and the planning subsystem.

    Derives planning requests from reasoning traces by collecting the
    evidence-bearing steps (observations, premises, inferences,
    results, conclusions) that a planner needs as context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .reasoning_engine import ReasoningStep

# Step kinds that carry substance a planner can act on.
_EVIDENCE_KINDS = {
    "observation",
    "premise",
    "inference",
    "result",
    "conclusion",
    "branch",
}


@dataclass(slots=True)
class PlanRequest:
    """
    A request to the planning subsystem derived from reasoning.
    """

    goal: str
    reasoning_refs: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)


class PlannerBridge:
    """
    Translates reasoning conclusions into planning requests.
    """

    def to_plan(self, trace: list[ReasoningStep], goal: str | None = None) -> PlanRequest:
        """
        Build a planning request from a reasoning trace.

        Reasoning references collect the content of evidence-bearing
        steps in trace order, de-duplicated.
        """
        refs: list[str] = []
        seen: set[str] = set()
        for step in trace:
            if step.kind not in _EVIDENCE_KINDS or not step.content:
                continue
            if step.content in seen:
                continue
            seen.add(step.content)
            refs.append(step.content)
        return PlanRequest(
            goal=goal or "investigate subject",
            reasoning_refs=refs,
        )
