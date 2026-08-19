"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    evaluation.runner

Purpose:
    Run backtests for all detectors against their labeled evaluation windows
    and report whether each is promotable.

    A promotable result means the detector has earned a measured error rate
    and may be upgraded from IMPLEMENTED to VALIDATED in the maturity
    registry, lifting its confidence ceiling from 0.60 to 1.0 and
    permitting it to raise alerts.

Usage:
    from evaluation.runner import run_all

    results = run_all()
    for name, result in results.items():
        print(f"{name}: promotable={result.promotable}")
        if not result.promotable:
            print(f"  blockers: {result.blockers()}")
"""

from __future__ import annotations

from typing import Any

from intelligence.analysis.anomaly import AnomalyAnalyzer
from intelligence.analysis.dormant import DormantAnalyzer
from intelligence.analysis.exchange import ExchangeFlowAnalyzer
from intelligence.analysis.whale import WhaleAnalyzer

from .backtest import Backtest, BacktestResult, VerdictReader
from .labelled import DETECTOR_CASES

_ANALYZERS: dict[str, Any] = {
    "whale": WhaleAnalyzer,
    "dormant": DormantAnalyzer,
    "anomaly": AnomalyAnalyzer,
    "exchange_flow": ExchangeFlowAnalyzer,
}

_VERDICTS: dict[str, VerdictReader] = {
    "whale": lambda r: (r.data["is_whale"], r.confidence),
    "dormant": lambda r: (r.data["reactivated"], r.confidence),
    "anomaly": lambda r: (r.data["is_anomalous"], r.confidence),
    "exchange_flow": lambda r: (r.data["is_directional"], r.confidence),
}

_BASE_RATES: dict[str, float] = {
    "whale": 0.001,
    "dormant": 0.0001,
    "anomaly": 0.01,
    "exchange_flow": 0.1,
}


def run_backtest(name: str) -> BacktestResult:
    """Run the backtest for one named detector."""
    if name not in _ANALYZERS:
        raise ValueError(
            f"unknown detector {name!r}; "
            f"known: {', '.join(sorted(_ANALYZERS))}"
        )

    detector = _ANALYZERS[name]()
    verdict = _VERDICTS[name]
    cases = DETECTOR_CASES[name]()

    return Backtest(
        detector, verdict, base_rate=_BASE_RATES.get(name),
    ).run(cases)


def run_all() -> dict[str, BacktestResult]:
    """Run backtests for every detector and return a name-to-result map."""
    return {name: run_backtest(name) for name in _ANALYZERS}


__all__ = ["run_all", "run_backtest"]
