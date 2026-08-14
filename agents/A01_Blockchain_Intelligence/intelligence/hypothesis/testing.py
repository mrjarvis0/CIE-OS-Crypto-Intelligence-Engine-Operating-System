"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.hypothesis.testing

Purpose:
    Hypothesis testing against evidence.

    Contradicted artifacts never count as supporting evidence: a
    high-confidence artifact that has been contradicted neutralizes
    its own contribution instead of inflating the hypothesis score.
"""

from __future__ import annotations

from ..schemas.evidence import ClaimTier, EvidenceArtifact
from .generator import Hypothesis

# Confidence weight by claim tier: structural (grouping) evidence counts
# less toward a behavioural hypothesis than corroborated attribution.
_TIER_WEIGHT = {
    ClaimTier.STRUCTURAL.value: 0.5,
    ClaimTier.ATTRIBUTION.value: 1.0,
    ClaimTier.OPERATOR.value: 1.0,
}

_SUPPORT_CONFIDENCE = 0.6
_CONTRADICTION_PENALTY = 0.2
_VERIFIED_MIN = 0.6
_REJECTED_MAX = 0.3


class HypothesisTester:
    """
    Tests a hypothesis against supporting/opposing evidence.

    Confidence is a tier-weighted, evidence-weighted score so that many
    weak structural hints do not override a single strong attribution.
    """

    def test(self, hypothesis: Hypothesis, evidence: list[EvidenceArtifact]) -> Hypothesis:
        """
        Update hypothesis confidence and status based on evidence.

        Artifacts with contradicted status are excluded from the
        supporting set (so they cannot inflate confidence or coverage)
        and are instead counted as opposing.
        """
        supporting = [
            e
            for e in evidence
            if e.confidence >= _SUPPORT_CONFIDENCE and str(e.status) != "contradicted"
        ]
        opposing = [e for e in evidence if str(e.status) == "contradicted"]
        hypothesis.supporting = [e.claim for e in supporting]
        hypothesis.opposing = [e.claim for e in opposing]

        # Tier-weighted evidence strength.
        numerator = sum(
            _TIER_WEIGHT.get(str(e.tier), 1.0) * e.confidence for e in supporting
        )
        denominator = sum(
            _TIER_WEIGHT.get(str(e.tier), 1.0) for e in supporting
        ) or 1.0
        evidence_strength = numerator / denominator if supporting else 0.0
        coverage = len(supporting) / len(evidence) if evidence else 0.0

        # Penalize explicit contradiction proportionally: a lone
        # contradicting artifact among several supporting ones reduces
        # confidence but does not automatically reject the hypothesis.
        contradiction_penalty = _CONTRADICTION_PENALTY * (
            len(opposing) / len(evidence) if evidence else 0.0
        )
        confidence = evidence_strength * coverage - contradiction_penalty
        hypothesis.confidence = max(0.0, min(1.0, round(confidence, 4)))

        if not supporting:
            hypothesis.status = "rejected"
        elif hypothesis.confidence >= _VERIFIED_MIN:
            hypothesis.status = "verified"
        elif hypothesis.confidence <= _REJECTED_MAX:
            hypothesis.status = "rejected"
        else:
            hypothesis.status = "inconclusive"
        return hypothesis
