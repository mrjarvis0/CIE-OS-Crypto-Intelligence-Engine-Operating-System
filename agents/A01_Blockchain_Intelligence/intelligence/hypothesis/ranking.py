"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.hypothesis.ranking

Purpose:
    Hypothesis ranking.
"""

from __future__ import annotations

from .generator import Hypothesis
from ..utils.ranking import top_n


class HypothesisRanker:
    """
    Ranks hypotheses by confidence.
    """

    def rank(self, hypotheses: list[Hypothesis], n: int | None = None) -> list[Hypothesis]:
        """
        Return hypotheses ordered by descending confidence.
        """
        ranked = top_n(hypotheses, key=lambda h: h.confidence, n=n or len(hypotheses))
        return ranked
