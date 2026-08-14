"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the rebuilt domain analyzers and the pipeline wiring.

The whale tests exist largely to pin down behaviour the previous
implementation got wrong: an absolute unit-less threshold, and no folding of
transfers that are not economic movements at all.
"""

from __future__ import annotations

from intelligence.analysis.anomaly import (
    MIN_POPULATION,
    AnomalyAnalyzer,
    Grade,
    modified_z_scores,
)
from intelligence.analysis.dormant import DormantAnalyzer
from intelligence.analysis.exchange import (
    DIRECTIONAL_RATIO,
    MIN_ATTRIBUTED,
    Direction,
    ExchangeFlowAnalyzer,
    imbalance,
)
from intelligence.analysis.whale import WhaleAnalyzer
from intelligence.core.engine import IntelligenceEngine
from intelligence.schemas.evidence import ClaimTier

POPULATION = [1, 5, 12, 40, 110, 480, 1200, 5400, 21000]

#: A population with spread but no outlier, large enough to be judged.
STEADY = [100 + (i % 7) * 3 for i in range(MIN_POPULATION + 10)]


# =============================================================================
# Anomaly
# =============================================================================


class TestAnomalyAnalyzer:
    def test_a_short_population_is_insufficient_not_normal(self) -> None:
        """
        The failure the whole evidence standard exists to prevent: reporting
        "nothing unusual" from a sample too small to have said otherwise.
        """
        result = AnomalyAnalyzer().analyze(
            {"address": "0xabc", "transfer_population": [1, 2, 3], "absence_meaningful": True}
        )

        assert result.data["grade"] == Grade.INSUFFICIENT
        assert not result.data["determinable"]
        assert not result.data["is_anomalous"]
        assert not result.evidence

    def test_a_clean_population_with_coverage_is_normal(self) -> None:
        result = AnomalyAnalyzer().analyze(
            {"address": "0xabc", "transfer_population": STEADY, "absence_meaningful": True}
        )

        assert result.data["grade"] == Grade.NORMAL
        assert not result.data["is_anomalous"]

    def test_a_clean_population_without_coverage_cannot_claim_normal(self) -> None:
        """
        NORMAL is a negative claim. Without a window that licenses an absence it
        is a statement about what was never looked at.
        """
        result = AnomalyAnalyzer().analyze(
            {"address": "0xabc", "transfer_population": STEADY, "absence_meaningful": False}
        )

        assert result.data["grade"] == Grade.INSUFFICIENT
        assert "cannot license an absence" in result.data["reason"]

    def test_an_outlier_is_detected_without_coverage(self) -> None:
        """
        A positive claim needs no absence licence: the outlying value was
        observed, whatever else was missed.
        """
        result = AnomalyAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": [*STEADY, 10_000_000],
                "absence_meaningful": False,
            }
        )

        assert result.data["is_anomalous"]
        assert result.data["outlier_count"] >= 1
        assert result.evidence
        assert result.evidence[0].tier is ClaimTier.STRUCTURAL

    def test_a_single_extreme_value_does_not_mask_itself(self) -> None:
        """
        The reason this uses MAD rather than mean and standard deviation.

        One value four orders of magnitude above the rest inflates the standard
        deviation enough to bring its own z-score back under the cutoff — the
        detector is then blindest at exactly the case it was built for. The
        median absolute deviation has a 50% breakdown point, so one outlier
        cannot move it.
        """
        values = [*STEADY, 10_000_000.0]

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        naive_z = abs(10_000_000.0 - mean) / (variance**0.5)

        scores, _, _ = modified_z_scores(values)

        assert naive_z < 6, "the naive score is dragged down by the outlier itself"
        assert max(scores) > 100, "the robust score is not"

    def test_a_log_normal_population_is_not_flagged_wholesale(self) -> None:
        """
        The regression for a detector that called a third of normal traffic
        anomalous.

        Transfer values are log-normal across many orders of magnitude. Measured
        on raw values the MAD is tiny against that spread and almost everything
        clears the cutoff: on 5,000 real ethereum transfers the first version of
        this module flagged 1,581 of them — 31.6% — with a maximum z of 88,104.

        This population is built to the same shape. Remove the log transform and
        this test fails, which is the point of it.
        """
        # Deterministic log-uniform spread over eight decades, the shape a real
        # transfer population takes. No seeding needed and no outlier planted.
        values = [10 ** (12 + (i % 89) * 8 / 89) for i in range(500)]

        scores, _, mad = modified_z_scores(values)
        outliers = [score for score in scores if score >= 3.5]

        assert mad > 0
        assert len(outliers) / len(values) < 0.02, (
            f"{len(outliers)} of {len(values)} flagged; a detector that fires on "
            "ordinary traffic is not a detector"
        )

    def test_the_analyzer_reports_a_wide_ordinary_population_as_normal(self) -> None:
        """The same property through the public surface, not just the helper."""
        values = [10 ** (12 + (i % 89) * 8 / 89) for i in range(500)]

        result = AnomalyAnalyzer().analyze(
            {"address": "0xabc", "transfer_population": values,
             "absence_meaningful": True}
        )

        assert result.data["grade"] == Grade.NORMAL
        assert result.data["outlier_count"] == 0
        assert not result.evidence

    def test_a_population_with_no_spread_is_insufficient(self) -> None:
        """
        Every value identical means no scale to measure deviation against.
        Any difference would score infinitely, so the honest answer is that the
        population cannot support the question.
        """
        result = AnomalyAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": [500.0] * (MIN_POPULATION + 5),
                "absence_meaningful": True,
            }
        )

        assert result.data["grade"] == Grade.INSUFFICIENT
        assert "no spread" in result.data["reason"]

    def test_zero_value_transfers_are_excluded(self) -> None:
        """
        Contract calls that move nothing are most of chain traffic. Left in,
        they drag the median to zero and every real transfer becomes an outlier.
        """
        result = AnomalyAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": [*STEADY, *([0] * 100)],
                "absence_meaningful": True,
            }
        )

        assert result.data["population_size"] == len(STEADY)
        assert result.data["grade"] == Grade.NORMAL

    def test_the_analyzer_never_claims_an_interpretation(self) -> None:
        """
        Section 13: anomaly is not bullish, bearish, or manipulation.
        Classification comes strictly after analysis, and this detector is
        analysis.
        """
        result = AnomalyAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": [*STEADY, 10_000_000],
                "absence_meaningful": True,
            }
        )

        rendered = (result.summary + str(result.data)).lower()
        for word in ("bullish", "bearish", "manipulat", "wash", "smart money", "pump"):
            assert word not in rendered, f"interpretation leaked: {word}"

    def test_the_grade_vocabulary_is_the_evidence_standard_one(self) -> None:
        allowed = {
            Grade.NORMAL, Grade.UNUSUAL, Grade.SUSPICIOUS,
            Grade.HIGH_RISK, Grade.INSUFFICIENT,
        }
        for population in ([1, 2], STEADY, [*STEADY, 10_000_000]):
            result = AnomalyAnalyzer().analyze(
                {"address": "0xabc", "transfer_population": population,
                 "absence_meaningful": True}
            )
            assert result.data["grade"] in allowed

    def test_the_detector_reaches_the_pipeline(self) -> None:
        package = IntelligenceEngine().run(
            {
                "address": "0xabc",
                "transfer_population": [*STEADY, 10_000_000],
                "absence_meaningful": True,
            }
        )

        assert "anomaly" in package.metadata["findings"]


# =============================================================================
# Whale
# =============================================================================


class TestWhaleAnalyzer:
    def test_large_transfer_flagged_by_percentile(self) -> None:
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [{"value": 999_999}],
            }
        )
        assert result.data["is_whale"] is True
        assert "percentile" in result.data["triggers"][0]

    def test_small_transfer_not_flagged(self) -> None:
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [{"value": 2}],
            }
        )
        assert result.data["is_whale"] is False

    def test_supply_fraction_triggers_without_population(self) -> None:
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "circulating_supply": 1_000_000,
                "large_transfers": [{"value": 50_000}],
            }
        )
        assert result.data["is_whale"] is True
        assert result.data["triggers"] == ["supply_fraction"]

    def test_non_economic_transfers_suppressed(self) -> None:
        """Wrapping and internal rebalancing are not whale activity."""
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [
                    {"value": 999_999, "kind": "wrap"},
                    {"value": 999_999, "kind": "internal"},
                    {"value": 999_999, "kind": "bridge_lock"},
                ],
            }
        )
        assert result.data["is_whale"] is False
        assert result.data["suppressed_transfer_count"] == 3
        assert result.data["large_transfer_count"] == 0

    def test_exchange_deposit_reads_as_sell_pressure(self) -> None:
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [
                    {
                        "value": 999_999,
                        "direction": "out",
                        "counterparty_type": "exchange",
                    }
                ],
            }
        )
        flow = result.data["flow"]
        assert flow["exchange_signal"] == "deposit_to_exchange"
        assert flow["posture"] == "distribution"
        assert "sell pressure" in flow["interpretation"]

    def test_exchange_withdrawal_reads_as_supply_removal(self) -> None:
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [
                    {
                        "value": 999_999,
                        "direction": "in",
                        "counterparty_type": "exchange",
                    }
                ],
            }
        )
        flow = result.data["flow"]
        assert flow["exchange_signal"] == "withdrawal_from_exchange"
        assert flow["posture"] == "accumulation"

    def test_no_reference_data_is_reported_as_indeterminable(self) -> None:
        """'No whale activity' and 'cannot tell' are different claims."""
        result = WhaleAnalyzer().analyze(
            {"address": "0xabc", "large_transfers": [{"value": 5}]}
        )
        assert result.data["determinable"] is False
        assert "not determinable" in result.summary

    def test_evidence_is_structural_not_attribution(self) -> None:
        """A large transfer is an observation, not a claim about who moved it."""
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [{"value": 999_999}],
            }
        )
        assert all(a.tier == ClaimTier.STRUCTURAL for a in result.evidence)

    def test_malformed_values_do_not_crash(self) -> None:
        result = WhaleAnalyzer().analyze(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [
                    {"value": None}, {"value": "abc"}, {"value": float("nan")}, "junk",
                ],
            }
        )
        assert result.data["is_whale"] is False


# =============================================================================
# Dormant
# =============================================================================


class TestDormantAnalyzer:
    BASE = {
        "address": "0xabc",
        "as_of": "2026-01-01T00:00:00Z",
        "balance": 100_000,
        "balance_percentile_rank": 99.9,
        "reactivated": True,
    }

    def test_long_dormancy_reactivation_detected(self) -> None:
        result = DormantAnalyzer().analyze(
            {**self.BASE, "last_outbound_at": "2018-01-01T00:00:00Z"}
        )
        assert result.data["reactivated"] is True
        assert result.data["dormancy_band"] == "ancient"
        assert result.data["signal"]["severity"] == "high"

    def test_recent_activity_not_dormant(self) -> None:
        result = DormantAnalyzer().analyze(
            {**self.BASE, "last_outbound_at": "2025-12-01T00:00:00Z"}
        )
        assert result.data["reactivated"] is False
        assert result.data["is_dormant"] is False

    def test_no_movement_is_not_reactivation(self) -> None:
        result = DormantAnalyzer().analyze(
            {
                **self.BASE,
                "last_outbound_at": "2018-01-01T00:00:00Z",
                "reactivated": False,
            }
        )
        assert result.data["reactivated"] is False

    def test_vesting_unlock_suppressed(self) -> None:
        """A scheduled, publicly-known unlock is not a holder decision."""
        result = DormantAnalyzer().analyze(
            {
                **self.BASE,
                "last_outbound_at": "2018-01-01T00:00:00Z",
                "movement_context": "vesting_unlock",
            }
        )
        assert result.data["reactivated"] is False
        assert result.data["suppressed_as_benign"] is True

    def test_dust_wallet_not_material(self) -> None:
        result = DormantAnalyzer().analyze(
            {
                **self.BASE,
                "last_outbound_at": "2018-01-01T00:00:00Z",
                "balance": 0.0001,
                "balance_percentile_rank": 10.0,
            }
        )
        assert result.data["is_material"] is False
        assert result.data["reactivated"] is False

    def test_missing_history_is_indeterminable(self) -> None:
        result = DormantAnalyzer().analyze({"address": "0xabc"})
        assert result.data["determinable"] is False

    def test_epoch_timestamps_accepted(self) -> None:
        result = DormantAnalyzer().analyze(
            {**self.BASE, "last_outbound_at": 1_500_000_000}
        )
        assert result.data["is_dormant"] is True


# =============================================================================
# Exchange flow
# =============================================================================

ETH = 10**18


def flow_subject(
    *,
    attributed: int = 40,
    inflow: int = 30 * ETH,
    outflow: int = 10 * ETH,
    entities: dict | None = None,
    **overrides,
) -> dict:
    """A subject shaped the way ``ExchangeFlowSkill`` composes one."""
    body = {
        "chain": "ethereum",
        "labelled_addresses": 2859,
        "labelled_entities": 316,
        "label_source": "community evm_cex list",
        "label_confidence": 0.5,
        "transfers_scanned": 25_743,
        "attributed": attributed,
        "totals": {
            "inflow_count": 20,
            "inflow_value": str(inflow),
            "outflow_count": 20,
            "outflow_value": str(outflow),
            "internal_count": 0,
            "internal_value": "0",
            "net_value": str(inflow - outflow),
            "direction": "inflow" if inflow >= outflow else "outflow",
        },
        "entities": entities
        if entities is not None
        else {
            "Binance": {"inflow_value": inflow, "outflow_value": outflow},
        },
        "bounds": ["native value only; token and stablecoin transfers are not attributed"],
    }
    body.update(overrides)
    return {"address": "0xabc", "exchange_flow": body}


class TestImbalance:
    def test_a_perfectly_two_way_window_is_zero(self) -> None:
        assert imbalance(500, 500) == 0.0

    def test_a_one_way_window_is_one(self) -> None:
        assert imbalance(500, 0) == 1.0

    def test_an_empty_window_does_not_divide_by_zero(self) -> None:
        assert imbalance(0, 0) == 0.0

    def test_the_ratio_is_scale_free(self) -> None:
        """The same shape at wei scale and at ether scale is the same number."""
        assert imbalance(3 * ETH, 1 * ETH) == imbalance(3, 1)


class TestExchangeFlowAnalyzer:
    def test_no_flow_in_the_subject_is_insufficient_not_absent(self) -> None:
        """
        No labels loaded means the question was never asked. Reading that as
        "no exchange flow" is a claim about the chain produced by not looking.
        """
        result = ExchangeFlowAnalyzer().analyze({"address": "0xabc"})
        assert result.data["grade"] == Direction.INSUFFICIENT
        assert result.data["determinable"] is False
        assert result.data["is_directional"] is False

    def test_a_thin_window_is_insufficient_not_balanced(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(attributed=MIN_ATTRIBUTED - 1)
        )
        assert result.data["grade"] == Direction.INSUFFICIENT
        assert str(MIN_ATTRIBUTED) in result.data["reason"]

    def test_a_one_sided_window_reads_as_inflow(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=30 * ETH, outflow=1 * ETH)
        )
        assert result.data["grade"] == Direction.NET_INFLOW
        assert result.data["is_directional"] is True

    def test_a_one_sided_window_reads_as_outflow(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=1 * ETH, outflow=30 * ETH)
        )
        assert result.data["grade"] == Direction.NET_OUTFLOW
        assert result.data["is_directional"] is True

    def test_churn_with_a_large_net_is_not_directional(self) -> None:
        """
        The reason the measurement is a ratio. 900 in and 880 out nets +20,
        which is a rounding error on the venue's own traffic -- and an absolute
        threshold on the net would have called it a signal.
        """
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=900 * ETH, outflow=880 * ETH)
        )
        assert result.data["grade"] == Direction.BALANCED
        assert result.data["is_directional"] is False
        assert result.data["imbalance"] < DIRECTIONAL_RATIO

    def test_values_beyond_float_precision_stay_exact(self) -> None:
        """
        2**53 wei is about 0.009 ether, so a float total is wrong for
        essentially every exchange window.
        """
        inflow = 12_345_678_901_234_567_890_123
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=inflow, outflow=1)
        )
        assert result.data["inflow_value"] == str(inflow)
        assert result.data["net_value"] == str(inflow - 1)

    def test_an_unlicensed_zero_is_withheld(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(attributed=0, absence_licensed=False)
        )
        assert result.data["grade"] == Direction.INSUFFICIENT
        assert result.data["determinable"] is False

    def test_a_licensed_zero_is_an_answer(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(attributed=0, absence_licensed=True, absence_floor="1000")
        )
        assert result.data["grade"] == Direction.NO_ATTRIBUTED_FLOW
        assert result.data["determinable"] is True
        assert result.data["is_directional"] is False

    def test_valueless_traffic_has_no_direction_to_measure(self) -> None:
        """Contract calls to a labelled address move nothing to take a side of."""
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=0, outflow=0)
        )
        assert result.data["grade"] == Direction.INSUFFICIENT
        assert "no native value" in result.data["reason"]

    def test_evidence_is_attribution_not_structural(self) -> None:
        """That value moved is structural; that it moved to Binance is a claim."""
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=30 * ETH, outflow=1 * ETH)
        )
        assert result.evidence
        assert all(a.tier == ClaimTier.ATTRIBUTION for a in result.evidence)

    def test_confidence_cannot_exceed_the_label_list(self) -> None:
        """A conclusion is worth no more than the assertion holding it up."""
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=30 * ETH, outflow=1 * ETH, label_confidence=0.5)
        )
        assert all(a.confidence <= 0.5 for a in result.evidence)

    def test_a_balanced_window_emits_no_evidence(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=900 * ETH, outflow=880 * ETH)
        )
        assert result.evidence == []

    def test_concentration_is_measured_against_gross_not_the_rows(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(
                inflow=30 * ETH,
                outflow=1 * ETH,
                entities={
                    "Binance": {"inflow_value": 29 * ETH, "outflow_value": 0},
                    "Kraken": {"inflow_value": 1 * ETH, "outflow_value": 1 * ETH},
                },
            )
        )
        assert result.data["top_entity"] == "Binance"
        assert result.data["concentrated"] is True
        assert result.data["top_entity_share"] <= 1.0

    def test_no_interpretation_appears_in_the_output(self) -> None:
        """
        The detection catalog puts classification strictly after analysis. The
        same deposit is consistent with selling, with collateral and with a
        custody move, and native value cannot separate them.
        """
        result = ExchangeFlowAnalyzer().analyze(
            flow_subject(inflow=30 * ETH, outflow=1 * ETH)
        )
        rendered = (
            result.summary
            + str(result.data)
            + " ".join(a.claim for a in result.evidence)
        ).lower()
        for forbidden in (
            "sell pressure",
            "bullish",
            "bearish",
            "accumulation",
            "distribution",
            "dumping",
            "smart money",
        ):
            assert forbidden not in rendered, forbidden

    def test_malformed_totals_do_not_crash(self) -> None:
        result = ExchangeFlowAnalyzer().analyze(
            {
                "address": "0xabc",
                "exchange_flow": {
                    "attributed": 40,
                    "totals": {"inflow_value": None, "outflow_value": "junk"},
                    "entities": {"Binance": "not a row"},
                },
            }
        )
        assert result.data["determinable"] is False


# =============================================================================
# Pipeline wiring
# =============================================================================


class TestPipelineWiring:
    """The engine previously ran zero stages and returned an empty package."""

    def test_engine_registers_default_stages(self) -> None:
        assert IntelligenceEngine().pipeline.stage_count > 0

    def test_investigation_produces_evidence_and_scores(self) -> None:
        package = IntelligenceEngine().run(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [
                    {
                        "value": 999_999,
                        "direction": "out",
                        "counterparty_type": "exchange",
                    }
                ],
            }
        )
        assert package.evidence_chains
        assert package.scores
        assert package.pipeline.metadata["failure_count"] == 0

    def test_empty_subject_scores_zero_without_failing(self) -> None:
        """Absence of signal is a result, not an error."""
        package = IntelligenceEngine().run({"address": "0xabc"})
        signal = next(s for s in package.scores if s.name == "signal")
        assert signal.value == 0.0
        assert package.pipeline.metadata["failure_count"] == 0

    def test_score_confidence_capped_by_unmeasured_detectors(self) -> None:
        package = IntelligenceEngine().run(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [{"value": 999_999}],
            }
        )
        signal = next(s for s in package.scores if s.name == "signal")
        assert signal.confidence <= 0.60

    def test_findings_reach_the_package(self) -> None:
        package = IntelligenceEngine().run({"address": "0xabc"})
        findings = package.metadata["findings"]
        assert "whale" in findings
        assert "dormant" in findings
        assert "exchange_flow" in findings
        assert "report" in findings
        assert "verification" in findings

    def test_a_directional_window_raises_the_signal(self) -> None:
        package = IntelligenceEngine().run(
            flow_subject(inflow=30 * ETH, outflow=1 * ETH)
        )
        signal = next(s for s in package.scores if s.name == "signal")
        assert signal.value > 0.0
        assert any(c.name == "exchange_flow_direction" for c in signal.components)

    def test_a_balanced_window_does_not_raise_the_signal(self) -> None:
        package = IntelligenceEngine().run(
            flow_subject(inflow=900 * ETH, outflow=880 * ETH)
        )
        signal = next(s for s in package.scores if s.name == "signal")
        assert not any(c.name == "exchange_flow_direction" for c in signal.components)
