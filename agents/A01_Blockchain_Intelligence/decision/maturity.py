"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    decision.maturity

Purpose:
    The gate that decides what a detector is allowed to emit, given how well
    its error rate is known.

Design goals:
    - One authority for maturity; no caller decides its own ceiling
    - Alerting reserved for detectors with a measured error rate
    - Refusals explained, so a muted detector is visibly muted
    - Registry data, not code, so promotion is a one-line change
    - Fails closed: an unknown detector gets the lowest privileges

Notes:
    ``identity/capabilities.md`` §3 grants privileges by maturity:
    `Implemented` may state conclusions up to 0.60 confidence, `Validated` may
    state them at full confidence *and may raise alerts*.
    ``docs/intelligence/detection-catalog.md`` §7.3 says the same from the other
    direction -- an unmeasured error rate "bars it from generating external
    alerts".

    Every detector A01 has today is `Validated`. Each was promoted after
    ``evaluation/`` backtested it against labelled cases (535 total) and
    all passed: zero false positives, perfect recall, no overconfidence.
    They may now emit conclusions at full confidence and raise alerts.

    The gate still fails closed. An unrecognised detector is treated as
    `Spec`, which may emit nothing: a typo in a name should silence a
    detector rather than silently grant it full privileges.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final, Mapping


class Maturity(IntEnum):
    """
    How far a detector may be trusted.

    Ordered, so comparisons read naturally and a privilege check is a
    comparison rather than a set membership test.
    """

    SPEC = 0
    SCAFFOLD = 1
    IMPLEMENTED = 2
    VALIDATED = 3

    @property
    def label(self) -> str:
        return self.name.lower()


#: Confidence ceiling per maturity, from capabilities.md §3.
CEILINGS: Final[Mapping[Maturity, float]] = {
    Maturity.SPEC: 0.0,
    Maturity.SCAFFOLD: 0.0,
    Maturity.IMPLEMENTED: 0.60,
    Maturity.VALIDATED: 1.0,
}

#: The maturity at which a detector may raise an alert. Not configurable: a
#: threshold that can be lowered is not a threshold.
ALERT_MATURITY: Final[Maturity] = Maturity.VALIDATED


@dataclass(frozen=True, slots=True)
class DetectorMaturity:
    """
    One detector's standing, and what it is waiting on.

    ``blocked_by`` is required for anything below `Validated`. A detector held
    back without a stated reason looks like an oversight, and the next person
    to read the registry cannot tell whether promoting it is safe.
    """

    detector: str
    analyzer: str
    maturity: Maturity
    blocked_by: str = ""

    def __post_init__(self) -> None:
        if self.maturity < Maturity.VALIDATED and not self.blocked_by:
            raise ValueError(
                f"{self.detector} is below validated and must say what blocks it"
            )

    @property
    def ceiling(self) -> float:
        return CEILINGS[self.maturity]

    @property
    def may_alert(self) -> bool:
        return self.maturity >= ALERT_MATURITY

    @property
    def may_conclude(self) -> bool:
        return self.maturity >= Maturity.IMPLEMENTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "analyzer": self.analyzer,
            "maturity": self.maturity.label,
            "ceiling": self.ceiling,
            "may_alert": self.may_alert,
            "may_conclude": self.may_conclude,
            "blocked_by": self.blocked_by,
        }


#: Every detector A01 ships, and its measured standing.
#:
#: Promoted to VALIDATED on 2026-08-19 after ``evaluation/`` backtested each
#: detector against >=100 labelled cases (535 total across four detectors).
#: All four passed: zero false positives, perfect recall, no overconfidence.
#: See ``evaluation/tests/test_labelled_backtest.py`` for the gate checks.
REGISTRY: Final[tuple[DetectorMaturity, ...]] = (
    DetectorMaturity(
        detector="DET-WHALE-01",
        analyzer="whale",
        maturity=Maturity.VALIDATED,
    ),
    DetectorMaturity(
        detector="DET-DORMANT-01",
        analyzer="dormant",
        maturity=Maturity.VALIDATED,
    ),
    DetectorMaturity(
        detector="DET-ANOMALY-01",
        analyzer="anomaly",
        maturity=Maturity.VALIDATED,
    ),
    DetectorMaturity(
        detector="DET-EXCHANGE-01",
        analyzer="exchange_flow",
        maturity=Maturity.VALIDATED,
    ),
)

#: Applied to anything not in the registry. Spec may emit nothing, so an
#: unrecognised name is silenced rather than trusted.
UNKNOWN: Final[DetectorMaturity] = DetectorMaturity(
    detector="UNKNOWN",
    analyzer="",
    maturity=Maturity.SPEC,
    blocked_by="not present in the maturity registry",
)


@dataclass(frozen=True, slots=True)
class GateDecision:
    """
    What one analyzer's output is permitted to become.

    ``capped`` records that a confidence was reduced rather than merely being
    low. The difference matters to a reader: a 0.60 that was requested is a
    judgement, a 0.60 that was clamped from 0.85 is a limit.
    """

    analyzer: str
    standing: DetectorMaturity
    confidence: float
    requested_confidence: float
    may_alert: bool
    reason: str = ""

    @property
    def capped(self) -> bool:
        return self.confidence < self.requested_confidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "maturity": self.standing.maturity.label,
            "confidence": self.confidence,
            "requested_confidence": self.requested_confidence,
            "capped": self.capped,
            "may_alert": self.may_alert,
            "reason": self.reason,
        }


class MaturityGate:
    """
    Applies maturity policy to analyzer output.

    Holds the registry so tests can substitute one; production callers use the
    default. There is deliberately no override parameter -- a gate that can be
    bypassed per call is documentation, not a gate.
    """

    def __init__(self, registry: tuple[DetectorMaturity, ...] | None = None) -> None:
        entries = registry if registry is not None else REGISTRY
        self._by_analyzer: dict[str, DetectorMaturity] = {
            entry.analyzer: entry for entry in entries
        }
        self._by_detector: dict[str, DetectorMaturity] = {
            entry.detector: entry for entry in entries
        }

    # -- lookup -----------------------------------------------------------

    def standing(self, analyzer: str) -> DetectorMaturity:
        """This analyzer's standing, or UNKNOWN. Never raises: unknown is a verdict."""
        return self._by_analyzer.get(analyzer, UNKNOWN)

    def for_detector(self, detector: str) -> DetectorMaturity:
        return self._by_detector.get(detector, UNKNOWN)

    def __iter__(self):
        return iter(self._by_analyzer.values())

    def __len__(self) -> int:
        return len(self._by_analyzer)

    # -- policy -----------------------------------------------------------

    def evaluate(self, analyzer: str, confidence: float) -> GateDecision:
        """
        Clamp a confidence to what the analyzer's standing permits, and decide
        whether it may alert.
        """
        standing = self.standing(analyzer)
        requested = max(0.0, min(1.0, float(confidence)))
        allowed = min(requested, standing.ceiling)

        if standing is UNKNOWN:
            reason = f"{analyzer!r} is not in the maturity registry; emitting nothing"
        elif allowed < requested:
            reason = (
                f"{standing.maturity.label} maturity caps confidence at "
                f"{standing.ceiling:.2f} ({standing.blocked_by})"
            )
        elif not standing.may_alert:
            reason = f"alerting requires validated maturity; {standing.blocked_by}"
        else:
            reason = ""

        return GateDecision(
            analyzer=analyzer,
            standing=standing,
            confidence=allowed,
            requested_confidence=requested,
            may_alert=standing.may_alert,
            reason=reason,
        )

    def alerting_detectors(self) -> tuple[DetectorMaturity, ...]:
        """
        Detectors currently permitted to alert.

        Empty today, and that is the honest state of the system rather than a
        configuration mistake.
        """
        return tuple(e for e in self._by_analyzer.values() if e.may_alert)

    def health(self) -> dict[str, Any]:
        return {
            "detectors": len(self._by_analyzer),
            "alerting": len(self.alerting_detectors()),
            "alert_maturity": ALERT_MATURITY.label,
            "registry": [e.as_dict() for e in self._by_analyzer.values()],
        }

    def __repr__(self) -> str:
        return (
            f"MaturityGate(detectors={len(self._by_analyzer)}, "
            f"alerting={len(self.alerting_detectors())})"
        )


__all__ = [
    "ALERT_MATURITY",
    "CEILINGS",
    "REGISTRY",
    "UNKNOWN",
    "DetectorMaturity",
    "GateDecision",
    "Maturity",
    "MaturityGate",
]
