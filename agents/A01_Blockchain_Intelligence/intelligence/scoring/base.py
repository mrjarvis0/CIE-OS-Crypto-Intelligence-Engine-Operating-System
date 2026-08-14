"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.base

Purpose:
    Shared helpers for scoring modules.
"""

from __future__ import annotations

from ..schemas.score import ScoreBand
from ..utils.constants import (
    SCORE_CRITICAL_MIN,
    SCORE_HIGH_MIN,
    SCORE_LOW_MIN,
    SCORE_MEDIUM_MIN,
)


def to_band(value: float) -> ScoreBand:
    """
    Map a 0..100 score to a qualitative band.
    """
    if value >= SCORE_CRITICAL_MIN:
        return ScoreBand.CRITICAL
    if value >= SCORE_HIGH_MIN:
        return ScoreBand.HIGH
    if value >= SCORE_MEDIUM_MIN:
        return ScoreBand.MEDIUM
    if value >= SCORE_LOW_MIN:
        return ScoreBand.LOW
    return ScoreBand.NONE


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """
    Clamp a value into the [low, high] range.
    """
    return max(low, min(high, value))


def weighted_sum(values: dict[str, float], weights: dict[str, float]) -> float:
    """
    Weighted sum of named values using a weight map; missing weights are 1.0.
    """
    total_weight = sum(weights.get(name, 1.0) for name in values) or 1.0
    return sum(values[name] * weights.get(name, 1.0) for name in values) / total_weight
