"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the evidence spine.

These cover the invariants that make an A01 conclusion defensible: tier
confidence ceilings, correlation collapse, evidence-graph acyclicity and leaf
grounding, hash integrity across builder and validator, and expiry.

Each test names the doctrine rule it protects, so a failure says which
guarantee broke rather than merely which assertion tripped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intelligence.evidence.builder import EvidenceBuilder
from intelligence.evidence.confidence import ConfidenceEngine
from intelligence.evidence.evidence_graph import (
    EvidenceCycleError,
    EvidenceGraph,
)
from intelligence.evidence.validator import EvidenceValidator
from intelligence.schemas.evidence import (
    ClaimTier,
    ErrorRate,
    ErrorRateState,
    EvidenceArtifact,
    EvidenceSource,
    EvidenceStatus,
    UNMEASURED_ERROR_RATE_CEILING,
    tier_ceiling,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)

MEASURED = ErrorRate(
    state=ErrorRateState.MEASURED,
    value=0.005,
    sample_size=10_000,
    measured_at=NOW,
)


@pytest.fixture
def builder() -> EvidenceBuilder:
    return EvidenceBuilder()


@pytest.fixture
def validator() -> EvidenceValidator:
    return EvidenceValidator()


def artifact(
    claim: str = "claim",
    *,
    tier: ClaimTier = ClaimTier.STRUCTURAL,
    confidence: float = 0.9,
    source: EvidenceSource = EvidenceSource.ON_CHAIN,
    derivation: tuple[str, ...] = (),
    error_rate: ErrorRate | None = None,
    status: EvidenceStatus = EvidenceStatus.COLLECTED,
    expires_at: datetime | None = None,
) -> EvidenceArtifact:
    """Construct an artifact directly, bypassing the builder's clamping."""
    return EvidenceArtifact(
        claim=claim,
        source_type=source,
        data={"k": claim},
        confidence=confidence,
        tier=tier,
        content_hash=f"hash-{claim}",
        derivation=derivation,
        error_rate=error_rate or MEASURED,
        status=status,
        expires_at=expires_at,
    )


# =============================================================================
# Tier ceilings
# =============================================================================


class TestTierCeilings:
    """An identity claim must not be assertable at structural confidence."""

    def test_ceilings_are_ordered_by_evidentiary_demand(self) -> None:
        # OPERATOR asserts control, not just identity, so it is most demanding.
        assert tier_ceiling(ClaimTier.STRUCTURAL) == 0.95
        assert tier_ceiling(ClaimTier.ATTRIBUTION) == 0.40
        assert tier_ceiling(ClaimTier.OPERATOR) == 0.30

    def test_unknown_tier_falls_back_to_strictest(self) -> None:
        # A typo must not silently unlock high confidence.
        assert tier_ceiling("not-a-tier") == 0.30

    def test_builder_clamps_attribution_to_ceiling(
        self, builder: EvidenceBuilder
    ) -> None:
        art = builder.build(
            claim="cluster X is Binance",
            source_type=EvidenceSource.GOVERNMENT,
            data={"x": 1},
            confidence=0.99,
            tier=ClaimTier.ATTRIBUTION,
            error_rate=MEASURED,
        )
        assert art.confidence == 0.40

    def test_builder_allows_high_structural_confidence(
        self, builder: EvidenceBuilder
    ) -> None:
        art = builder.build(
            claim="inputs co-spent",
            source_type=EvidenceSource.ON_CHAIN,
            data={"x": 1},
            confidence=0.95,
            tier=ClaimTier.STRUCTURAL,
            error_rate=MEASURED,
        )
        assert art.confidence == 0.95

    def test_unmeasured_error_rate_caps_confidence(
        self, builder: EvidenceBuilder
    ) -> None:
        art = builder.build(
            claim="inputs co-spent",
            source_type=EvidenceSource.ON_CHAIN,
            data={"x": 1},
            confidence=0.95,
            tier=ClaimTier.STRUCTURAL,
        )
        assert art.confidence == UNMEASURED_ERROR_RATE_CEILING

    def test_validator_rejects_artifact_above_ceiling(
        self, validator: EvidenceValidator
    ) -> None:
        bad = artifact(tier=ClaimTier.ATTRIBUTION, confidence=0.9)
        errors = validator.validate(bad)
        assert any("ceiling" in e for e in errors)


# =============================================================================
# Combination discipline
# =============================================================================


class TestConfidenceCombination:
    """Accumulating weak signals must not manufacture certainty."""

    def test_many_weak_signals_cannot_exceed_tier_ceiling(self) -> None:
        engine = ConfidenceEngine()
        many = [
            artifact(f"a{i}", tier=ClaimTier.ATTRIBUTION, confidence=0.4)
            for i in range(20)
        ]
        assert engine.score(many) <= tier_ceiling(ClaimTier.ATTRIBUTION)

    def test_mixed_tiers_bound_by_strictest(self) -> None:
        engine = ConfidenceEngine()
        mixed = [
            artifact("structural", tier=ClaimTier.STRUCTURAL, confidence=0.95),
            artifact("operator", tier=ClaimTier.OPERATOR, confidence=0.30),
        ]
        # A conclusion inherits the weakest link in its chain.
        assert engine.score(mixed) <= tier_ceiling(ClaimTier.OPERATOR)

    def test_correlated_evidence_collapses(self) -> None:
        """Five restatements of one upstream fact are one source."""
        engine = ConfidenceEngine()
        shared = ("hash-root",)
        correlated = [
            artifact(f"restatement{i}", derivation=shared, confidence=0.6)
            for i in range(5)
        ]
        independent = [
            artifact(f"independent{i}", confidence=0.6) for i in range(5)
        ]

        detail = engine.explain(correlated)
        assert detail["correlated_collapsed"] == 4
        assert len(detail["contributing"]) == 1

        detail_independent = engine.explain(independent)
        assert detail_independent["correlated_collapsed"] == 0

    def test_empty_set_scores_zero(self) -> None:
        assert ConfidenceEngine().score([]) == 0.0

    def test_contradicted_evidence_dampens(self) -> None:
        engine = ConfidenceEngine()
        clean = [artifact("a", confidence=0.9)]
        disputed = [
            artifact("a", confidence=0.9),
            artifact("b", confidence=0.9, status=EvidenceStatus.CONTRADICTED),
        ]
        assert engine.score(disputed) < engine.score(clean)

    def test_tier_score_isolates_tier(self) -> None:
        engine = ConfidenceEngine()
        arts = [
            artifact("s", tier=ClaimTier.STRUCTURAL, confidence=0.9),
            artifact("a", tier=ClaimTier.ATTRIBUTION, confidence=0.4),
        ]
        assert engine.tier_score(arts, ClaimTier.STRUCTURAL) == pytest.approx(
            0.9, abs=1e-6
        )

    def test_explain_reports_binding_ceiling(self) -> None:
        engine = ConfidenceEngine()
        arts = [
            artifact("a", tier=ClaimTier.ATTRIBUTION, confidence=0.4)
            for _ in range(3)
        ]
        detail = engine.explain(arts)
        assert detail["ceiling"] == 0.40
        assert detail["ceiling_binding"] is True


# =============================================================================
# Expiry
# =============================================================================


class TestExpiry:
    """A stale behavioural classification is not a current claim."""

    def test_expired_artifact_excluded(self) -> None:
        engine = ConfidenceEngine()
        stale = artifact("stale", expires_at=NOW - timedelta(days=1))
        assert engine.score([stale], now=NOW) == 0.0

    def test_expiry_checked_by_time_not_only_status(self) -> None:
        # Nothing guarantees a sweep has run to mark status EXPIRED.
        stale = artifact("stale", expires_at=NOW - timedelta(days=1))
        assert stale.status == EvidenceStatus.COLLECTED
        assert stale.is_expired(NOW) is True

    def test_unexpired_artifact_contributes(self) -> None:
        engine = ConfidenceEngine()
        fresh = artifact("fresh", expires_at=NOW + timedelta(days=30))
        assert engine.score([fresh], now=NOW) > 0.0


# =============================================================================
# Evidence graph invariants
# =============================================================================


class TestEvidenceGraph:
    """A claim must not support itself, and must rest on observed facts."""

    def test_self_support_rejected(self) -> None:
        graph = EvidenceGraph()
        a = artifact("a")
        with pytest.raises(EvidenceCycleError):
            graph.link(a, a)

    def test_cycle_rejected(self) -> None:
        graph = EvidenceGraph()
        a, b, c = artifact("a"), artifact("b"), artifact("c")
        graph.link(a, b)
        graph.link(b, c)
        with pytest.raises(EvidenceCycleError):
            graph.link(c, a)

    def test_self_derivation_rejected(self) -> None:
        graph = EvidenceGraph()
        with pytest.raises(EvidenceCycleError):
            graph.add(artifact("a", derivation=("hash-a",)))

    def test_ancestors_are_transitive(self) -> None:
        graph = EvidenceGraph()
        a, b, c = artifact("a"), artifact("b"), artifact("c")
        graph.link(a, b)
        graph.link(b, c)
        assert graph.ancestors("hash-c") == {"hash-a", "hash-b"}

    def test_inference_on_inference_is_ungrounded(self) -> None:
        graph = EvidenceGraph()
        guess = artifact("guess", source=EvidenceSource.INFERRED)
        conclusion = artifact("conclusion", source=EvidenceSource.INFERRED)
        graph.link(guess, conclusion)

        assert graph.is_grounded("hash-conclusion") is False
        assert "hash-guess" in graph.ungrounded_roots("hash-conclusion")

    def test_chain_grounded_in_onchain_fact_is_valid(self) -> None:
        graph = EvidenceGraph()
        fact = artifact("fact", source=EvidenceSource.ON_CHAIN)
        conclusion = artifact("conclusion", source=EvidenceSource.INFERRED)
        graph.link(fact, conclusion)

        assert graph.is_grounded("hash-conclusion") is True
        assert graph.validate() == []

    def test_ai_output_cannot_ground_a_chain(self) -> None:
        """Model output is never a leaf; it must rest on real evidence."""
        graph = EvidenceGraph()
        model = artifact("model says", source=EvidenceSource.AI)
        conclusion = artifact("conclusion", source=EvidenceSource.INFERRED)
        graph.link(model, conclusion)

        assert graph.is_grounded("hash-conclusion") is False

    def test_correlation_groups_partition_correctly(self) -> None:
        graph = EvidenceGraph()
        root = artifact("root", source=EvidenceSource.ON_CHAIN)
        left = artifact("left", derivation=("hash-root",))
        right = artifact("right", derivation=("hash-root",))
        lone = artifact("lone", source=EvidenceSource.ON_CHAIN)
        for art in (root, left, right, lone):
            graph.add(art)

        groups = graph.correlation_groups(
            ["hash-left", "hash-right", "hash-lone"]
        )
        assert len(groups) == 2
        assert {"hash-left", "hash-right"} in groups
        assert {"hash-lone"} in groups

    def test_graph_backed_engine_collapses_shared_ancestry(self) -> None:
        graph = EvidenceGraph()
        root = artifact("root", source=EvidenceSource.ON_CHAIN)
        left = artifact("left", derivation=("hash-root",), confidence=0.6)
        right = artifact("right", derivation=("hash-root",), confidence=0.6)
        for art in (root, left, right):
            graph.add(art)

        engine = ConfidenceEngine(graph=graph)
        assert engine.explain([left, right])["correlated_collapsed"] == 1


# =============================================================================
# Hash integrity
# =============================================================================


class TestHashIntegrity:
    """Builder and validator must agree, or custody checks silently pass."""

    def test_built_artifact_validates(
        self, builder: EvidenceBuilder, validator: EvidenceValidator
    ) -> None:
        art = builder.build(
            claim="co-spend observed",
            source_type=EvidenceSource.ON_CHAIN,
            data={"tx": "0xabc"},
            confidence=0.9,
            tier=ClaimTier.STRUCTURAL,
            error_rate=MEASURED,
            method="common_input_ownership@1",
        )
        assert validator.validate(art) == []

    def test_tampered_tier_breaks_hash(
        self, builder: EvidenceBuilder, validator: EvidenceValidator
    ) -> None:
        """Quietly upgrading a grouping to an identity claim must be caught."""
        art = builder.build(
            claim="co-spend observed",
            source_type=EvidenceSource.ON_CHAIN,
            data={"tx": "0xabc"},
            confidence=0.3,
            tier=ClaimTier.STRUCTURAL,
            error_rate=MEASURED,
        )
        tampered = EvidenceArtifact(
            claim=art.claim,
            source_type=art.source_type,
            data=art.data,
            confidence=art.confidence,
            tier=ClaimTier.ATTRIBUTION,
            content_hash=art.content_hash,
            error_rate=art.error_rate,
        )
        assert "evidence content hash mismatch" in validator.validate(tampered)

    def test_tampered_derivation_breaks_hash(
        self, builder: EvidenceBuilder, validator: EvidenceValidator
    ) -> None:
        """Re-parenting an inference must change its fingerprint."""
        art = builder.build(
            claim="derived",
            source_type=EvidenceSource.INFERRED,
            data={"x": 1},
            tier=ClaimTier.STRUCTURAL,
            derivation=("hash-parent",),
            error_rate=MEASURED,
        )
        moved = EvidenceArtifact(
            claim=art.claim,
            source_type=art.source_type,
            data=art.data,
            confidence=art.confidence,
            tier=art.tier,
            content_hash=art.content_hash,
            derivation=("hash-other-parent",),
            error_rate=art.error_rate,
        )
        assert "evidence content hash mismatch" in validator.validate(moved)


# =============================================================================
# Error-rate declarations
# =============================================================================


class TestErrorRateDeclarations:
    """Claimed rigour must carry the support that rigour requires."""

    def test_measured_without_sample_size_rejected(
        self, validator: EvidenceValidator
    ) -> None:
        bad = artifact(
            error_rate=ErrorRate(state=ErrorRateState.MEASURED, value=0.01)
        )
        assert "measured error rate has no sample size" in validator.validate(bad)

    def test_stated_without_citation_rejected(
        self, validator: EvidenceValidator
    ) -> None:
        bad = artifact(
            error_rate=ErrorRate(state=ErrorRateState.STATED, value=0.005)
        )
        assert "stated error rate has no citation" in validator.validate(bad)

    def test_out_of_range_value_rejected(
        self, validator: EvidenceValidator
    ) -> None:
        bad = artifact(
            error_rate=ErrorRate(
                state=ErrorRateState.MEASURED, value=1.5, sample_size=10
            )
        )
        assert "error rate value out of range" in validator.validate(bad)

    def test_unmeasured_is_valid_but_capped(
        self, builder: EvidenceBuilder, validator: EvidenceValidator
    ) -> None:
        # Declaring ignorance is acceptable; hiding it is not.
        art = builder.build(
            claim="heuristic guess",
            source_type=EvidenceSource.ON_CHAIN,
            data={"x": 1},
            confidence=0.95,
            tier=ClaimTier.STRUCTURAL,
        )
        assert validator.validate(art) == []
        assert art.confidence == UNMEASURED_ERROR_RATE_CEILING
        assert ConfidenceEngine().score([art]) <= UNMEASURED_ERROR_RATE_CEILING
