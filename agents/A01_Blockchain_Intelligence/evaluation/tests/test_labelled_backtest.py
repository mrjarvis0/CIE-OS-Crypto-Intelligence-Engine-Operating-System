"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the labeled backtest pipeline.

These tests verify that the labeled evaluation data produces promotable
backtest results for each detector. A promotable result means the detector
has earned a measured error rate and may be promoted to VALIDATED maturity,
lifting the 0.60 confidence cap and enabling alerts.

Passing these tests is the prerequisite for editing the maturity registry.
"""

from __future__ import annotations

import pytest

from evaluation import MIN_SAMPLE_SIZE
from evaluation.runner import run_all, run_backtest
from intelligence.schemas.evidence import ErrorRateState

_DETECTORS = ("whale", "dormant", "anomaly", "exchange_flow")


@pytest.fixture(scope="module")
def results():
    return run_all()


# =========================================================================
# Promotion gates
# =========================================================================


@pytest.mark.parametrize("name", _DETECTORS)
def test_sample_size_is_credible(results, name):
    assert results[name].sample_size >= MIN_SAMPLE_SIZE


@pytest.mark.parametrize("name", _DETECTORS)
def test_backtest_is_promotable(results, name):
    r = results[name]
    assert r.promotable, f"{name} not promotable: {r.blockers()}"


@pytest.mark.parametrize("name", _DETECTORS)
def test_false_positive_rate_is_defined(results, name):
    """Without negatives there is no FPR, and without FPR no promotion."""
    assert results[name].metrics.false_positive_rate is not None


@pytest.mark.parametrize("name", _DETECTORS)
def test_no_systematic_overconfidence(results, name):
    assert results[name].calibration.overconfident is False


@pytest.mark.parametrize("name", _DETECTORS)
def test_promotable_result_yields_measured_error_rate(results, name):
    rate = results[name].to_error_rate()
    assert rate.state is ErrorRateState.MEASURED
    assert rate.is_known is True
    assert rate.sample_size >= MIN_SAMPLE_SIZE


# =========================================================================
# Detector quality on labeled data
# =========================================================================


@pytest.mark.parametrize("name", _DETECTORS)
def test_perfect_recall(results, name):
    """Every labeled positive must be detected."""
    assert results[name].metrics.recall == pytest.approx(1.0)


@pytest.mark.parametrize("name", _DETECTORS)
def test_zero_false_positive_rate(results, name):
    """No labeled negative should fire."""
    assert results[name].metrics.false_positive_rate == pytest.approx(0.0)


@pytest.mark.parametrize("name", _DETECTORS)
def test_no_detector_errors(results, name):
    assert results[name].errors == ()


# =========================================================================
# Individual detector sanity
# =========================================================================


def test_whale_backtest_standalone():
    r = run_backtest("whale")
    assert r.sample_size == 140
    assert r.promotable


def test_dormant_backtest_standalone():
    r = run_backtest("dormant")
    assert r.sample_size == 125
    assert r.promotable


def test_anomaly_backtest_standalone():
    r = run_backtest("anomaly")
    assert r.sample_size == 135
    assert r.promotable


def test_exchange_flow_backtest_standalone():
    r = run_backtest("exchange_flow")
    assert r.sample_size == 135
    assert r.promotable


def test_unknown_detector_raises():
    with pytest.raises(ValueError, match="unknown detector"):
        run_backtest("nonexistent")
