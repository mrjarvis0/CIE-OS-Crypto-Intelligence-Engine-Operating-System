"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.hypothesis.generator

Purpose:
    Hypothesis generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Hypothesis:
    """
    A testable assumption about a subject.
    """

    hypothesis_id: str
    statement: str
    supporting: list[str] = field(default_factory=list)
    opposing: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "untested"

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "supporting": list(self.supporting),
            "opposing": list(self.opposing),
            "confidence": self.confidence,
            "status": self.status,
        }


class HypothesisGenerator:
    """
    Generates hypotheses from observations.
    """

    def generate(self, observations: list[str], prefix: str = "hyp") -> list[Hypothesis]:
        """
        Turn observations into untested hypotheses.
        """
        return [
            Hypothesis(
                hypothesis_id=f"{prefix}-{i}",
                statement=obs,
            )
            for i, obs in enumerate(observations)
        ]
