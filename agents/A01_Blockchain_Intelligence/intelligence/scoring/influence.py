"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.influence

Purpose:
    Influence score.
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


class InfluenceScorer:
    """
    Computes a 0..100 influence score.
    """

    name = "influence"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        followers = _to_float(subject.get("followers", 0))
        reach = _to_float(subject.get("network_reach", 0))
        value = clamp(followers * 2 + reach * 3)
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
