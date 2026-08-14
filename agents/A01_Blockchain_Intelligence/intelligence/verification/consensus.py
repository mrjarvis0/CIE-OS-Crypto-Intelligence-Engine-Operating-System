"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.verification.consensus

Purpose:
    Consensus aggregation across sources.
"""

from __future__ import annotations

from typing import Any


class ConsensusEngine:
    """
    Aggregates agreement across verification checks.

    Supports weighting checks by source reliability so that a strong
    on-chain confirmation outweighs a weak social post.
    """

    def agree(self, checks: dict[str, Any], weights: dict[str, float] | None = None) -> float:
        """
        Return the fraction of checks that confirmed.

        When ``weights`` are provided, returns a weighted agreement in
        [0, 1].
        """
        if not checks:
            return 0.0
        if weights:
            total = sum(weights.get(name, 1.0) for name in checks) or 1.0
            confirmed = sum(
                weights.get(name, 1.0) for name, value in checks.items() if value
            )
            return confirmed / total
        confirmed = sum(1 for value in checks.values() if value)
        return confirmed / len(checks)

    def is_consensus(
        self,
        checks: dict[str, Any],
        threshold: float = 0.6,
        weights: dict[str, float] | None = None,
    ) -> bool:
        """
        Return True if agreement meets the threshold.
        """
        return self.agree(checks, weights) >= threshold
