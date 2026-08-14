"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.validator

Purpose:
    Validate the structural integrity of evidence artifacts.
"""

from __future__ import annotations

from datetime import datetime

from ..schemas.evidence import (
    ClaimTier,
    ErrorRateState,
    EvidenceArtifact,
    canonical_payload,
    tier_ceiling,
)
from ..utils.hashing import content_hash


class EvidenceValidator:
    """
    Validates evidence artifacts for required fields and integrity.

    Verifies that the stored content hash matches a recomputation over the
    canonical payload, enabling chain-of-custody checks, and that the artifact
    respects the confidence ceiling for its tier.
    """

    def validate(
        self,
        artifact: EvidenceArtifact,
        *,
        now: datetime | None = None,
    ) -> list[str]:
        """
        Return a list of validation errors (empty if valid).
        """
        errors: list[str] = []

        if not artifact.claim or not artifact.claim.strip():
            errors.append("evidence claim is empty")
        if not artifact.data and not artifact.reference:
            errors.append("evidence has no data or reference")
        if not 0.0 <= artifact.confidence <= 1.0:
            errors.append("evidence confidence out of range")

        try:
            ClaimTier(artifact.tier)
        except ValueError:
            errors.append(f"unknown claim tier: {artifact.tier}")
        else:
            ceiling = tier_ceiling(artifact.tier)
            if artifact.confidence > ceiling:
                errors.append(
                    f"confidence {artifact.confidence} exceeds "
                    f"{artifact.tier} tier ceiling {ceiling}"
                )

        errors.extend(self._validate_error_rate(artifact))

        if artifact.content_hash:
            payload = canonical_payload(
                claim=artifact.claim,
                source_type=artifact.source_type,
                data=artifact.data,
                reference=artifact.reference,
                tier=artifact.tier,
                derivation=artifact.derivation,
                method=artifact.method,
                completeness=artifact.completeness,
            )
            if content_hash(payload) != artifact.content_hash:
                errors.append("evidence content hash mismatch")

        if artifact.expires_at and artifact.collected_at:
            if artifact.expires_at <= artifact.collected_at:
                errors.append("evidence expires_at precedes collected_at")

        if artifact.content_hash and artifact.content_hash in artifact.derivation:
            errors.append("evidence derives from itself")

        return errors

    @staticmethod
    def _validate_error_rate(artifact: EvidenceArtifact) -> list[str]:
        """
        Check that a declared error rate carries what its state requires.

        MEASURED without a sample size, or STATED without a citation, is an
        unsupported claim of rigour -- worse than declaring UNMEASURED.
        """
        errors: list[str] = []
        rate = artifact.error_rate

        if rate.value is not None and not 0.0 <= rate.value <= 1.0:
            errors.append("error rate value out of range")

        if rate.state is ErrorRateState.MEASURED:
            if rate.value is None:
                errors.append("measured error rate has no value")
            if not rate.sample_size:
                errors.append("measured error rate has no sample size")
        elif rate.state is ErrorRateState.STATED:
            if rate.value is None:
                errors.append("stated error rate has no value")
            if not rate.citation:
                errors.append("stated error rate has no citation")

        return errors

    def is_valid(self, artifact: EvidenceArtifact) -> bool:
        """
        Return True if the artifact passes all validation checks.
        """
        return not self.validate(artifact)
