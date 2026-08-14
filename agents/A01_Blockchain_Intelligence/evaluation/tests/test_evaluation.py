"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the evaluation harness.

The promotion gates matter most here: a detector that is promoted on a thin
or miscalibrated sample gets its confidence cap lifted, and every conclusion
it produces afterwards inherits unearned authority.
"""

from __future__ import annotations

import pytest

from evaluation import (
    MIN_SAMPLE_SIZE,
    Backtest,
    ClassificationMetrics,
    LabelledCase,
    calibration,
    confusion_matrix,
)
from intelligence.analysis.whale import WhaleAnalyzer
from intelligence.schemas.evidence import ErrorRateState

POPULATION = [1, 5, 12, 40, 110, 480, 1200, 5400, 21000]


def whale_verdict(result):
    return result.data["is_whale"], result.confidence


# =============================================================================
# Metrics
# =============================================================================


class TestConfusionMatrix:
    def test_counts_all_four_outcomes(self) -> None:
        matrix = confusion_matrix(
            predictions=[True, True, False, False],
            labels=[True, False, True, False],
        )
        assert matrix.true_positive == 1
        assert matrix.false_positive == 1
        assert matrix.false_negative == 1
        assert matrix.true_negative == 1

    def test_mismatched_lengths_rejected(self) -> None:
        """Zipping mismatched sequences would silently truncate the run."""
        with pytest.raises(ValueError, match="same length"):
            confusion_matrix([True], [True, False])


class TestClassificationMetrics:
    def test_precision_and_recall(self) -> None:
        metrics = ClassificationMetrics(
            confusion_matrix([True] * 8 + [False] * 2, [True] * 9 + [False])
        )
        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(8 / 9)

    def test_undefined_precision_is_none_not_zero(self) -> None:
        """Never fired and always wrong are different findings."""
        metrics = ClassificationMetrics(
            confusion_matrix([False, False], [True, False])
        )
        assert metrics.precision is None

    def test_posterior_collapses_under_a_low_base_rate(self) -> None:
        """A 99%-accurate detector on a rare class is mostly false positives."""
        matrix = confusion_matrix(
            predictions=[True] * 99 + [False] + [True] * 1 + [False] * 99,
            labels=[True] * 100 + [False] * 100,
        )
        metrics = ClassificationMetrics(matrix=matrix, base_rate=0.0001)
        assert metrics.precision > 0.9
        # Same detector, realistic prior: the flag means almost nothing.
        assert metrics.posterior < 0.02

    def test_posterior_requires_a_base_rate(self) -> None:
        metrics = ClassificationMetrics(confusion_matrix([True], [True]))
        assert metrics.posterior is None


class TestCalibration:
    def test_perfectly_calibrated_scores_near_zero_error(self) -> None:
        # 80 correct out of 100, all stated at 0.8.
        confidences = [0.8] * 100
        outcomes = [True] * 80 + [False] * 20
        report = calibration(confidences, outcomes)
        assert report.expected_calibration_error == pytest.approx(0.0, abs=1e-9)
        assert report.overconfident is False

    def test_overconfidence_detected(self) -> None:
        # Claims 0.95, right only half the time.
        report = calibration([0.95] * 100, [True] * 50 + [False] * 50)
        assert report.expected_calibration_error > 0.4
        assert report.overconfident is True

    def test_underconfidence_is_not_flagged_as_overconfident(self) -> None:
        report = calibration([0.3] * 100, [True] * 90 + [False] * 10)
        assert report.overconfident is False

    def test_confidence_of_one_lands_in_final_bin(self) -> None:
        report = calibration([1.0] * 10, [True] * 10)
        assert report.bins[-1].count == 10

    def test_empty_input_returns_empty_report(self) -> None:
        assert calibration([], []).sample_size == 0


# =============================================================================
# Backtest and promotion
# =============================================================================


def _cases(count: int, whale: bool) -> list[LabelledCase]:
    """Build labelled cases that a correct detector classifies correctly."""
    value = 999_999 if whale else 2
    return [
        LabelledCase(
            subject={
                "address": f"0x{index:040x}",
                "transfer_population": POPULATION,
                "large_transfers": [{"value": value}],
            },
            label=whale,
            case_id=f"{'pos' if whale else 'neg'}-{index}",
        )
        for index in range(count)
    ]


class TestBacktest:
    def test_detects_correctly_on_a_clean_window(self) -> None:
        result = Backtest(WhaleAnalyzer(), whale_verdict).run(
            _cases(60, True) + _cases(60, False)
        )
        assert result.metrics.recall == pytest.approx(1.0)
        assert result.metrics.false_positive_rate == pytest.approx(0.0)

    def test_promotion_requires_a_credible_sample(self) -> None:
        result = Backtest(WhaleAnalyzer(), whale_verdict).run(
            _cases(5, True) + _cases(5, False)
        )
        assert result.promotable is False
        assert any("sample size" in b for b in result.blockers())

    def test_promotion_requires_negative_cases(self) -> None:
        """Without negatives there is no false-positive rate to publish."""
        result = Backtest(WhaleAnalyzer(), whale_verdict).run(_cases(150, True))
        assert result.promotable is False
        assert any("false-positive rate undefined" in b for b in result.blockers())

    def test_promotable_run_yields_a_measured_error_rate(self) -> None:
        result = Backtest(WhaleAnalyzer(), whale_verdict).run(
            _cases(60, True) + _cases(60, False)
        )
        assert result.promotable is True

        rate = result.to_error_rate()
        assert rate.state is ErrorRateState.MEASURED
        assert rate.is_known is True
        assert rate.sample_size >= MIN_SAMPLE_SIZE

    def test_failed_run_cannot_lift_the_confidence_cap(self) -> None:
        """A failed backtest must not accidentally promote a detector."""
        result = Backtest(WhaleAnalyzer(), whale_verdict).run(_cases(4, True))
        rate = result.to_error_rate()
        assert rate.state is ErrorRateState.UNMEASURED
        assert rate.is_known is False

    def test_underconfidence_does_not_block_promotion(self) -> None:
        """The 0.60 cap makes every unpromoted detector underconfident."""
        result = Backtest(WhaleAnalyzer(), whale_verdict).run(
            _cases(60, True) + _cases(60, False)
        )
        assert result.calibration.overconfident is False
        assert result.underconfident is True
        assert result.promotable is True

    def test_detector_exception_recorded_not_raised(self) -> None:
        class Broken:
            name = "broken"

            def analyze(self, subject):  # noqa: ANN001, ANN202
                raise RuntimeError("boom")

        result = Backtest(Broken(), whale_verdict).run(_cases(3, True))
        assert len(result.errors) == 3
        assert "boom" in result.errors[0]
        assert result.promotable is False

    def test_measured_rate_lifts_the_evidence_ceiling(self) -> None:
        """End to end: backtest promotes, evidence confidence rises."""
        from intelligence.evidence.builder import EvidenceBuilder
        from intelligence.schemas.evidence import ClaimTier

        builder = EvidenceBuilder()

        capped = builder.build(
            claim="co-spend",
            source_type="on_chain",
            data={"x": 1},
            confidence=0.95,
            tier=ClaimTier.STRUCTURAL,
        )
        assert capped.confidence == 0.60

        result = Backtest(WhaleAnalyzer(), whale_verdict).run(
            _cases(60, True) + _cases(60, False)
        )
        promoted = builder.build(
            claim="co-spend",
            source_type="on_chain",
            data={"x": 1},
            confidence=0.95,
            tier=ClaimTier.STRUCTURAL,
            error_rate=result.to_error_rate(),
        )
        assert promoted.confidence == 0.95
