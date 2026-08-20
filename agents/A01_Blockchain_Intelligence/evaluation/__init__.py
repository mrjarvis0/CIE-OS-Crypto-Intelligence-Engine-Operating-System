"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    evaluation

Purpose:
    Backtesting and calibration for A01's detectors.

Why this package is load-bearing
--------------------------------
Every detector begins with an unmeasured error rate, which caps its output at
0.60 confidence. Nothing in A01 can reach ``validated`` maturity, and no
conclusion can carry full confidence, until a detector has been measured
against a labelled window.

While this package was empty that promotion path did not exist, so the cap was
permanent and the maturity level unreachable in principle. This is the module
that closes the loop.

Modules
-------
metrics    Confusion matrix, precision/recall, base-rate posterior, calibration.
backtest   Run a detector over labelled cases and produce a measured ErrorRate.

Usage
-----
    from evaluation import Backtest, LabelledCase
    from intelligence.analysis.whale import WhaleAnalyzer

    backtest = Backtest(
        WhaleAnalyzer(),
        verdict=lambda r: (r.data["is_whale"], r.confidence),
        base_rate=0.001,
    )
    result = backtest.run(cases)
    if result.promotable:
        error_rate = result.to_error_rate()
"""

from __future__ import annotations

from .backtest import (
    MAX_CALIBRATION_ERROR,
    MIN_SAMPLE_SIZE,
    Backtest,
    BacktestResult,
    LabelledCase,
)
from .metrics import (
    CalibrationBin,
    CalibrationReport,
    ClassificationMetrics,
    ConfusionMatrix,
    calibration,
    confusion_matrix,
)
from .labelled import (
    DETECTOR_CASES,
    anomaly_cases,
    dormant_cases,
    exchange_flow_cases,
    whale_cases,
)
from .runner import run_all, run_backtest
from .promotion import (
    PromotionReport,
    PromotionVerdict,
    build_promoted_registry,
    evaluate_all,
    evaluate_detector,
)

__all__ = [
    "Backtest",
    "BacktestResult",
    "DETECTOR_CASES",
    "LabelledCase",
    "MAX_CALIBRATION_ERROR",
    "MIN_SAMPLE_SIZE",
    "CalibrationBin",
    "CalibrationReport",
    "ClassificationMetrics",
    "ConfusionMatrix",
    "PromotionReport",
    "PromotionVerdict",
    "anomaly_cases",
    "build_promoted_registry",
    "calibration",
    "confusion_matrix",
    "dormant_cases",
    "evaluate_all",
    "evaluate_detector",
    "exchange_flow_cases",
    "run_all",
    "run_backtest",
    "whale_cases",
]
