"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.chain

Purpose:
    Build ordered evidence chains leading to a conclusion.
"""

from __future__ import annotations

from ..schemas.evidence import EvidenceArtifact, EvidenceChain
from .source_rank import SourceRanker


class EvidenceChainBuilder:
    """
    Assembles evidence artifacts into an ordered, aggregated chain.
    """

    def __init__(self, source_ranker: SourceRanker | None = None) -> None:
        self._ranker = source_ranker or SourceRanker()

    def build(self, conclusion: str, artifacts: list[EvidenceArtifact]) -> EvidenceChain:
        """
        Build an evidence chain with aggregated confidence.
        """
        if not artifacts:
            return EvidenceChain(conclusion=conclusion, artifacts=())

        weighted = sum(
            artifact.confidence * self._ranker.reliability(artifact.source_type)
            for artifact in artifacts
        )
        total_weight = sum(
            self._ranker.reliability(artifact.source_type) for artifact in artifacts
        )
        aggregated = weighted / total_weight if total_weight else 0.0
        return EvidenceChain(
            conclusion=conclusion,
            artifacts=tuple(artifacts),
            aggregated_confidence=max(0.0, min(1.0, aggregated)),
        )
