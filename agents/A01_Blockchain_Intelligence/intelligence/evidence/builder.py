"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.builder

Purpose:
    Assemble finalized, hashed evidence artifacts from raw inputs.

    The builder is the enforcement point for tier confidence ceilings: an
    artifact cannot be constructed above the ceiling for its claim tier, so
    no downstream code has to remember to clamp it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..schemas.evidence import (
    ClaimTier,
    ErrorRate,
    ErrorRateState,
    EvidenceArtifact,
    EvidenceSource,
    UNMEASURED_ERROR_RATE_CEILING,
    canonical_payload,
    tier_ceiling,
)
from ..utils.hashing import content_hash


class EvidenceBuilder:
    """
    Builds finalized evidence artifacts with provenance hashes.

    Confidence passed in is treated as a *request*. The value stored is the
    request clamped to the tier ceiling and, where the producing method has
    no measured error rate, to the unmeasured ceiling as well.
    """

    def build(
        self,
        claim: str,
        source_type: EvidenceSource | str = EvidenceSource.INFERRED,
        data: dict[str, Any] | None = None,
        reference: str | None = None,
        confidence: float = 0.0,
        tier: ClaimTier | str = ClaimTier.ATTRIBUTION,
        metadata: dict[str, Any] | None = None,
        *,
        derivation: tuple[str, ...] = (),
        error_rate: ErrorRate | None = None,
        expires_at: datetime | None = None,
        contradicts: tuple[str, ...] = (),
        completeness: tuple[str, ...] = (),
        method: str | None = None,
    ) -> EvidenceArtifact:
        """
        Construct a hashed evidence artifact.

        The content hash covers claim, source, data, reference, tier,
        derivation, method, and completeness, so tampering with any of them
        changes the fingerprint.
        """
        rate = error_rate or ErrorRate()
        effective = self.clamp(confidence, tier=tier, error_rate=rate)

        payload = canonical_payload(
            claim=claim,
            source_type=source_type,
            data=data,
            reference=reference,
            tier=tier,
            derivation=tuple(derivation),
            method=method,
            completeness=tuple(completeness),
        )
        return EvidenceArtifact(
            claim=claim,
            source_type=source_type,
            data=dict(data or {}),
            reference=reference,
            confidence=effective,
            tier=tier,
            content_hash=content_hash(payload),
            metadata=dict(metadata or {}),
            derivation=tuple(derivation),
            error_rate=rate,
            expires_at=expires_at,
            contradicts=tuple(contradicts),
            completeness=tuple(completeness),
            method=method,
        )

    @staticmethod
    def clamp(
        confidence: float,
        *,
        tier: ClaimTier | str,
        error_rate: ErrorRate | None = None,
    ) -> float:
        """
        Clamp a requested confidence to every applicable ceiling.

        Applied in the constructor rather than left to callers, because a
        ceiling that must be remembered is a ceiling that will be forgotten.
        """
        value = max(0.0, min(1.0, confidence))
        value = min(value, tier_ceiling(tier))

        rate = error_rate or ErrorRate()
        if rate.state is ErrorRateState.UNMEASURED or not rate.is_known:
            value = min(value, UNMEASURED_ERROR_RATE_CEILING)

        return round(value, 6)
