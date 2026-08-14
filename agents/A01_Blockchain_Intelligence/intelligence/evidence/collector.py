"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.collector

Purpose:
    Collect raw evidence from multiple sources and normalize it into
    evidence candidates for further processing.

    Finalized artifacts carry a content hash (same payload contract as
    :class:`~intelligence.evidence.builder.EvidenceBuilder`) and retain
    any confidence/tier supplied by the source, so downstream
    confidence, chain, and validation stages receive complete inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..schemas.evidence import (
    ClaimTier,
    EvidenceArtifact,
    EvidenceSource,
)
from ..utils.hashing import content_hash

_DEFAULT_CANDIDATE_CONFIDENCE = 0.5


@dataclass
class EvidenceCandidate:
    """
    Raw evidence before it is finalized into an artifact.
    """

    claim: str
    source_type: EvidenceSource | str
    data: dict[str, Any] = field(default_factory=dict)
    reference: str | None = None
    confidence: float = _DEFAULT_CANDIDATE_CONFIDENCE
    tier: ClaimTier | str = ClaimTier.ATTRIBUTION
    metadata: dict[str, Any] | None = None


class EvidenceCollector:
    """
    Collects and normalizes raw evidence candidates into artifacts.
    """

    def __init__(self) -> None:
        self._candidates: list[EvidenceCandidate] = []

    def add(self, candidate: EvidenceCandidate | dict[str, Any]) -> "EvidenceCollector":
        """
        Register a raw evidence candidate.

        Dictionary candidates may carry optional ``confidence`` and
        ``tier`` keys; both are preserved on the final artifact.
        """
        if isinstance(candidate, dict):
            candidate = EvidenceCandidate(
                claim=candidate["claim"],
                source_type=candidate.get("source_type", EvidenceSource.INFERRED),
                data=candidate.get("data", {}),
                reference=candidate.get("reference"),
                confidence=candidate.get("confidence", _DEFAULT_CANDIDATE_CONFIDENCE),
                tier=candidate.get("tier", ClaimTier.ATTRIBUTION),
                metadata=candidate.get("metadata"),
            )
        self._candidates.append(candidate)
        return self

    def collect(self) -> list[EvidenceArtifact]:
        """
        Convert all registered candidates into hashed evidence artifacts.
        """
        artifacts: list[EvidenceArtifact] = []
        for candidate in self._candidates:
            payload = {
                "claim": candidate.claim,
                "source_type": str(candidate.source_type),
                "data": candidate.data,
                "reference": candidate.reference,
                "tier": str(candidate.tier),
            }
            artifacts.append(
                EvidenceArtifact(
                    claim=candidate.claim,
                    source_type=candidate.source_type,
                    data=dict(candidate.data),
                    reference=candidate.reference,
                    confidence=max(0.0, min(1.0, float(candidate.confidence))),
                    tier=candidate.tier,
                    content_hash=content_hash(payload),
                    metadata=dict(candidate.metadata or {}),
                )
            )
        return artifacts

    @property
    def count(self) -> int:
        """Number of registered candidates."""
        return len(self._candidates)
