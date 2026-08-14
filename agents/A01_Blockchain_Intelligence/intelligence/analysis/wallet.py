"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.wallet

Purpose:
    Wallet profiling analyzer.

    Produces a behavioral entity profile (not an identification):
    activity level, net flow, counterparty exposure, and a behavioral
    sketch consistent with the observed on-chain pattern.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer


class WalletAnalyzer(BaseAnalyzer):
    """
    Produces a behavioral profile summary for a wallet subject.
    """

    name = "wallet"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        address = self._address(subject)
        balance = self._get(subject, "balance", 0)
        tx_count = self._get(subject, "transaction_count", 0)
        inflow = self._get(subject, "total_inflow", 0)
        outflow = self._get(subject, "total_outflow", 0)
        first_seen = self._get(subject, "first_seen")
        last_seen = self._get(subject, "last_seen")

        net_flow = (inflow or 0) - (outflow or 0)

        if (tx_count or 0) <= 0:
            activity = "dormant"
        elif (tx_count or 0) < 5:
            activity = "low"
        elif (tx_count or 0) < 50:
            activity = "moderate"
        elif (tx_count or 0) < 500:
            activity = "high"
        else:
            activity = "very_high"

        exposure = (
            "accumulator"
            if net_flow > 0
            else ("distributor" if net_flow < 0 else "transient")
        )

        data = {
            "address": address,
            "balance": balance,
            "transaction_count": tx_count,
            "net_flow": net_flow,
            "activity": activity,
            "behavioral_profile": exposure,
            "first_seen": first_seen,
            "last_seen": last_seen,
        }
        artifact = self._evidence(
            claim=f"wallet {address} has {tx_count} transactions with {exposure} flow pattern",
            data=data,
            source_type="on_chain",
            confidence=0.7,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=(
                f"wallet {address}: {activity} activity, "
                f"net_flow={net_flow}, {exposure}"
            ),
            confidence=0.7,
        )
