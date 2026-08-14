"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.attribution.confidence

Purpose:
    Attribution confidence scoring.
"""

from __future__ import annotations

from .heuristics import Heuristic


class AttributionConfidence:
    """
    Computes aggregate confidence from a set of heuristics.

    Conservative by design: a single confident label is preferred, but
    conflicting labels (disagreeing categories) dampen the result rather
    than being ignored.
    """

    def score(self, heuristics: list[Heuristic]) -> float:
        """
        Combine heuristic confidences into a single 0..1 score.

        Returns 0.0 for an empty set. When all heuristics agree on a
        category, the strongest confidence is used; disagreement reduces
        the score in proportion to the size of the majority block.
        """
        if not heuristics:
            return 0.0

        best = max(h.confidence for h in heuristics)
        categories = {h.category for h in heuristics}

        if len(categories) == 1:
            return max(0.0, min(1.0, best))

        # Conflicting categories: reward agreement, penalize discord.
        total = len(heuristics)
        majority = max(
            sum(1 for h in heuristics if h.category == cat) for cat in categories
        )
        agreement_ratio = majority / total
        score = best * agreement_ratio
        return max(0.0, min(1.0, round(score, 6)))
