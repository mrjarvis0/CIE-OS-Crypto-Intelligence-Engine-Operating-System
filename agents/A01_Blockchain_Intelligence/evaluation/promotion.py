"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    evaluation.promotion

Purpose:
    Close the promotion loop: run backtests, check gates, and produce the
    registry update that lifts a detector from IMPLEMENTED to VALIDATED.

    This is the module that turns a measured error rate into a maturity
    change. Without it, ``evaluation/`` can *measure* but cannot *apply*,
    and the confidence cap stays permanent.

    The promotion is data, not code: a new REGISTRY tuple replaces the
    old one. The module never bypasses the gates --- a detector that
    fails its backtest stays at IMPLEMENTED, and the report says why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from decision.maturity import (
    REGISTRY,
    DetectorMaturity,
    Maturity,
    MaturityGate,
)
from intelligence.schemas.evidence import ErrorRate

from .backtest import BacktestResult
from .runner import run_all, run_backtest


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    """Whether one detector earned promotion, and the evidence."""

    detector: str
    analyzer: str
    promotable: bool
    backtest: BacktestResult
    error_rate: ErrorRate
    blockers: tuple[str, ...] = ()
    previous_maturity: str = "implemented"

    def as_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "analyzer": self.analyzer,
            "promotable": self.promotable,
            "previous_maturity": self.previous_maturity,
            "blockers": list(self.blockers),
            "sample_size": self.backtest.sample_size,
            "precision": self.backtest.metrics.precision,
            "recall": self.backtest.metrics.recall,
            "false_positive_rate": self.backtest.metrics.false_positive_rate,
            "calibration_error": self.backtest.calibration.expected_calibration_error,
            "overconfident": self.backtest.calibration.overconfident,
            "error_rate": self.error_rate.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PromotionReport:
    """Outcome of evaluating every detector for promotion."""

    verdicts: tuple[PromotionVerdict, ...]
    promoted_registry: tuple[DetectorMaturity, ...]
    ran_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def promoted_count(self) -> int:
        return sum(1 for v in self.verdicts if v.promotable)

    @property
    def blocked_count(self) -> int:
        return sum(1 for v in self.verdicts if not v.promotable)

    @property
    def all_promoted(self) -> bool:
        return all(v.promotable for v in self.verdicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ran_at": self.ran_at.isoformat(),
            "promoted": self.promoted_count,
            "blocked": self.blocked_count,
            "all_promoted": self.all_promoted,
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


def evaluate_detector(name: str) -> PromotionVerdict:
    """Run the backtest for one detector and return a promotion verdict."""
    gate = MaturityGate()
    standing = None
    for entry in gate:
        if entry.analyzer == name:
            standing = entry
            break

    detector_id = standing.detector if standing else f"DET-{name.upper()}-01"
    previous = standing.maturity.label if standing else "unknown"

    result = run_backtest(name)
    error_rate = result.to_error_rate()

    return PromotionVerdict(
        detector=detector_id,
        analyzer=name,
        promotable=result.promotable,
        backtest=result,
        error_rate=error_rate,
        blockers=tuple(result.blockers()),
        previous_maturity=previous,
    )


def evaluate_all() -> PromotionReport:
    """Run backtests for every detector and produce a promotion report."""
    results = run_all()

    verdicts: list[PromotionVerdict] = []
    gate = MaturityGate()

    for name, result in results.items():
        standing = None
        for entry in gate:
            if entry.analyzer == name:
                standing = entry
                break

        detector_id = standing.detector if standing else f"DET-{name.upper()}-01"
        previous = standing.maturity.label if standing else "unknown"

        verdicts.append(PromotionVerdict(
            detector=detector_id,
            analyzer=name,
            promotable=result.promotable,
            backtest=result,
            error_rate=result.to_error_rate(),
            blockers=tuple(result.blockers()),
            previous_maturity=previous,
        ))

    promoted_registry = build_promoted_registry(tuple(verdicts))

    return PromotionReport(
        verdicts=tuple(verdicts),
        promoted_registry=promoted_registry,
    )


def build_promoted_registry(
    verdicts: tuple[PromotionVerdict, ...],
    *,
    base: tuple[DetectorMaturity, ...] | None = None,
) -> tuple[DetectorMaturity, ...]:
    """
    Build a new REGISTRY tuple with promoted detectors.

    Detectors that passed all gates are upgraded to VALIDATED. Those that
    did not keep their current standing and blocked_by is updated with the
    backtest result.
    """
    source = base if base is not None else REGISTRY
    verdict_by_analyzer = {v.analyzer: v for v in verdicts}

    entries: list[DetectorMaturity] = []
    for entry in source:
        verdict = verdict_by_analyzer.get(entry.analyzer)
        if verdict and verdict.promotable:
            entries.append(DetectorMaturity(
                detector=entry.detector,
                analyzer=entry.analyzer,
                maturity=Maturity.VALIDATED,
            ))
        elif verdict and not verdict.promotable:
            entries.append(DetectorMaturity(
                detector=entry.detector,
                analyzer=entry.analyzer,
                maturity=entry.maturity,
                blocked_by="; ".join(verdict.blockers),
            ))
        else:
            entries.append(entry)

    return tuple(entries)


__all__ = [
    "PromotionReport",
    "PromotionVerdict",
    "build_promoted_registry",
    "evaluate_all",
    "evaluate_detector",
]
