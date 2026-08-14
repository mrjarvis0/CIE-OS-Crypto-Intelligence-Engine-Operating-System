"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.dex

Purpose:
    DEX analysis.

    Summarizes DEX liquidity and trading activity, flagging thin
    liquidity relative to volume as a risk-relevant signal. Depth
    tiers compare total liquidity against 24h volume: a pool whose
    liquidity is only a small multiple of daily volume is not deep.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer

# A pool is only "deep" when liquidity is a large multiple of volume.
_SHALLOW_MAX = 0.3
_DEEP_MIN = 2.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class DexAnalyzer(BaseAnalyzer):
    """
    Produces a DEX liquidity/trading summary.
    """

    name = "dex"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        dex = self._get(subject, "name")
        volume_24h = _to_float(self._get(subject, "volume_24h", 0))
        liquidity = _to_float(self._get(subject, "liquidity_24h", 0))
        pairs = self._get(subject, "pair_count", 0)

        liquidity_depth = "unknown"
        if volume_24h > 0:
            ratio = liquidity / volume_24h
            if ratio < _SHALLOW_MAX:
                liquidity_depth = "shallow"
            elif ratio < _DEEP_MIN:
                liquidity_depth = "adequate"
            else:
                liquidity_depth = "deep"

        data = {
            "name": dex,
            "volume_24h": volume_24h,
            "liquidity_24h": liquidity,
            "pair_count": pairs,
            "liquidity_depth": liquidity_depth,
        }
        artifact = self._evidence(
            claim=f"DEX {dex} has {liquidity_depth} liquidity with {pairs} pairs",
            data=data,
            source_type="market",
            confidence=0.6,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"DEX {dex}: {liquidity_depth} liquidity",
            confidence=0.6,
        )
