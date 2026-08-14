"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.chain_of_thought

Purpose:
    Linear, step-by-step chain-of-thought reasoning.
"""

from __future__ import annotations

from typing import Any

from ..schemas.evidence import EvidenceArtifact
from .reasoning_engine import ReasoningStep


class ChainOfThought:
    """
    Produces an ordered sequence of reasoning steps.

    Decomposes a question into testable claims, scores them against the
    supplied evidence, and derives a confidence-weighted conclusion.
    """

    def reason(
        self, question: str, context: dict[str, Any] | None = None, **_: Any
    ) -> list[ReasoningStep]:
        context = context or {}
        steps: list[ReasoningStep] = [
            ReasoningStep(
                kind="observation",
                content=question,
                metadata={"subject": context.get("subject", "unknown")},
            )
        ]

        evidence = context.get("evidence", [])
        evidence = [e for e in evidence if isinstance(e, EvidenceArtifact)]

        # 1. Decompose into claims.
        claims = self._decompose(context)
        if not claims:
            claims = ["the subject exhibits the questioned behaviour"]
        steps.append(
            ReasoningStep(
                kind="decomposition",
                content=f"split into {len(claims)} testable claims",
                metadata={"claims": list(claims)},
            )
        )

        # 2. Score each claim against evidence.
        supported = 0.0
        total_weight = 0.0
        for claim in claims:
            claim_score, weight = self._score_claim(claim, evidence)
            supported += claim_score * weight
            total_weight += weight
            steps.append(
                ReasoningStep(
                    kind="premise",
                    content=claim,
                    metadata={"support": round(claim_score, 4), "weight": weight},
                )
            )

        # 3. Aggregate into a conclusion with stated confidence.
        confidence = supported / total_weight if total_weight else 0.0
        conclusion = (
            "claim is supported by evidence"
            if confidence >= 0.5
            else "insufficient evidence to support claim"
        )
        steps.append(
            ReasoningStep(
                kind="inference",
                content=f"aggregated {len(evidence)} evidence items",
                metadata={"evidence_count": len(evidence)},
            )
        )
        steps.append(
            ReasoningStep(
                kind="conclusion",
                content=conclusion,
                metadata={"confidence": round(confidence, 4)},
            )
        )
        return steps

    def _decompose(self, context: dict[str, Any]) -> list[str]:
        claims = context.get("claims", [])
        if isinstance(claims, list):
            return [str(c) for c in claims if c]
        return []

    def _score_claim(self, claim: str, evidence: list[EvidenceArtifact]) -> tuple[float, float]:
        """
        Score a single claim against evidence by matching key terms.

        Returns (support 0..1, weight). Evidence matching the claim's
        tokens reinforces it; strong but non-matching evidence does not
        detract (conservative).
        """
        if not evidence:
            return 0.0, 1.0
        tokens = {w for w in claim.lower().split() if len(w) > 2}
        if not tokens:
            return 0.0, 1.0
        hits = 0.0
        for item in evidence:
            haystack = f"{item.claim} {item.reference or ''}".lower()
            if any(tok in haystack for tok in tokens):
                hits += item.confidence
        score = min(1.0, hits / max(1, len(evidence)))
        return score, 1.0
