"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the detector promotion pipeline.
"""

from __future__ import annotations

import pytest

from decision.maturity import (
    REGISTRY,
    DetectorMaturity,
    Maturity,
    MaturityGate,
)
from evaluation.promotion import (
    PromotionReport,
    PromotionVerdict,
    build_promoted_registry,
    evaluate_all,
    evaluate_detector,
)
from intelligence.schemas.evidence import ErrorRateState


# ==============================================================================
# SINGLE DETECTOR EVALUATION
# ==============================================================================


def test_evaluate_whale_returns_promotable_verdict():
    verdict = evaluate_detector("whale")

    assert verdict.promotable is True
    assert verdict.detector == "DET-WHALE-01"
    assert verdict.analyzer == "whale"
    assert verdict.error_rate.state == ErrorRateState.MEASURED
    assert verdict.error_rate.value == 0.0
    assert verdict.blockers == ()


def test_evaluate_dormant_returns_promotable_verdict():
    verdict = evaluate_detector("dormant")

    assert verdict.promotable is True
    assert verdict.detector == "DET-DORMANT-01"


def test_evaluate_anomaly_returns_promotable_verdict():
    verdict = evaluate_detector("anomaly")

    assert verdict.promotable is True
    assert verdict.detector == "DET-ANOMALY-01"


def test_evaluate_exchange_flow_returns_promotable_verdict():
    verdict = evaluate_detector("exchange_flow")

    assert verdict.promotable is True
    assert verdict.detector == "DET-EXCHANGE-01"


def test_evaluate_unknown_detector_raises():
    with pytest.raises(ValueError, match="unknown detector"):
        evaluate_detector("nonexistent")


# ==============================================================================
# FULL EVALUATION
# ==============================================================================


def test_evaluate_all_produces_four_verdicts():
    report = evaluate_all()

    assert isinstance(report, PromotionReport)
    assert len(report.verdicts) == 4
    assert report.all_promoted is True
    assert report.promoted_count == 4
    assert report.blocked_count == 0


def test_evaluate_all_builds_promoted_registry():
    """
    Backtested detectors are promoted; un-backtested ones are left alone.

    The second half is the part worth testing. ``run_all`` only covers
    detectors with labelled cases, so a detector that has none never appears
    in a verdict -- and a builder that defaulted to "promote what I was not
    told about" would grant full confidence and alerting rights to exactly
    the detector nobody has measured.
    """
    report = evaluate_all()

    # Every registry entry survives the rebuild; none is dropped.
    assert {entry.detector for entry in report.promoted_registry} == {
        entry.detector for entry in REGISTRY
    }

    backtested = {verdict.detector for verdict in report.verdicts}
    for entry in report.promoted_registry:
        if entry.detector in backtested:
            assert entry.maturity == Maturity.VALIDATED
            assert entry.may_alert is True
        else:
            assert entry.maturity < Maturity.VALIDATED
            assert entry.may_alert is False
            assert entry.blocked_by, f"{entry.detector} is held back without a reason"


# ==============================================================================
# REGISTRY BUILDER
# ==============================================================================


def test_build_promoted_registry_upgrades_promotable():
    from evaluation.backtest import BacktestResult
    from evaluation.metrics import CalibrationReport, ClassificationMetrics, ConfusionMatrix
    from intelligence.schemas.evidence import ErrorRate

    matrix = ConfusionMatrix(true_positive=70, false_positive=0, true_negative=70, false_negative=0)
    metrics = ClassificationMetrics(matrix=matrix, base_rate=0.001)
    cal = CalibrationReport(sample_size=140)

    result = BacktestResult(
        detector="DET-WHALE-01",
        metrics=metrics,
        calibration=cal,
        sample_size=140,
    )
    verdict = PromotionVerdict(
        detector="DET-WHALE-01",
        analyzer="whale",
        promotable=True,
        backtest=result,
        error_rate=result.to_error_rate(),
    )

    base = (
        DetectorMaturity(
            detector="DET-WHALE-01",
            analyzer="whale",
            maturity=Maturity.IMPLEMENTED,
            blocked_by="test",
        ),
    )

    promoted = build_promoted_registry((verdict,), base=base)

    assert len(promoted) == 1
    assert promoted[0].maturity == Maturity.VALIDATED
    assert promoted[0].may_alert is True


def test_build_promoted_registry_keeps_blocked_at_implemented():
    from evaluation.backtest import BacktestResult
    from evaluation.metrics import CalibrationReport, ClassificationMetrics, ConfusionMatrix
    from intelligence.schemas.evidence import ErrorRate

    matrix = ConfusionMatrix(true_positive=5, false_positive=3, true_negative=2, false_negative=0)
    metrics = ClassificationMetrics(matrix=matrix)
    cal = CalibrationReport(sample_size=10, overconfident=True)

    result = BacktestResult(
        detector="DET-X-01",
        metrics=metrics,
        calibration=cal,
        sample_size=10,
    )
    verdict = PromotionVerdict(
        detector="DET-X-01",
        analyzer="x",
        promotable=False,
        backtest=result,
        error_rate=result.to_error_rate(),
        blockers=("sample size 10 below minimum 100",),
    )

    base = (
        DetectorMaturity(
            detector="DET-X-01",
            analyzer="x",
            maturity=Maturity.IMPLEMENTED,
            blocked_by="original",
        ),
    )

    kept = build_promoted_registry((verdict,), base=base)

    assert len(kept) == 1
    assert kept[0].maturity == Maturity.IMPLEMENTED
    assert "sample size" in kept[0].blocked_by


# ==============================================================================
# REGISTRY STATE
# ==============================================================================


def test_every_validated_detector_was_actually_backtested():
    """
    Promotion is earned, not declared.

    This used to assert that every entry in REGISTRY was VALIDATED, which was
    true on the day it was written and stopped being an invariant the moment a
    fifth detector was built. The durable property is the one below: a
    detector may sit at VALIDATED only if a backtest put it there.
    """
    backtested = {verdict.detector for verdict in evaluate_all().verdicts}

    for entry in REGISTRY:
        if entry.maturity == Maturity.VALIDATED:
            assert entry.detector in backtested, (
                f"{entry.detector} is validated but no backtest covers it"
            )
            assert entry.may_alert is True


def test_every_unpromoted_detector_names_what_blocks_it():
    """
    A detector held back without a stated reason reads as an oversight, and
    the next reader cannot tell whether promoting it is safe.
    """
    for entry in REGISTRY:
        if entry.maturity < Maturity.VALIDATED:
            assert entry.blocked_by
            assert entry.may_alert is False
            assert entry.ceiling <= 0.60


def test_the_alerting_set_is_exactly_the_validated_set():
    gate = MaturityGate()
    alerting = {entry.detector for entry in gate.alerting_detectors()}
    validated = {e.detector for e in REGISTRY if e.maturity == Maturity.VALIDATED}

    assert alerting == validated


def test_verdict_serialization():
    verdict = evaluate_detector("whale")
    d = verdict.as_dict()

    assert d["promotable"] is True
    assert d["analyzer"] == "whale"
    assert d["sample_size"] >= 100
    assert d["error_rate"]["state"] == "measured"
