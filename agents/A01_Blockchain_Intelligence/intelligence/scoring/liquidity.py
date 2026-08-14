"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.liquidity

Purpose:
    Liquidity score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score
from .base import clamp, to_band

# Depth qualifier -> 0..1 depth factor. Producers emit a string depth
# qualifier (e.g. "deep"), so a raw numeric "depth" key must not be
# assumed; both forms are accepted.
_DEPTH_QUALIFIER = {
    "none": 0.0,
    "shallow": 0.3,
    "adequate": 0.6,
    "deep": 1.0,
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _depth_factor(subject: dict[str, Any]) -> float:
    qualifier = subject.get("liquidity_depth")
    if isinstance(qualifier, str):
        return _DEPTH_QUALIFIER.get(qualifier.lower(), 0.0)
    numeric = _to_float(qualifier)
    if numeric:
        return clamp(numeric, 0.0, 1.0)
    return clamp(_to_float(subject.get("depth", 0)), 0.0, 1.0)


class LiquidityScorer:
    """
    Computes a 0..100 liquidity health score.
    """

    name = "liquidity"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        locked_ratio = clamp(_to_float(subject.get("locked_ratio", 0)), 0.0, 1.0)
        depth = _depth_factor(subject)
        value = clamp(locked_ratio * 60 + depth * 40)
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
