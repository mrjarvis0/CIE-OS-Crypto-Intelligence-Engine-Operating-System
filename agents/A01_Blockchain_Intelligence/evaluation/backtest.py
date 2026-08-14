"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    evaluation.backtest

Purpose:
    Run a detector against a labelled historical window and produce the
    measured error rate that promotes it out of the confidence cap.

The promotion loop
------------------
Every detector starts with an unmeasured error rate, which caps its output at
0.60 confidence however reliable its source category looks. That cap is not a
limitation to work around -- it is the honest position for a method that has
never been checked.

This module closes the loop:

    detector -> labelled window -> measured error rate -> higher ceiling

A detector reaches ``validated`` maturity only after this runs, and the
:class:`~intelligence.schemas.evidence.ErrorRate` it returns is what the
detector then attaches to its evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from intelligence.schemas.evidence import ErrorRate, ErrorRateState

from .metrics import (
    CalibrationReport,
    ClassificationMetrics,
    calibration,
    confusion_matrix,
)

#: Below this many labelled samples a measured rate is not credible, and the
#: detector stays capped. Publishing a rate from a handful of cases is worse
#: than declaring the rate unmeasured, because it claims rigour it lacks.
MIN_SAMPLE_SIZE = 100

#: A detector whose stated confidence drifts more than this from observed
#: correctness is miscalibrated and must not be promoted.
MAX_CALIBRATION_ERROR = 0.10


@dataclass(frozen=True, slots=True)
class LabelledCase:
    """
    One labelled evaluation case.

    ``subject`` is fed to the detector exactly as a live subject would be, so
    a backtest exercises the same code path as production.
    """

    subject: dict[str, Any]
    label: bool
    case_id: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Outcome of evaluating one detector against one labelled window."""

    detector: str
    metrics: ClassificationMetrics
    calibration: CalibrationReport
    sample_size: int
    ran_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    errors: tuple[str, ...] = ()

    @property
    def promotable(self) -> bool:
        """
        Whether this run justifies promoting the detector to ``validated``.

        Three independent gates, all of which must hold: a credible sample, a
        computable false-positive rate, and no systematic overconfidence.

        Only *over*-confidence blocks promotion. Underconfidence is the safe
        direction -- and it is also unavoidable here, because an unpromoted
        detector is capped at 0.60 by definition. Gating on absolute
        calibration error would therefore be a catch-22: the cap makes the
        detector look miscalibrated, and the miscalibration blocks the
        promotion that would lift the cap.
        """
        if self.sample_size < MIN_SAMPLE_SIZE:
            return False
        if self.metrics.false_positive_rate is None:
            return False
        if self.calibration.overconfident:
            return False
        return True

    def blockers(self) -> list[str]:
        """
        Why promotion is refused, in reviewable form.

        A bare False tells an operator nothing actionable.
        """
        reasons: list[str] = []
        if self.sample_size < MIN_SAMPLE_SIZE:
            reasons.append(
                f"sample size {self.sample_size} below minimum {MIN_SAMPLE_SIZE}"
            )
        if self.metrics.false_positive_rate is None:
            reasons.append(
                "false-positive rate undefined (no negative cases in window)"
            )
        if self.calibration.overconfident:
            reasons.append(
                "detector is systematically overconfident "
                f"(calibration error {self.calibration.expected_calibration_error:.3f})"
            )
        return reasons

    @property
    def underconfident(self) -> bool:
        """
        True when the detector is materially more reliable than it claims.

        Not a blocker, but worth surfacing: it usually means the confidence
        cap is now the binding constraint rather than the evidence, and the
        detector's stated confidence can be raised once promoted.
        """
        return (
            not self.calibration.overconfident
            and self.calibration.expected_calibration_error > MAX_CALIBRATION_ERROR
        )

    def to_error_rate(self) -> ErrorRate:
        """
        The :class:`ErrorRate` this detector may now attach to its evidence.

        Returns an unmeasured rate when the run is not promotable, so a failed
        backtest cannot accidentally lift the confidence cap.
        """
        if not self.promotable:
            return ErrorRate()

        return ErrorRate(
            state=ErrorRateState.MEASURED,
            value=self.metrics.false_positive_rate,
            sample_size=self.sample_size,
            measured_at=self.ran_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "sample_size": self.sample_size,
            "ran_at": self.ran_at.isoformat(),
            "metrics": self.metrics.to_dict(),
            "calibration": self.calibration.to_dict(),
            "promotable": self.promotable,
            "blockers": self.blockers(),
            "errors": list(self.errors),
        }


#: Extracts (fired, confidence) from a detector result. Detectors expose
#: their verdict under different keys, so the caller supplies the reader.
VerdictReader = Callable[[Any], tuple[bool, float]]


class Backtest:
    """
    Runs a detector over labelled cases and measures how well it did.

    The detector is invoked through its normal ``analyze`` entry point, so a
    backtest cannot pass where production would fail.
    """

    def __init__(
        self,
        detector: Any,
        verdict: VerdictReader,
        *,
        base_rate: float | None = None,
    ) -> None:
        self._detector = detector
        self._verdict = verdict
        self._base_rate = base_rate

    def run(self, cases: list[LabelledCase]) -> BacktestResult:
        """
        Evaluate every case and summarise.

        A case that raises is recorded as a non-detection and an error rather
        than aborting the run: a detector that crashes on some inputs has a
        real defect, and hiding it behind an exception would conceal that.
        """
        name = getattr(self._detector, "name", type(self._detector).__name__)

        predictions: list[bool] = []
        labels: list[bool] = []
        confidences: list[float] = []
        outcomes: list[bool] = []
        errors: list[str] = []

        for index, case in enumerate(cases):
            identifier = case.case_id or f"case[{index}]"
            try:
                result = self._detector.analyze(case.subject)
                fired, confidence = self._verdict(result)
            except Exception as exc:  # noqa: BLE001 - detector boundary
                errors.append(f"{identifier}: {type(exc).__name__}: {exc}")
                fired, confidence = False, 0.0

            predictions.append(fired)
            labels.append(case.label)
            # Calibration compares the detector's stated probability that the
            # subject is positive against whether it actually was. Comparing
            # against "was the prediction correct" instead would score a
            # confident correct negative as badly miscalibrated, because a
            # non-firing detector states a low probability by design.
            confidences.append(max(0.0, min(1.0, confidence)))
            outcomes.append(case.label)

        matrix = confusion_matrix(predictions, labels)

        return BacktestResult(
            detector=name,
            metrics=ClassificationMetrics(matrix=matrix, base_rate=self._base_rate),
            calibration=calibration(confidences, outcomes),
            sample_size=len(cases),
            errors=tuple(errors),
        )
