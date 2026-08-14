"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.hypothesis.elimination

Purpose:
    Hypothesis elimination.
"""

from __future__ import annotations

from .generator import Hypothesis


class HypothesisEliminator:
    """
    Removes contradicted hypotheses from a candidate set.
    """

    def eliminate(self, hypotheses: list[Hypothesis], threshold: float = 0.3) -> list[Hypothesis]:
        """
        Return hypotheses whose confidence exceeds the threshold.
        """
        return [h for h in hypotheses if h.confidence > threshold]
