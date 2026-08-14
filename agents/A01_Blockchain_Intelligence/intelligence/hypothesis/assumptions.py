"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.hypothesis.assumptions

Purpose:
    Assumption tracking for hypotheses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Assumption:
    """
    An assumption underlying a hypothesis.
    """

    description: str
    confidence: float = 0.5
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "confidence": self.confidence,
            "risks": list(self.risks),
        }


class AssumptionTracker:
    """
    Records assumptions and their confidence.
    """

    def __init__(self) -> None:
        self._assumptions: list[Assumption] = []

    def add(self, description: str, confidence: float = 0.5, risks: list[str] | None = None) -> None:
        """
        Record an assumption.
        """
        self._assumptions.append(
            Assumption(description=description, confidence=confidence, risks=risks or [])
        )

    def all(self) -> list[Assumption]:
        """
        Return all recorded assumptions.
        """
        return list(self._assumptions)

    def average_confidence(self) -> float:
        """
        Average confidence across assumptions.
        """
        if not self._assumptions:
            return 0.0
        return sum(a.confidence for a in self._assumptions) / len(self._assumptions)
