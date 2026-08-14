"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.liquidity

Purpose:
    Liquidity analysis.

    Assesses liquidity health from the locked/total ratio and flags
    low-liquidity risk. Inputs are coerced numerically so string or
    null values from market feeds cannot crash the analysis.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer

_HEALTHY_RATIO = 0.7
_MODERATE_RATIO = 0.3


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class LiquidityAnalyzer(BaseAnalyzer):
    """
    Produces a liquidity health summary.
    """

    name = "liquidity"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        locked = _to_float(self._get(subject, "liquidity_locked", 0))
        total = _to_float(self._get(subject, "liquidity_total", 0))
        ratio = (locked / total) if total > 0 else 0.0

        health = "unknown"
        if total > 0:
            if ratio >= _HEALTHY_RATIO:
                health = "healthy"
            elif ratio >= _MODERATE_RATIO:
                health = "moderate"
            else:
                health = "low"

        low_risk = bool(total > 0 and ratio < _MODERATE_RATIO)

        data = {
            "liquidity_locked": locked,
            "liquidity_total": total,
            "locked_ratio": ratio,
            "health": health,
            "low_liquidity_risk": low_risk,
        }
        artifact = self._evidence(
            claim=f"liquidity is {health} ({ratio:.0%} locked)",
            data=data,
            source_type="market",
            confidence=0.6,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"liquidity: {ratio:.0%} locked ({health})",
            confidence=0.6,
        )
