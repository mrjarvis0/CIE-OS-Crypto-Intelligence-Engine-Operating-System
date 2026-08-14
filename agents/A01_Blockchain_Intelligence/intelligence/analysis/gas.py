"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.gas

Purpose:
    Gas usage analysis.

    Summarizes gas behavior and flags abnormal gas usage relative to
    the base fee or configured thresholds. On-chain gas feeds routinely
    deliver hex or string numerics, so all fields are coerced safely.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer

# Priority premium (multiple of base fee) considered anomalous.
_ANOMALOUS_PREMIUM = 5.0


def _to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str) and value.lower().startswith("0x"):
        try:
            return float(int(value, 16))
        except ValueError:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class GasAnalyzer(BaseAnalyzer):
    """
    Produces a gas behavior summary.
    """

    name = "gas"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        avg_gas = _to_float(self._get(subject, "average_gas", 0))
        base_fee = _to_float(self._get(subject, "base_fee", 0))
        priority_fee = _to_float(self._get(subject, "priority_fee", 0))
        anomaly = bool(self._get(subject, "anomaly", False))

        # An unusual priority premium over the base fee is a signal.
        premium = (priority_fee / base_fee) if base_fee > 0 else 0.0
        if not anomaly and base_fee > 0 and premium > _ANOMALOUS_PREMIUM:
            anomaly = True

        data = {
            "average_gas": avg_gas,
            "base_fee": base_fee,
            "priority_fee": priority_fee,
            "priority_premium": premium,
            "anomaly": anomaly,
        }
        artifact = self._evidence(
            claim=f"gas avg {avg_gas} base {base_fee} premium {premium:.1f}x anomaly={anomaly}",
            data=data,
            source_type="on_chain",
            confidence=0.6,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"gas: avg {avg_gas}, premium {premium:.1f}x",
            confidence=0.6,
        )
