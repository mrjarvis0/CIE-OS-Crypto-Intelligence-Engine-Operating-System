"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    decision.alerts

Purpose:
    Decide which conclusions are worth interrupting a human for, and refuse to
    send the rest.

Design goals:
    - Nothing alerts without a measured error rate, per capabilities.md §3
    - Per-subscription daily budget; digest on breach, never a flood
    - Suppressions recorded with the reason, so a silent system is explicable
    - Deterministic: the same conclusions and clock produce the same output
    - No delivery; this decides, transport belongs to interfaces/

Notes:
    Alert fatigue is the primary failure mode of production intelligence
    (``detection-catalog.md`` §7.1), and it destroys true positives along with
    false ones -- once a channel is noise, the real alert is dismissed with the
    rest. So volume is budgeted rather than emergent, and the budget is a
    property of the subscription rather than of the detector: the person being
    interrupted is the one whose attention is being spent.

    **A01 currently sends no alerts at all.** Both detectors are `Implemented`,
    and §7.3 bars an unmeasured error rate from generating external alerts. The
    gate therefore suppresses everything, and this module's real output today is
    a list of suppressions naming what would have fired and why it did not.

    That is worth more than it sounds. It makes the alert path exercisable
    before it is live, so promotion is a registry edit rather than a scramble;
    and it makes the silence legible -- an operator can see that A01 is quiet
    because nothing is validated, not because nothing is happening.

    Over budget, a digest replaces the individual alerts rather than the excess
    being dropped. Dropping loses the tail, and the tail is where the unusual
    case sits; a digest keeps every conclusion while spending one interruption.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Final, Iterable

from .conclusions import Conclusion, Stance
from .maturity import MaturityGate

logger = logging.getLogger(__name__)

#: Default daily ceiling per subscription. Deliberately small: a channel that
#: can deliver fifty alerts a day is a channel nobody reads.
DEFAULT_DAILY_BUDGET: Final[int] = 10

#: Minimum confidence for an alert, independent of maturity. A validated
#: detector may still produce a weak result, and a weak result is a queue entry
#: rather than an interruption.
MIN_ALERT_CONFIDENCE: Final[float] = 0.70


class Suppression(StrEnum):
    """Why an alert was not sent."""

    #: The detector's error rate has never been measured.
    UNVALIDATED = "unvalidated_detector"
    #: Confidence below the alerting floor.
    LOW_CONFIDENCE = "low_confidence"
    #: The conclusion states nothing actionable.
    NOT_ACTIONABLE = "not_actionable"
    #: The subscription does not cover this detector.
    NOT_SUBSCRIBED = "not_subscribed"
    #: Daily budget exhausted; folded into a digest instead.
    OVER_BUDGET = "over_budget"


@dataclass(frozen=True, slots=True)
class Subscription:
    """
    One recipient's standing interest, and the attention they will spend.

    ``detectors`` empty means every detector. Naming them is preferred: a
    subscription that silently widens as detectors are added spends attention
    nobody agreed to.
    """

    name: str
    detectors: frozenset[str] = frozenset()
    max_alerts_per_day: int = DEFAULT_DAILY_BUDGET
    min_confidence: float = MIN_ALERT_CONFIDENCE

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a subscription must be named")
        if self.max_alerts_per_day <= 0:
            raise ValueError("max_alerts_per_day must be > 0")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within 0..1")

    def covers(self, detector: str) -> bool:
        return not self.detectors or detector in self.detectors

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "detectors": sorted(self.detectors) or ["*"],
            "max_alerts_per_day": self.max_alerts_per_day,
            "min_confidence": self.min_confidence,
        }


@dataclass(frozen=True, slots=True)
class Alert:
    """One conclusion escalated to a named recipient."""

    subscription: str
    subject: str
    detector: str
    claim: str
    qualifier: str
    confidence: float
    severity: float
    falsified_by: str
    raised_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "subscription": self.subscription,
            "subject": self.subject,
            "detector": self.detector,
            "claim": self.claim,
            "qualifier": self.qualifier,
            "confidence": self.confidence,
            "severity": self.severity,
            "falsified_by": self.falsified_by,
            "raised_at": self.raised_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SuppressedAlert:
    """A conclusion that did not become an alert, and why."""

    subscription: str
    subject: str
    detector: str
    claim: str
    reason: Suppression
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "subscription": self.subscription,
            "subject": self.subject,
            "detector": self.detector,
            "claim": self.claim,
            "reason": self.reason.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Digest:
    """
    A single interruption standing in for conclusions over budget.

    Carries every folded conclusion rather than a count. The budget limits how
    often a recipient is interrupted, not how much they are allowed to know.
    """

    subscription: str
    on: date
    folded: tuple[SuppressedAlert, ...]

    @property
    def count(self) -> int:
        return len(self.folded)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subscription": self.subscription,
            "date": self.on.isoformat(),
            "count": self.count,
            "folded": [item.as_dict() for item in self.folded],
        }


@dataclass(frozen=True, slots=True)
class AlertDecision:
    """Everything the alerting pass decided, sent and unsent alike."""

    raised: tuple[Alert, ...] = ()
    suppressed: tuple[SuppressedAlert, ...] = ()
    digests: tuple[Digest, ...] = ()

    @property
    def silent(self) -> bool:
        return not self.raised and not self.digests

    def reasons(self) -> dict[str, int]:
        """Suppression counts by reason, for an operator asking why it is quiet."""
        counts: dict[str, int] = {}
        for item in self.suppressed:
            counts[item.reason.value] = counts.get(item.reason.value, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "raised": [a.as_dict() for a in self.raised],
            "suppressed": [s.as_dict() for s in self.suppressed],
            "digests": [d.as_dict() for d in self.digests],
            "silent": self.silent,
            "suppression_reasons": self.reasons(),
        }


class AlertPolicy:
    """
    Applies alerting policy to decided conclusions.

    Budget state is kept per subscription per day in memory. That is the right
    scope for a process-lifetime agent and the wrong one for a long-running
    daemon, which would need it in ``database/`` to survive a restart -- noted
    rather than pretended: today nothing alerts, so a restart cannot leak an
    over-budget flood.
    """

    def __init__(
        self,
        subscriptions: Iterable[Subscription] = (),
        *,
        gate: MaturityGate | None = None,
    ) -> None:
        self._subscriptions = tuple(subscriptions)
        self._gate = gate if gate is not None else MaturityGate()
        self._spent: dict[tuple[str, date], int] = {}

    @property
    def subscriptions(self) -> tuple[Subscription, ...]:
        return self._subscriptions

    @property
    def gate(self) -> MaturityGate:
        return self._gate

    def subscribe(self, subscription: Subscription) -> None:
        self._subscriptions = self._subscriptions + (subscription,)

    def spent_today(self, subscription: str, on: date | None = None) -> int:
        return self._spent.get((subscription, on or datetime.now(UTC).date()), 0)

    # -- policy -----------------------------------------------------------

    def decide(
        self,
        conclusions: Iterable[Conclusion],
        *,
        now: datetime | None = None,
    ) -> AlertDecision:
        """
        Decide what to raise, what to suppress, and what to fold into a digest.

        ``now`` is injectable so budget behaviour is testable without a test
        depending on the wall clock or on the day it runs.
        """
        moment = now or datetime.now(UTC)
        today = moment.date()
        decided = list(conclusions)

        raised: list[Alert] = []
        suppressed: list[SuppressedAlert] = []
        digests: list[Digest] = []

        for subscription in self._subscriptions:
            over_budget: list[SuppressedAlert] = []

            for conclusion in decided:
                outcome = self._screen(subscription, conclusion)
                if outcome is not None:
                    suppressed.append(outcome)
                    continue

                key = (subscription.name, today)
                if self._spent.get(key, 0) >= subscription.max_alerts_per_day:
                    folded = SuppressedAlert(
                        subscription=subscription.name,
                        subject=conclusion.subject,
                        detector=conclusion.detector,
                        claim=conclusion.claim,
                        reason=Suppression.OVER_BUDGET,
                        detail=(
                            f"daily budget of {subscription.max_alerts_per_day} "
                            "reached; folded into a digest"
                        ),
                    )
                    over_budget.append(folded)
                    suppressed.append(folded)
                    continue

                self._spent[key] = self._spent.get(key, 0) + 1
                raised.append(
                    Alert(
                        subscription=subscription.name,
                        subject=conclusion.subject,
                        detector=conclusion.detector,
                        claim=conclusion.claim,
                        qualifier=conclusion.qualifier,
                        confidence=conclusion.confidence,
                        severity=conclusion.severity,
                        falsified_by=conclusion.falsified_by,
                        raised_at=moment,
                    )
                )

            if over_budget:
                logger.warning(
                    "%s: %d conclusion(s) over budget, folded into a digest",
                    subscription.name,
                    len(over_budget),
                )
                digests.append(
                    Digest(
                        subscription=subscription.name,
                        on=today,
                        folded=tuple(over_budget),
                    )
                )

        return AlertDecision(
            raised=tuple(raised),
            suppressed=tuple(suppressed),
            digests=tuple(digests),
        )

    def _screen(
        self, subscription: Subscription, conclusion: Conclusion
    ) -> SuppressedAlert | None:
        """
        The reason this conclusion must not alert, or None to let it through.

        Maturity is checked before confidence deliberately. An unvalidated
        detector is barred whatever its confidence, and reporting the
        confidence reason instead would suggest that a stronger result would
        have alerted -- which is the wrong lesson.
        """

        def refuse(reason: Suppression, detail: str) -> SuppressedAlert:
            return SuppressedAlert(
                subscription=subscription.name,
                subject=conclusion.subject,
                detector=conclusion.detector,
                claim=conclusion.claim,
                reason=reason,
                detail=detail,
            )

        if not subscription.covers(conclusion.detector):
            return refuse(
                Suppression.NOT_SUBSCRIBED,
                f"{subscription.name} does not subscribe to {conclusion.detector}",
            )

        if conclusion.stance is not Stance.AFFIRMED or not conclusion.actionable:
            return refuse(
                Suppression.NOT_ACTIONABLE,
                f"stance is {conclusion.stance.value}; nothing to act on",
            )

        standing = self._gate.for_detector(conclusion.detector)
        if not standing.may_alert:
            return refuse(
                Suppression.UNVALIDATED,
                (
                    f"{conclusion.detector} is {standing.maturity.label}; alerting "
                    f"requires a measured error rate ({standing.blocked_by})"
                ),
            )

        if conclusion.confidence < subscription.min_confidence:
            return refuse(
                Suppression.LOW_CONFIDENCE,
                (
                    f"confidence {conclusion.confidence:.2f} below "
                    f"{subscription.min_confidence:.2f}"
                ),
            )

        return None

    def health(self) -> dict[str, Any]:
        return {
            "subscriptions": [s.as_dict() for s in self._subscriptions],
            "alerting_detectors": [
                d.detector for d in self._gate.alerting_detectors()
            ],
            "budget_spent": {
                f"{name}@{day.isoformat()}": count
                for (name, day), count in self._spent.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"AlertPolicy(subscriptions={len(self._subscriptions)}, "
            f"alerting={len(self._gate.alerting_detectors())})"
        )


__all__ = [
    "DEFAULT_DAILY_BUDGET",
    "MIN_ALERT_CONFIDENCE",
    "Alert",
    "AlertDecision",
    "AlertPolicy",
    "Digest",
    "Subscription",
    "SuppressedAlert",
    "Suppression",
]
