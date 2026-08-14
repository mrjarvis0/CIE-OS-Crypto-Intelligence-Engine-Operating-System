"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.token

Purpose:
    Token analysis.

    Assesses token concentration and distribution risk from holder
    data, using the top-holder share as a concentration signal. When
    the top-holder share is unavailable the concentration is reported
    as unknown rather than fabricated.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer

_EXTREME_SHARE = 0.8
_HIGH_SHARE = 0.5
_MODERATE_SHARE = 0.3


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TokenAnalyzer(BaseAnalyzer):
    """
    Produces a token summary with distribution risk assessment.
    """

    name = "token"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        token_address = self._address(subject)
        supply = self._get(subject, "total_supply", 0)
        holders = self._get(subject, "holder_count", 0)
        top10_pct = self._get(subject, "top_10_share")

        concentration = "unknown"
        if top10_pct is not None:
            share = _to_float(top10_pct)
            if share >= _EXTREME_SHARE:
                concentration = "extreme"
            elif share >= _HIGH_SHARE:
                concentration = "high"
            elif share >= _MODERATE_SHARE:
                concentration = "moderate"
            else:
                concentration = "distributed"

        data = {
            "address": token_address,
            "total_supply": supply,
            "holder_count": holders,
            "top_10_share": top10_pct,
            "concentration": concentration,
        }
        artifact = self._evidence(
            claim=f"token {token_address} has {holders} holders with {concentration} concentration",
            data=data,
            source_type="on_chain",
            confidence=0.7,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"token {token_address}: {concentration} distribution",
            confidence=0.7,
        )
