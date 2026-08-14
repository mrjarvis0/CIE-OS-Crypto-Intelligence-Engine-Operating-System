"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    evaluation.metrics

Purpose:
    Classification and calibration metrics for detector evaluation.

Why base rates dominate
-----------------------
The most common analytical error in this field is reading a detector's
accuracy as the probability that a flagged subject is genuinely interesting.
If 0.01% of addresses are exploiters, a 99%-accurate detector that fires
yields a posterior of roughly 1% -- not 99%.

:class:`ClassificationMetrics` therefore reports precision alongside the
posterior implied by a supplied base rate, so a detector cannot be promoted
on an accuracy figure that means nothing in deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    """Raw outcome counts from a labelled evaluation run."""

    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def total(self) -> int:
        return (
            self.true_positive
            + self.false_positive
            + self.true_negative
            + self.false_negative
        )

    @property
    def positives(self) -> int:
        """Actual positives in the labelled set."""
        return self.true_positive + self.false_negative

    @property
    def negatives(self) -> int:
        """Actual negatives in the labelled set."""
        return self.true_negative + self.false_positive

    def to_dict(self) -> dict[str, int]:
        return {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "total": self.total,
        }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """
    Ratio, or None when undefined.

    None rather than 0.0 deliberately: a precision of zero and an undefined
    precision (nothing was flagged) are different findings, and collapsing
    them hides that the detector never fired.
    """
    if denominator <= 0:
        return None
    return numerator / denominator


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    """
    Precision, recall, and the deployment-relevant posterior.

    ``false_positive_rate`` is the figure a detector publishes as its
    documented error rate, per the Daubert known-error-rate criterion.
    """

    matrix: ConfusionMatrix
    base_rate: float | None = None

    @property
    def precision(self) -> float | None:
        """Of everything flagged, the share that was genuinely positive."""
        return _safe_ratio(
            self.matrix.true_positive,
            self.matrix.true_positive + self.matrix.false_positive,
        )

    @property
    def recall(self) -> float | None:
        """Of everything genuinely positive, the share that was flagged."""
        return _safe_ratio(self.matrix.true_positive, self.matrix.positives)

    @property
    def false_positive_rate(self) -> float | None:
        """Of everything genuinely negative, the share wrongly flagged."""
        return _safe_ratio(self.matrix.false_positive, self.matrix.negatives)

    @property
    def specificity(self) -> float | None:
        return _safe_ratio(self.matrix.true_negative, self.matrix.negatives)

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or (precision + recall) == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    @property
    def posterior(self) -> float | None:
        """
        P(positive | flagged) at the supplied deployment base rate.

        The evaluation set is usually balanced far more favourably than
        reality. This re-weights precision by the prior the detector will
        actually face, and it is normally a much smaller number.
        """
        if self.base_rate is None:
            return None

        recall = self.recall
        fpr = self.false_positive_rate
        if recall is None or fpr is None:
            return None

        prior = max(0.0, min(1.0, self.base_rate))
        true_flag = recall * prior
        false_flag = fpr * (1.0 - prior)
        denominator = true_flag + false_flag
        if denominator <= 0:
            return None
        return true_flag / denominator

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix": self.matrix.to_dict(),
            "precision": self.precision,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "specificity": self.specificity,
            "f1": self.f1,
            "base_rate": self.base_rate,
            "posterior": self.posterior,
        }


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    """One bucket of a reliability diagram."""

    lower: float
    upper: float
    count: int = 0
    predicted_mean: float = 0.0
    observed_rate: float = 0.0

    @property
    def gap(self) -> float:
        """Signed calibration error: positive means overconfident."""
        return self.predicted_mean - self.observed_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "range": [self.lower, self.upper],
            "count": self.count,
            "predicted_mean": round(self.predicted_mean, 6),
            "observed_rate": round(self.observed_rate, 6),
            "gap": round(self.gap, 6),
        }


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """
    How well stated confidence matches observed correctness.

    A01's confidence values are calibrated probability estimates: a claim at
    0.80 should be correct about 80% of the time. A class whose 0.9-confidence
    claims are right 60% of the time is miscalibrated, and the fix is to
    correct the confidence function -- not to move the threshold.
    """

    bins: tuple[CalibrationBin, ...] = ()
    expected_calibration_error: float = 0.0
    max_calibration_error: float = 0.0
    sample_size: int = 0
    overconfident: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "bins": [b.to_dict() for b in self.bins],
            "expected_calibration_error": round(
                self.expected_calibration_error, 6
            ),
            "max_calibration_error": round(self.max_calibration_error, 6),
            "sample_size": self.sample_size,
            "overconfident": self.overconfident,
        }


def confusion_matrix(
    predictions: list[bool],
    labels: list[bool],
) -> ConfusionMatrix:
    """
    Build a confusion matrix from aligned prediction and label sequences.

    Raises
    ------
    ValueError
        If the sequences differ in length. Silently zipping mismatched
        sequences would truncate the evaluation and overstate performance.
    """
    if len(predictions) != len(labels):
        raise ValueError(
            f"predictions ({len(predictions)}) and labels ({len(labels)}) "
            "must be the same length"
        )

    tp = fp = tn = fn = 0
    for predicted, actual in zip(predictions, labels):
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1

    return ConfusionMatrix(
        true_positive=tp, false_positive=fp, true_negative=tn, false_negative=fn
    )


def calibration(
    confidences: list[float],
    outcomes: list[bool],
    *,
    bin_count: int = 10,
) -> CalibrationReport:
    """
    Build a reliability diagram over ``bin_count`` equal-width buckets.

    Expected calibration error is the sample-weighted mean absolute gap
    between stated confidence and observed correctness.
    """
    if len(confidences) != len(outcomes):
        raise ValueError("confidences and outcomes must be the same length")
    if not confidences:
        return CalibrationReport()
    if bin_count < 1:
        raise ValueError("bin_count must be at least 1")

    width = 1.0 / bin_count
    bins: list[CalibrationBin] = []
    weighted_error = 0.0
    max_error = 0.0
    signed_total = 0.0
    total = len(confidences)

    for index in range(bin_count):
        lower = index * width
        upper = (index + 1) * width
        # The final bin is closed so a confidence of exactly 1.0 lands in it.
        members = [
            (c, o)
            for c, o in zip(confidences, outcomes)
            if (lower <= c < upper) or (index == bin_count - 1 and c == upper)
        ]
        if not members:
            bins.append(CalibrationBin(lower=lower, upper=upper))
            continue

        predicted_mean = sum(c for c, _ in members) / len(members)
        observed_rate = sum(1 for _, o in members if o) / len(members)
        bucket = CalibrationBin(
            lower=lower,
            upper=upper,
            count=len(members),
            predicted_mean=predicted_mean,
            observed_rate=observed_rate,
        )
        bins.append(bucket)

        gap = abs(bucket.gap)
        weighted_error += (len(members) / total) * gap
        max_error = max(max_error, gap)
        signed_total += (len(members) / total) * bucket.gap

    return CalibrationReport(
        bins=tuple(bins),
        expected_calibration_error=weighted_error,
        max_calibration_error=max_error,
        sample_size=total,
        # Overconfidence is the dangerous direction: it means the system
        # claims more certainty than it earns.
        overconfident=signed_total > 0.05,
    )
