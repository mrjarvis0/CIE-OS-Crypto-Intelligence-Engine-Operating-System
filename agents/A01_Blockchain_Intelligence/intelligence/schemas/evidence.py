"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.evidence

Purpose:
    Canonical evidence data models.

    Every intelligence conclusion is backed by one or more evidence
    artifacts. An artifact records the claim, supporting material,
    source, confidence, timestamp, and a content hash for provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EvidenceSource(StrEnum):
    """
    Provenance category of an evidence artifact.

    Categories mirror the trust profile of the underlying source.
    On-chain and explorer data are deterministic records; news,
    social, and AI outputs are secondary and require corroboration.
    """

    ON_CHAIN = "on_chain"
    EXPLORER = "explorer"
    MARKET = "market"
    NEWS = "news"
    SOCIAL = "social"
    GITHUB = "github"
    DOCUMENTATION = "documentation"
    GOVERNMENT = "government"
    ANALYST = "analyst"
    AI = "ai"
    INFERRED = "inferred"


class ClaimTier(StrEnum):
    """
    Evidence standard of an analytical claim (Chainalysis-style
    two-tier ontology collapsed into three explicit tiers).

    Structural
        Deterministic, reproducible on-chain grouping
        (e.g. co-spend, change-address, deposit clustering).
    Attribution
        Off-chain linkage of a cluster to a named entity; requires
        explicit source characterization and confidence.
    Operator
        Determination that an attributed entity actually controls
        the infrastructure rather than merely using it.

    A single evidence artifact maps to exactly one tier, and a claim
    may only inherit labels once its structural integrity, attribution
    evidence, and (where required) operator verification each hold.
    """

    STRUCTURAL = "structural"
    ATTRIBUTION = "attribution"
    OPERATOR = "operator"


class EvidenceStatus(StrEnum):
    """
    Lifecycle status of an evidence artifact.
    """

    COLLECTED = "collected"
    VALIDATED = "validated"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    EXPIRED = "expired"


# =============================================================================
# Confidence ceilings
# =============================================================================

#: Maximum confidence a claim may carry, by tier, on the strength of the
#: evidence category alone. These are hard limits: accumulating many weak
#: signals must never lift a claim past its tier ceiling, because the *kind*
#: of available evidence is what is limited, and quantity does not change it.
#:
#: STRUCTURAL is mechanically grounded (spending an input requires its key),
#: which is why it earns the highest ceiling. ATTRIBUTION asserts a real-world
#: identity and requires external corroboration. OPERATOR is the most demanding
#: claim of all -- it asserts an attributed entity actually *controls*
#: infrastructure rather than merely using it -- so it sits lowest.
#:
#: See docs/intelligence/attribution-doctrine.md section 2.
TIER_CONFIDENCE_CEILING: dict[ClaimTier, float] = {
    ClaimTier.STRUCTURAL: 0.95,
    ClaimTier.ATTRIBUTION: 0.40,
    ClaimTier.OPERATOR: 0.30,
}

#: Ceiling applied to any claim whose detector has not measured its error rate.
#: A detector that cannot state how often it is wrong may still be useful, but
#: it must not carry high confidence.
#: See docs/intelligence/evidence-standard.md section 2.1.
UNMEASURED_ERROR_RATE_CEILING: float = 0.60


def tier_ceiling(tier: ClaimTier | str) -> float:
    """
    Return the confidence ceiling for a claim tier.

    Unknown tiers fall back to the most restrictive ceiling rather than the
    most permissive, so a typo cannot silently unlock high confidence.
    """
    try:
        return TIER_CONFIDENCE_CEILING[ClaimTier(tier)]
    except (ValueError, KeyError):
        return min(TIER_CONFIDENCE_CEILING.values())


# =============================================================================
# Error rates
# =============================================================================


class ErrorRateState(StrEnum):
    """
    Whether a detector's error rate is known, and how.

    There is deliberately no fourth state. Under the Daubert testability and
    known-error-rate criteria, an undocumented error rate is worse than a high
    one, so every artifact must declare which of these applies.
    """

    MEASURED = "measured"
    STATED = "stated"
    UNMEASURED = "unmeasured"


@dataclass(frozen=True, slots=True)
class ErrorRate:
    """
    Documented false-positive characteristics of the method that produced
    an artifact.

    ``MEASURED`` requires ``value`` and ``sample_size``; ``STATED`` requires
    ``value`` and ``citation`` (inherited from published research).
    """

    state: ErrorRateState = ErrorRateState.UNMEASURED
    value: float | None = None
    citation: str | None = None
    sample_size: int | None = None
    measured_at: datetime | None = None

    @property
    def is_known(self) -> bool:
        """True when the error rate is measured or cited, not merely absent."""
        return self.state is not ErrorRateState.UNMEASURED and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": str(self.state),
            "value": self.value,
            "citation": self.citation,
            "sample_size": self.sample_size,
            "measured_at": (
                self.measured_at.isoformat() if self.measured_at else None
            ),
        }


#: An error rate that has not been measured. Shared default so callers do not
#: each construct their own.
UNMEASURED = ErrorRate()


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """
    A single unit of evidence supporting an intelligence claim.

    Carries a content hash for chain-of-custody provenance and a
    tier (structural / attribution / operator) so that downstream
    consumers never treat a structural grouping as proof of identity
    or an attribution as proof of control.
    """

    claim: str
    source_type: EvidenceSource | str
    data: dict[str, Any] = field(default_factory=dict)
    reference: str | None = None
    confidence: float = 0.0
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    content_hash: str | None = None
    status: EvidenceStatus | str = EvidenceStatus.COLLECTED
    tier: ClaimTier | str = ClaimTier.ATTRIBUTION
    metadata: dict[str, Any] = field(default_factory=dict)

    #: Content hashes of the artifacts this one was derived from. Empty means
    #: this is a leaf -- a direct observation or external assertion rather
    #: than an inference. EvidenceGraph uses this for acyclicity, leaf
    #: grounding, and correlation collapse.
    derivation: tuple[str, ...] = ()

    #: Documented error characteristics of the producing method.
    error_rate: ErrorRate = field(default_factory=ErrorRate)

    #: When this artifact stops being presentable as current. Behavioural
    #: classifications drift, so they expire; protocol facts do not.
    expires_at: datetime | None = None

    #: Content hashes of artifacts this one contradicts. Retained rather than
    #: discarded: a report showing only supporting evidence is advocacy.
    contradicts: tuple[str, ...] = ()

    #: Which transfer types the underlying data covered, e.g.
    #: ("external", "internal", "erc20"). A balance derived from external
    #: transfers alone is wrong for any address receiving via contract calls,
    #: so completeness must be declared rather than assumed.
    completeness: tuple[str, ...] = ()

    #: Producing heuristic and version, e.g. "common_input_ownership@1".
    method: str | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when this artifact has passed its expiry."""
        if self.expires_at is None:
            return False
        return (now or datetime.now(UTC)) >= self.expires_at

    def is_leaf(self) -> bool:
        """True when this artifact is an observation rather than an inference."""
        return not self.derivation

    def to_dict(self) -> dict[str, Any]:
        """Serialize artifact to a plain dictionary."""
        return {
            "claim": self.claim,
            "source_type": str(self.source_type),
            "data": self.data,
            "reference": self.reference,
            "confidence": self.confidence,
            "collected_at": self.collected_at.isoformat(),
            "content_hash": self.content_hash,
            "status": str(self.status),
            "tier": str(self.tier),
            "metadata": self.metadata,
            "derivation": list(self.derivation),
            "error_rate": self.error_rate.to_dict(),
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "contradicts": list(self.contradicts),
            "completeness": list(self.completeness),
            "method": self.method,
        }


def canonical_payload(
    *,
    claim: str,
    source_type: EvidenceSource | str,
    data: dict[str, Any] | None,
    reference: str | None,
    tier: ClaimTier | str,
    derivation: tuple[str, ...] = (),
    method: str | None = None,
    completeness: tuple[str, ...] = (),
) -> dict[str, Any]:
    """
    Build the canonical dictionary that an artifact's content hash covers.

    This is the single definition, used by both :class:`EvidenceBuilder` and
    :class:`EvidenceValidator`. Previously each constructed the payload
    independently, so a change to one silently broke hash verification in the
    other -- and a silent chain-of-custody failure is exactly the defect this
    hash exists to prevent.

    Derivation is included so that re-parenting an inference changes its
    fingerprint; tier is included so that quietly upgrading a structural
    grouping to an identity claim does too.
    """
    return {
        "claim": claim,
        "source_type": str(source_type),
        "data": data or {},
        "reference": reference,
        "tier": str(tier),
        "derivation": sorted(derivation),
        "method": method,
        "completeness": sorted(completeness),
    }


@dataclass(frozen=True, slots=True)
class EvidenceChain:
    """
    An ordered chain of evidence artifacts leading to a conclusion.
    """

    conclusion: str
    artifacts: tuple[EvidenceArtifact, ...] = ()
    aggregated_confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conclusion": self.conclusion,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "aggregated_confidence": self.aggregated_confidence,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }
