"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.trust

Purpose:
    Trust score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score
from .base import clamp, to_band


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TrustScorer:
    """
    Computes a 0..100 trust score from positive signals.
    """

    name = "trust"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        age_years = _to_float(subject.get("age_years", 0))
        verified = bool(subject.get("verified", False))
        value = clamp(age_years * 10 + (30 if verified else 0))
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
