"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.protocol

Purpose:
    Protocol analysis.

    Summarizes a DeFi protocol's scale (TVL, category, chain) and
    flags growth/contraction signals from recent TVL movement.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer


class ProtocolAnalyzer(BaseAnalyzer):
    """
    Produces a protocol profile with TVL trend assessment.
    """

    name = "protocol"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        protocol = self._get(subject, "name")
        tvl = self._get(subject, "tvl", 0)
        chain = self._get(subject, "chain")
        tvl_change = self._get(subject, "tvl_change_7d", 0)

        trend = "growing" if (tvl_change or 0) > 0.05 else ("shrinking" if (tvl_change or 0) < -0.05 else "stable")

        data = {
            "name": protocol,
            "chain": chain,
            "tvl": tvl,
            "category": self._get(subject, "category"),
            "tvl_change_7d": tvl_change,
            "trend": trend,
        }
        artifact = self._evidence(
            claim=f"protocol {protocol} on {chain} has TVL {tvl} ({trend})",
            data=data,
            source_type="market",
            confidence=0.6,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"protocol {protocol}: TVL {tvl}, {trend}",
            confidence=0.6,
        )
