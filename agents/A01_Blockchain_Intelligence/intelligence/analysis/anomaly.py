"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.anomaly

Purpose:
    Statistical anomaly detection over an observed transfer population
    (DET-ANOMALY-01).

    Finds values that do not belong to the distribution the rest of the
    population describes. It does not say why, and it does not say what the
    deviation means.

What this detector refuses to do
--------------------------------
An anomaly is a statement about a distribution, not about intent or direction.
The detection catalog is explicit that classification comes strictly *after*
analysis, so this module reports deviation and stops. It never emits
"bullish", "bearish", "manipulation", "wash trading", or "smart money" -- each
of those is a conclusion requiring evidence this detector does not have and
cannot obtain from a value distribution alone.

The grading vocabulary is deliberately the one the evidence standard defines:
NORMAL / UNUSUAL / SUSPICIOUS / HIGH_RISK_PATTERN / INSUFFICIENT_EVIDENCE.
"SUSPICIOUS" here means "this value is far outside its population", which is a
measurement. It does not mean anyone did anything wrong.

Why the median absolute deviation
---------------------------------
Mean and standard deviation are the obvious choice and the wrong one. Transfer
value distributions are heavy-tailed, and a handful of very large transfers --
precisely the ones being looked for -- drag the mean up and inflate the
standard deviation enough to hide themselves. The effect is called masking, and
it makes a naive z-score quietly worst at exactly the job it was hired for.

The median absolute deviation has a 50% breakdown point: half the population
would have to be outliers before the estimate is corrupted. The 0.6745 factor
rescales it to be consistent with the standard deviation of a normal
distribution, so the resulting modified z-score reads on the familiar scale.

Reference: Iglewicz & Hoaglin, "How to Detect and Handle Outliers" (1993),
which is also the source of the 3.5 cutoff used below.

Why the logarithm, which matters more
-------------------------------------
A robust estimator on the wrong scale is still wrong. The modified z-score
assumes the population is roughly normal around its centre; transfer values are
not remotely normal, they are approximately log-normal, spanning many orders of
magnitude. Measured on raw values the MAD is tiny relative to the spread, and
almost everything scores as an outlier.

This is not a theoretical worry. The first version of this module ran on raw
values against 5,000 real ethereum transfers and flagged **1,581 of them --
31.6% of the population -- as outliers, with a maximum z of 88,104.** A
detector that calls a third of normal traffic anomalous is not a detector.

The same population, measured in log10 space: **zero outliers, maximum z of
2.5.** The values span 5.8e12 to 6.7e20 and are well-behaved once the scale
matches the distribution.

Note this does not contradict the whale detector flagging the largest of those
transfers. Percentile rank and distributional outlier are different questions:
the biggest sample from a log-normal population is expected to be the biggest,
and being so does not make it a departure from the distribution.

See docs/intelligence/detection-catalog.md.
"""

from __future__ import annotations

from math import log10
from statistics import median
from typing import Any, Final, Sequence

from ..schemas.evidence import ClaimTier, EvidenceSource
from .base import AnalyzerResult, BaseAnalyzer

#: Consistency constant: makes MAD estimate the standard deviation of a normal
#: distribution, so the modified z-score below reads on the usual scale.
_MAD_TO_SIGMA: Final[float] = 0.6745

#: Modified z-score above which a value is not plausibly from the population.
#: Iglewicz & Hoaglin's recommended cutoff.
OUTLIER_Z: Final[float] = 3.5

#: Below this many observations the population does not describe a distribution
#: and a "deviation" from it means nothing. Reporting NORMAL from eight
#: transfers would be a negative claim built from an absence of data, which is
#: the failure the whole evidence standard exists to prevent.
MIN_POPULATION: Final[int] = 20

#: Grading thresholds on the maximum modified z-score observed, in log space.
#: Deliberately close together: once the scale matches the distribution, a
#: z of 8 is already a value that does not belong. The earlier 10/50 bands were
#: tuned against the raw-value scale and are meaningless here.
UNUSUAL_Z: Final[float] = OUTLIER_Z
SUSPICIOUS_Z: Final[float] = 5.0
HIGH_RISK_Z: Final[float] = 8.0

#: Number of independent outliers that turns a large deviation into a pattern.
#: One extreme value is an event; several is a shape.
PATTERN_OUTLIERS: Final[int] = 3


class Grade:
    """
    The evidence standard's vocabulary for a deviation.

    Deliberately not an interpretation scale. ``SUSPICIOUS`` describes how far a
    value sits from its population, not the honesty of whoever sent it.
    """

    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
    NORMAL = "NORMAL"
    UNUSUAL = "UNUSUAL"
    SUSPICIOUS = "SUSPICIOUS"
    HIGH_RISK = "HIGH_RISK_PATTERN"


def _numeric(values: Any) -> list[float]:
    """Every finite, positive number in ``values``. Zero-value transfers are
    excluded: contract calls that move nothing are the bulk of chain traffic and
    would drag the median to zero, making every real transfer an outlier."""
    if not isinstance(values, (list, tuple)):
        return []

    out: list[float] = []
    for item in values:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number != number or number in (float("inf"), float("-inf")):
            continue
        if number > 0:
            out.append(number)
    return out


def modified_z_scores(values: Sequence[float]) -> tuple[list[float], float, float]:
    """
    Modified z-scores in log space, plus the median and MAD of the logs.

    Every value is transformed to log10 first, because the population is
    log-normal and the estimator assumes normality. Measuring on raw values
    flagged 31.6% of a real ethereum sample as outliers; see the module
    docstring.

    The returned median and MAD are therefore in log units. They are reported
    rather than converted back, because a MAD of 0.34 log-decades is the number
    that explains the scores, and an exponentiated version of it would not.

    Returns an empty score list when the MAD is zero. That happens when more
    than half the population holds the identical value, and it is not a
    degenerate case worth patching around: with no spread there is no scale to
    measure deviation against, and any non-zero difference would score
    infinitely. The honest answer is that the population cannot support the
    question.
    """
    if not values:
        return [], 0.0, 0.0

    scaled = [log10(value) for value in values]
    centre = median(scaled)
    mad = median([abs(value - centre) for value in scaled])

    if mad <= 0:
        return [], centre, 0.0

    scale = _MAD_TO_SIGMA / mad
    return [abs(value - centre) * scale for value in scaled], centre, mad


def grade(max_z: float, outliers: int) -> str:
    """Map a deviation onto the evidence standard's vocabulary."""
    if max_z >= HIGH_RISK_Z or (max_z >= SUSPICIOUS_Z and outliers >= PATTERN_OUTLIERS):
        return Grade.HIGH_RISK
    if max_z >= SUSPICIOUS_Z:
        return Grade.SUSPICIOUS
    if max_z >= UNUSUAL_Z:
        return Grade.UNUSUAL
    return Grade.NORMAL


class AnomalyAnalyzer(BaseAnalyzer):
    """
    Detects values that do not belong to their observed population.

    Emits STRUCTURAL evidence: that a value sits far from its population is an
    arithmetic fact about observed data. Why it does is not claimed, because
    nothing here can establish it.
    """

    name = "anomaly"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        address = self._address(subject)
        population = _numeric(self._get(subject, "transfer_population", []))

        # A negative result needs the coverage to license it. Without a window
        # that supports absence, "nothing unusual here" is a claim about what
        # was not looked at.
        absence_meaningful = bool(self._get(subject, "absence_meaningful", False))

        scores, centre, mad = modified_z_scores(population)

        if len(population) < MIN_POPULATION or not scores:
            data = self._insufficient(address, population, mad, absence_meaningful)
            return self._result(data=data, evidence=[], summary=self._summary(address, data))

        ranked = sorted(
            ((score, value) for score, value in zip(scores, population)),
            reverse=True,
        )
        outliers = [
            {"value": value, "z": round(score, 2)}
            for score, value in ranked
            if score >= OUTLIER_Z
        ]
        max_z = ranked[0][0]
        verdict = grade(max_z, len(outliers))

        # NORMAL is a negative claim and needs coverage behind it. Everything
        # else is positive -- an outlier was observed, which the data shows
        # regardless of how much else was never fetched.
        if verdict == Grade.NORMAL and not absence_meaningful:
            data = self._insufficient(
                address, population, mad, absence_meaningful,
                reason="no deviation found, but the window cannot license an absence",
            )
            return self._result(data=data, evidence=[], summary=self._summary(address, data))

        data: dict[str, Any] = {
            "address": address,
            "grade": verdict,
            "is_anomalous": verdict not in (Grade.NORMAL, Grade.INSUFFICIENT),
            "determinable": True,
            "population_size": len(population),
            "median_log10": centre,
            "mad_log10": mad,
            "max_z": round(max_z, 2),
            "outlier_count": len(outliers),
            "outliers": outliers[:5],
            "method": "modified z-score over median absolute deviation",
            "thresholds": {
                "outlier_z": OUTLIER_Z,
                "min_population": MIN_POPULATION,
                "pattern_outliers": PATTERN_OUTLIERS,
            },
            "absence_meaningful": absence_meaningful,
            # Consumed by intelligence.scoring.anomaly, which expects a list of
            # named severities rather than this detector's raw shape.
            "anomalies": [
                {
                    "name": f"transfer_outlier_{index}",
                    "severity": min(1.0, item["z"] / HIGH_RISK_Z),
                }
                for index, item in enumerate(outliers[:5])
            ],
            "not_claimed": (
                "direction, intent, and legitimacy: a deviation is a property "
                "of the distribution, not of whoever produced it"
            ),
        }

        evidence = []
        if data["is_anomalous"]:
            evidence.append(
                self._evidence(
                    claim=(
                        f"{len(outliers)} transfer value(s) for {address} lie outside "
                        f"their observed population (max modified z={data['max_z']})"
                    ),
                    data={
                        "address": address,
                        "grade": verdict,
                        "max_z": data["max_z"],
                        "outlier_count": len(outliers),
                        "population_size": len(population),
                        "method": data["method"],
                    },
                    source_type=EvidenceSource.ON_CHAIN,
                    tier=ClaimTier.STRUCTURAL,
                    confidence=0.75,
                    completeness=("external",),
                )
            )

        return self._result(
            data=data, evidence=evidence, summary=self._summary(address, data)
        )

    @staticmethod
    def _insufficient(
        address: str | None,
        population: list[float],
        mad: float,
        absence_meaningful: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        if not reason:
            if len(population) < MIN_POPULATION:
                reason = (
                    f"{len(population)} observation(s); {MIN_POPULATION} needed "
                    "before a deviation means anything"
                )
            else:
                reason = (
                    "the population has no spread (median absolute deviation is "
                    "zero), so there is no scale to measure deviation against"
                )
        return {
            "address": address,
            "grade": Grade.INSUFFICIENT,
            "is_anomalous": False,
            "determinable": False,
            "population_size": len(population),
            "mad": mad,
            "reason": reason,
            "absence_meaningful": absence_meaningful,
            "anomalies": [],
        }

    @staticmethod
    def _summary(address: str | None, data: dict[str, Any]) -> str:
        if not data["determinable"]:
            return f"{address}: anomaly not determinable ({data['reason']})"
        if not data["is_anomalous"]:
            return (
                f"{address}: NORMAL, no value outside its population of "
                f"{data['population_size']}"
            )
        return (
            f"{address}: {data['grade']} — {data['outlier_count']} outlier(s) in a "
            f"population of {data['population_size']} (max z={data['max_z']}); "
            "deviation only, no interpretation claimed"
        )


__all__ = [
    "HIGH_RISK_Z",
    "MIN_POPULATION",
    "OUTLIER_Z",
    "PATTERN_OUTLIERS",
    "SUSPICIOUS_Z",
    "AnomalyAnalyzer",
    "Grade",
    "grade",
    "modified_z_scores",
]
