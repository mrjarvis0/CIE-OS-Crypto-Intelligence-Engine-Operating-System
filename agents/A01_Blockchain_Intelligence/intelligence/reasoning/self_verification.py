"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.self_verification

Purpose:
    Verify conclusions against available evidence.

    A conclusion passes only when it is corroborated (multiple
    independent references), non-contradicted, adequately confident,
    and backed by evidence of sufficient tier — structural grouping
    alone never verifies an identity or operator claim.
"""

from __future__ import annotations

from typing import Any

from ..schemas.evidence import ClaimTier, EvidenceArtifact
from .reasoning_engine import ReasoningStep

# Tiers strong enough to support a claim independently.
_VERIFYING_TIERS = {ClaimTier.ATTRIBUTION.value, ClaimTier.OPERATOR.value}

_CONFIDENCE_FLOOR = 0.5
_CORROBORATION_MIN = 2


class SelfVerifier:
    """
    Cross-checks a conclusion against supporting evidence artifacts.

    Verifies not only that evidence exists but that it is corroborated
    (multiple independent items), non-contradicted, and strong enough
    (confidence and tier) to support the claim.
    """

    def verify(
        self, conclusion: str, evidence: list[EvidenceArtifact]
    ) -> list[ReasoningStep]:
        """
        Produce verification steps for a conclusion.
        """
        supporting = [e for e in evidence if e.confidence >= _CONFIDENCE_FLOOR]
        contradicted = [e for e in evidence if str(e.status) == "contradicted"]
        tier = self._max_tier(evidence)
        tier_adequate = tier in _VERIFYING_TIERS

        corroboration = (
            len({e.reference for e in supporting if e.reference}) >= _CORROBORATION_MIN
        )
        adequate_confidence = len(supporting) > 0 and all(
            e.confidence >= _CONFIDENCE_FLOOR for e in supporting
        )

        passed = (
            corroboration
            and adequate_confidence
            and tier_adequate
            and not contradicted
        )
        reason = (
            "conclusion corroborated by independent evidence"
            if passed
            else "insufficient, contradicted, or too-weak-tier evidence"
        )

        return [
            ReasoningStep(
                kind="verification",
                content=f"checking {len(evidence)} evidence items",
                metadata={"evidence_count": len(evidence)},
            ),
            ReasoningStep(
                kind="assessment",
                content=(
                    f"{len(supporting)} supporting, {len(contradicted)} contradicted, "
                    f"max tier {tier}"
                ),
                metadata={
                    "supporting": len(supporting),
                    "contradicted": len(contradicted),
                    "tier": tier,
                },
            ),
            ReasoningStep(kind="result", content=reason, metadata={"passed": passed}),
        ]

    def _max_tier(self, evidence: list[EvidenceArtifact]) -> str:
        """
        Return the strongest claim tier present in the evidence set.
        """
        order = {
            ClaimTier.STRUCTURAL.value: 0,
            ClaimTier.ATTRIBUTION.value: 1,
            ClaimTier.OPERATOR.value: 2,
        }
        best = ClaimTier.STRUCTURAL.value
        for item in evidence:
            tier = str(item.tier)
            if order.get(tier, 0) > order.get(best, 0):
                best = tier
        return best
