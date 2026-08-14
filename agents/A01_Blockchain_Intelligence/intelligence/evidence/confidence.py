"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.confidence

Purpose:
    Derive an aggregate confidence value from evidence strength.

    Applies a conservative bias (favoring false negatives over false
    positives): low-reliability sources dampen the aggregate rather
    than inflating it, and contradicted or expired artifacts reduce
    confidence.

Enforced rules
--------------
1. Tier ceilings
    Combination may never lift a claim above the ceiling for its tier. The
    *category* of available evidence is what is limited, and no quantity of
    it changes that.
2. Correlation collapse
    Artifacts sharing a common ancestor count once. Five restatements of one
    provider's opinion are one source, not five confirmations.
3. Unmeasured error rates
    Evidence from a method that has never measured how often it is wrong is
    capped, however reliable its source category looks.
4. Time-based expiry
    Behavioural classifications drift. An artifact past its expiry is treated
    as degraded even if nothing has marked its status yet.

See docs/intelligence/evidence-standard.md and
docs/intelligence/attribution-doctrine.md section 7.
"""

from __future__ import annotations

from datetime import datetime

from ..schemas.evidence import (
    ClaimTier,
    ErrorRateState,
    EvidenceArtifact,
    EvidenceStatus,
    UNMEASURED_ERROR_RATE_CEILING,
    tier_ceiling,
)
from .evidence_graph import EvidenceGraph
from .source_rank import SourceRanker

# Per-artifact dampening factors for degraded evidence.
_CONTRADICTION_DAMPEN = 0.85
_EXPIRY_DAMPEN = 0.9


def _key(artifact: EvidenceArtifact) -> str:
    """Stable identity for an artifact."""
    return artifact.content_hash or artifact.claim


class ConfidenceEngine:
    """
    Computes an aggregate 0..1 confidence from a set of evidence.

    The aggregate is source-weighted, conservative, correlation-aware, and
    bounded by the ceiling of the claim tier being asserted.
    """

    def __init__(
        self,
        source_ranker: SourceRanker | None = None,
        graph: EvidenceGraph | None = None,
    ) -> None:
        self._ranker = source_ranker or SourceRanker()
        #: Optional. When supplied, artifacts sharing an ancestor are
        #: collapsed before combination. Without it, only the artifacts'
        #: own declared derivation is available for correlation detection.
        self._graph = graph

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(
        self,
        artifacts: list[EvidenceArtifact],
        *,
        tier: ClaimTier | str | None = None,
        now: datetime | None = None,
    ) -> float:
        """
        Compute aggregate confidence weighted by source reliability.

        Contradicted and expired artifacts are excluded from the supporting
        set and dampen the aggregate. Correlated artifacts are collapsed to a
        single contribution. Returns 0.0 for an empty or fully-degraded set.

        ``tier`` bounds the result. When omitted, the strictest tier present
        among the supporting artifacts is used, so a set mixing a structural
        grouping with an identity claim cannot be reported at the structural
        ceiling.
        """
        if not artifacts:
            return 0.0

        effective = [a for a in artifacts if not self._is_degraded(a, now)]
        if not effective:
            return 0.0

        degraded = [a for a in artifacts if self._is_degraded(a, now)]
        contradicted = sum(
            1 for a in degraded if a.status == EvidenceStatus.CONTRADICTED
        )
        expired = len(degraded) - contradicted

        representatives = self._collapse_correlated(effective)

        weighted = 0.0
        total = 0.0
        for artifact in representatives:
            reliability = self._ranker.reliability(artifact.source_type)
            weighted += self._artifact_confidence(artifact) * reliability
            total += reliability

        if total <= 0:
            return 0.0

        base = max(0.0, min(1.0, weighted / total))

        # Conservative dampening: contradictions and expired artifacts
        # each lower confidence toward zero.
        dampen = (_CONTRADICTION_DAMPEN**contradicted) * (_EXPIRY_DAMPEN**expired)
        value = base * dampen

        ceiling = (
            tier_ceiling(tier)
            if tier is not None
            else self._strictest_ceiling(representatives)
        )
        return round(max(0.0, min(ceiling, value)), 6)

    def tier_score(
        self,
        artifacts: list[EvidenceArtifact],
        tier: ClaimTier | str,
        *,
        now: datetime | None = None,
    ) -> float:
        """
        Compute aggregate confidence using only artifacts of a given tier.

        Enforces the tier framework: structural, attribution, and operator
        claims are scored independently, each against its own ceiling.
        """
        tier = ClaimTier(tier) if not isinstance(tier, ClaimTier) else tier
        subset = [
            a for a in artifacts if a.tier == tier or str(a.tier) == str(tier)
        ]
        return self.score(subset, tier=tier, now=now)

    def explain(
        self,
        artifacts: list[EvidenceArtifact],
        *,
        tier: ClaimTier | str | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """
        Return the aggregate alongside the reasoning behind it.

        A confidence value with no visible derivation cannot be reviewed, and
        an unreviewable number is exactly what the evidence standard exists to
        prevent. This is what reporting should render, not the bare float.
        """
        effective = [a for a in artifacts if not self._is_degraded(a, now)]
        representatives = self._collapse_correlated(effective)
        collapsed = len(effective) - len(representatives)

        ceiling = (
            tier_ceiling(tier)
            if tier is not None
            else self._strictest_ceiling(representatives or effective)
        )
        value = self.score(artifacts, tier=tier, now=now)

        return {
            "confidence": value,
            "artifacts_total": len(artifacts),
            "artifacts_supporting": len(effective),
            "artifacts_degraded": len(artifacts) - len(effective),
            "correlated_collapsed": collapsed,
            "ceiling": ceiling,
            "ceiling_binding": value >= ceiling > 0,
            "unmeasured_sources": sum(
                1
                for a in representatives
                if a.error_rate.state is ErrorRateState.UNMEASURED
            ),
            "contributing": [
                {
                    "claim": a.claim,
                    "tier": str(a.tier),
                    "source": str(a.source_type),
                    "reliability": self._ranker.reliability(a.source_type),
                    "confidence": self._artifact_confidence(a),
                }
                for a in representatives
            ],
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_degraded(artifact: EvidenceArtifact, now: datetime | None) -> bool:
        """
        True when an artifact must not contribute to the supporting set.

        Time-based expiry is checked directly rather than trusting status,
        because nothing guarantees a sweep has run to mark it.
        """
        if artifact.status in (
            EvidenceStatus.CONTRADICTED,
            EvidenceStatus.EXPIRED,
        ):
            return True
        return artifact.is_expired(now)

    @staticmethod
    def _artifact_confidence(artifact: EvidenceArtifact) -> float:
        """
        An artifact's confidence, bounded by its own tier and error-rate state.

        Applied again here rather than trusting the builder, because artifacts
        can be constructed directly and this is the last gate before a number
        reaches a consumer.
        """
        value = max(0.0, min(1.0, artifact.confidence))
        value = min(value, tier_ceiling(artifact.tier))
        if not artifact.error_rate.is_known:
            value = min(value, UNMEASURED_ERROR_RATE_CEILING)
        return value

    @staticmethod
    def _strictest_ceiling(artifacts: list[EvidenceArtifact]) -> float:
        """
        The lowest tier ceiling present in the set.

        A conclusion inherits the weakest link in its chain, so a set mixing
        tiers is bounded by the most demanding claim it contains.
        """
        if not artifacts:
            return 0.0
        return min(tier_ceiling(a.tier) for a in artifacts)

    def _collapse_correlated(
        self,
        artifacts: list[EvidenceArtifact],
    ) -> list[EvidenceArtifact]:
        """
        Reduce each group of correlated artifacts to a single representative.

        Correlation is determined from the evidence graph when one is
        attached, and otherwise from the artifacts' own declared derivation:
        two artifacts sharing a parent are restatements of the same upstream
        fact.

        The representative is the group's strongest member, so collapsing
        removes double-counting without discarding the best evidence.
        """
        if len(artifacts) < 2:
            return list(artifacts)

        by_key = {_key(a): a for a in artifacts}

        if self._graph is not None:
            groups = self._graph.correlation_groups(list(by_key))
        else:
            groups = self._groups_from_derivation(artifacts)

        representatives: list[EvidenceArtifact] = []
        for group in groups:
            members = [by_key[k] for k in group if k in by_key]
            if not members:
                continue
            representatives.append(
                max(members, key=self._artifact_confidence)
            )

        return representatives or list(artifacts)

    @staticmethod
    def _groups_from_derivation(
        artifacts: list[EvidenceArtifact],
    ) -> list[set[str]]:
        """
        Group artifacts by shared declared ancestry, without a graph.

        Union-find over each artifact's own derivation set. Artifacts with no
        declared parents are independent by definition and form singletons.
        """
        keys = [_key(a) for a in artifacts]
        lineage = {
            _key(a): set(a.derivation) | {_key(a)} for a in artifacts
        }

        remaining = list(keys)
        groups: list[set[str]] = []

        while remaining:
            current = remaining.pop(0)
            group = {current}
            shared = set(lineage[current])

            merged = True
            while merged:
                merged = False
                for other in list(remaining):
                    # Singletons with no parents never merge: their only
                    # lineage member is themselves.
                    if lineage[other] & shared:
                        group.add(other)
                        shared |= lineage[other]
                        remaining.remove(other)
                        merged = True

            groups.append(group)

        return groups
