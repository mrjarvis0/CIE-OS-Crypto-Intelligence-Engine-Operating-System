"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.reputation

Purpose:
    Reputation score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score
from .base import to_band


class ReputationScorer:
    """
    Computes a 0..100 reputation score.
    """

    name = "reputation"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        positive = subject.get("positive_signals", 0)
        negative = subject.get("negative_signals", 0)
        base = 50.0
        value = base + (positive * 5) - (negative * 10)
        value = max(0.0, min(100.0, value))
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
