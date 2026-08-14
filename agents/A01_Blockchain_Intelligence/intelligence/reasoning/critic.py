"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.critic

Purpose:
    Self-critique and counter-argument generation.
"""

from __future__ import annotations

from typing import Any

from ..schemas.evidence import EvidenceArtifact
from .reasoning_engine import ReasoningStep


class Critic:
    """
    Generates counter-arguments to test a proposed conclusion.

    Deliberately surfaces evidence that contradicts or weakens the
    conclusion so that a decision is not reached without adversarial
    review (reflection-style self-critique).
    """

    def critique(
        self, conclusion: str, evidence: list[EvidenceArtifact] | None = None
    ) -> list[ReasoningStep]:
        """
        Produce critique steps challenging the conclusion.

        Weak evidence items (low confidence, contradicted status) and
        low-tier claims are flagged as grounds for doubt.
        """
        evidence = evidence or []
        weak = [e for e in evidence if e.confidence < 0.5]
        contradicted = [e for e in evidence if str(e.status) == "contradicted"]
        structural_only = [e for e in evidence if str(e.tier) == "structural"]

        challenges: list[str] = []
        if contradicted:
            challenges.append(f"{len(contradicted)} contradicted evidence items")
        if weak:
            challenges.append(f"{len(weak)} low-confidence evidence items")
        if structural_only and not any(str(e.tier) != "structural" for e in evidence):
            challenges.append("only structural (grouping) evidence; no entity attribution")

        return [
            ReasoningStep(kind="critique", content=f"challenging conclusion: {conclusion}"),
            ReasoningStep(
                kind="counter_argument",
                content="considering alternative explanations",
                metadata={"challenges": challenges},
            ),
            ReasoningStep(
                kind="assessment",
                content=f"raised {len(challenges)} concerns requiring resolution",
                metadata={"concern_count": len(challenges)},
            ),
        ]
