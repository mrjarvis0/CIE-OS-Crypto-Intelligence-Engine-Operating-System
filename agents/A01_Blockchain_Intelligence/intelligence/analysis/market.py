"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.market

Purpose:
    Market analysis.

    Summarizes market conditions (price, 24h change, cap) and derives
    a directional sentiment. Market APIs frequently emit numeric
    strings or nulls, so inputs are coerced defensively.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer

_BULLISH_THRESHOLD = 3.0
_BEARISH_THRESHOLD = -3.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class MarketAnalyzer(BaseAnalyzer):
    """
    Produces a market condition summary.
    """

    name = "market"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        asset = self._get(subject, "asset")
        price = _to_float(self._get(subject, "price", 0))
        change_24h = _to_float(self._get(subject, "change_24h", 0))

        if change_24h > _BULLISH_THRESHOLD:
            sentiment = "bullish"
        elif change_24h < _BEARISH_THRESHOLD:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        data = {
            "asset": asset,
            "price": price,
            "change_24h": change_24h,
            "market_cap": self._get(subject, "market_cap"),
            "volume_24h": self._get(subject, "volume_24h"),
            "sentiment": sentiment,
        }
        artifact = self._evidence(
            claim=f"market for {asset}: price {price}, 24h {change_24h}% ({sentiment})",
            data=data,
            source_type="market",
            confidence=0.5,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"market {asset}: {change_24h:+.1f}% ({sentiment})",
            confidence=0.5,
        )
