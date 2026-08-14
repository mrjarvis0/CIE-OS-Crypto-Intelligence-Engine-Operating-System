"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.bridge

Purpose:
    Bridge analysis.

    Summarizes cross-chain bridge flow. Net-flow direction and volume
    are used as signals for cross-chain fund movement.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer


class BridgeAnalyzer(BaseAnalyzer):
    """
    Produces a bridge activity summary.
    """

    name = "bridge"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        bridge = self._get(subject, "name")
        flows_in = self._get(subject, "inflow", 0)
        flows_out = self._get(subject, "outflow", 0)
        net_flow = (flows_in or 0) - (flows_out or 0)

        direction = "neutral"
        if net_flow > 0:
            direction = "net_inflow"
        elif net_flow < 0:
            direction = "net_outflow"

        data = {
            "name": bridge,
            "inflow": flows_in,
            "outflow": flows_out,
            "net_flow": net_flow,
            "direction": direction,
            "chain": self._get(subject, "chain"),
        }
        artifact = self._evidence(
            claim=f"bridge {bridge} has net flow {net_flow} ({direction})",
            data=data,
            source_type="on_chain",
            confidence=0.7,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"bridge {bridge}: {direction} {net_flow}",
            confidence=0.7,
        )
