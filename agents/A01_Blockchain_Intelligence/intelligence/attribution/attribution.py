"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.attribution.attribution

Purpose:
    Central attribution engine combining labels, identity, ownership,
    and heuristics.

    Every heuristic contributes a label proposal; all proposals are
    surfaced on the attribution result while the queryable label store
    retains the highest-confidence proposal per entity.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..schemas.entity import Entity
from ..schemas.evidence import ClaimTier
from .confidence import AttributionConfidence
from .heuristics import AttributionHeuristics, Heuristic
from .identity import IdentityResolver
from .labels import LabelStore
from .ownership import Ownership, OwnershipResolver


@dataclass(slots=True)
class Attribution:
    """
    Full attribution result for a subject.

    An attribution is a confidence-scored research hypothesis. It
    carries the evidence tier satisfied (structural grouping vs. entity
    attribution vs. operator determination), the alternative
    explanations considered, and the specific evidence that supports the
    conclusion.
    """

    entity: Entity
    ownership: Ownership | None = None
    labels: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    claim_tier: str = "attribution"
    alternatives: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "ownership": self.ownership.to_dict() if self.ownership else None,
            "labels": list(self.labels),
            "confidence": self.confidence,
            "claim_tier": self.claim_tier,
            "alternatives": list(self.alternatives),
            "evidence": list(self.evidence),
        }


class AttributionEngine:
    """
    Orchestrates attribution of a subject.

    Mirrors on-chain attribution practice: structural grouping (co-spend,
    deposit chains) provides the weakest evidence tier; verified labels
    (exchange addresses, published identities) provide entity attribution;
    operator determination (admin key, deployer, upgrade authority)
    provides the strongest tier.
    """

    def __init__(self) -> None:
        self.identity = IdentityResolver()
        self.ownership = OwnershipResolver()
        self.heuristics = AttributionHeuristics()
        self.confidence = AttributionConfidence()
        self.labels = LabelStore()

    def attribute(self, subject: dict[str, Any]) -> Attribution:
        """
        Produce a full attribution for a subject.

        Combines identity resolution, ownership, and rule heuristics.
        Evidence is captured per heuristic; confidence is scored
        conservatively across the heuristic set; claim tier reflects the
        strongest supported evidence level.
        """
        entity = self.identity.resolve(subject)
        ownership = self.ownership.resolve(subject)
        heuristic_list: list[Heuristic] = self.heuristics.apply(subject)
        conf = self.confidence.score(heuristic_list)

        evidence: list[dict[str, Any]] = []
        for h in heuristic_list:
            self.labels.add(
                entity.primary_identifier, h.label, h.category, h.confidence
            )
            evidence.append(
                {
                    "label": h.label,
                    "category": h.category,
                    "confidence": h.confidence,
                    "evidence_refs": list(h.evidence_refs),
                }
            )

        tier = self._derive_tier(subject, evidence, ownership)
        alternatives = self._derive_alternatives(subject, evidence)
        entity = replace(
            entity,
            claim_tier=tier.value,
            confidence=conf,
            alternatives=tuple(alternatives),
        )

        # Surface every heuristic's label proposal; the strongest
        # per-key proposal remains queryable via the label store.
        labels = [
            {
                "label": h.label,
                "category": h.category,
                "confidence": h.confidence,
            }
            for h in heuristic_list
        ]

        return Attribution(
            entity=entity,
            ownership=ownership,
            labels=labels,
            confidence=conf,
            claim_tier=tier.value,
            alternatives=alternatives,
            evidence=evidence,
        )

    def _derive_tier(
        self,
        subject: dict[str, Any],
        evidence: list[dict[str, Any]],
        ownership: Ownership | None,
    ) -> ClaimTier:
        """
        Pick the highest evidence tier that is actually supported.

        Order: operator > attribution > structural. Ownership of an
        upgrade/admin key or the presence of a verified operator signal
        promotes the claim to operator tier.
        """
        if ownership and ownership.basis in {"deployer", "operator", "admin"}:
            return ClaimTier.OPERATOR
        if any(e.get("category") == "operator" for e in evidence):
            return ClaimTier.OPERATOR
        if evidence and any(e.get("confidence", 0.0) >= 0.9 for e in evidence):
            return ClaimTier.ATTRIBUTION
        if subject.get("structural_evidence"):
            return ClaimTier.STRUCTURAL
        return ClaimTier.ATTRIBUTION

    def _derive_alternatives(
        self, subject: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> list[str]:
        """
        Record plausible alternatives that the evidence does not rule out.

        Conservative bias: attribution should surface the residual
        uncertainty (e.g. "shared ownership of the address") rather than
        over-claiming.
        """
        alternatives: list[str] = []
        if subject.get("shared_ownership"):
            alternatives.append("address may be jointly controlled")
        if subject.get("renamed"):
            alternatives.append("identity may have been re-assigned")
        if not evidence:
            alternatives.append("no corroborating labels; attribution is weak")
        return alternatives
