"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.decision

Purpose:
    Convert reasoned conclusions into explicit decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .reasoning_engine import ReasoningStep


@dataclass(slots=True)
class Decision:
    """
    A concrete decision derived from reasoning.
    """

    decision: str
    confidence: float = 0.5
    rationale: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "options": self.options,
        }


class DecisionEngine:
    """
    Produces a decision from a reasoning trace.

    When explicit options (each with a score/weight) are provided, the
    best-supported option is selected; otherwise the final conclusion
    step of the trace is used. Confidence is carried from the conclusion
    step's metadata when present.
    """

    def decide(
        self, trace: list[ReasoningStep], options: list[dict[str, Any]] | None = None
    ) -> Decision:
        """
        Derive a decision from options or the final conclusion step.
        """
        if options:
            scored = sorted(
                options,
                key=lambda o: float(o.get("score", 0.0)),
                reverse=True,
            )
            best = scored[0]
            return Decision(
                decision=str(best.get("name", best.get("decision", "selected"))),
                confidence=float(best.get("confidence", 0.5)),
                rationale=str(best.get("rationale", "")),
                options=list(options),
            )

        conclusion = "no conclusion reached"
        confidence = 0.5
        for step in reversed(trace):
            if step.kind in {"conclusion", "result"}:
                conclusion = step.content
                confidence = float(step.metadata.get("confidence", 0.5))
                break
        return Decision(
            decision=conclusion,
            confidence=confidence,
            options=[],
        )
