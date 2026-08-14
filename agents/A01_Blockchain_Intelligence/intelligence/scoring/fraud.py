"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.fraud

Purpose:
    Fraud score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score
from .base import to_band


class FraudScorer:
    """
    Computes a 0..100 fraud score from fraud indicators.
    """

    name = "fraud"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        indicators = subject.get("fraud_indicators", [])
        value = min(100.0, 12.5 * len(indicators))
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
