"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    decision.engine

Purpose:
    Turn one intelligence package into a decision: ranked conclusions, an
    alerting verdict, and the next steps that would improve the answer.

Design goals:
    - One entry point; the ordering of the stages is not a caller's choice
    - Ranking by severity discounted by confidence, never by severity alone
    - Silence explained, so a quiet system is distinguishable from a broken one
    - Deterministic given a package and a clock
    - Decides only; interpretation happened upstream, delivery happens downstream

Notes:
    The stage order is fixed because it encodes policy. Conclusions are formed
    before alerting is considered, so the maturity ceiling is applied once and
    everything downstream inherits it; recommendations are derived last, from
    what the conclusions could not establish, so they describe the actual gaps
    rather than anticipated ones.

    Ranking multiplies severity by confidence rather than averaging them. A
    critical claim held at 0.1 must rank below a moderate claim held at 0.6 --
    an average inverts that, and the inversion puts the least supported claim at
    the top of an analyst's queue.

    :attr:`Decision.silence_explained` exists because the most likely question
    an operator has about A01 today is "why did nothing fire". The answer is
    that no detector has a measured error rate, and it should be readable from
    the output rather than requiring someone to know the doctrine.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable

from .alerts import AlertDecision, AlertPolicy, Subscription
from .conclusions import Conclusion, ConclusionBuilder, Stance
from .maturity import MaturityGate
from .recommendations import Recommendation, RecommendationEngine
from .vocabulary import BindingConstraint, binding_constraint

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Decision:
    """
    Everything A01 decided about one subject.

    ``constraint`` is the binding one across all conclusions, not their mean.
    A decision resting on a 0.95 observation and a 0.30 inference is bounded by
    the inference, and an averaged 0.62 would hide which link is load-bearing.
    """

    subject: str
    conclusions: tuple[Conclusion, ...] = ()
    alerts: AlertDecision = field(default_factory=AlertDecision)
    recommendations: tuple[Recommendation, ...] = ()
    constraint: BindingConstraint | None = None
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def actionable(self) -> tuple[Conclusion, ...]:
        """Conclusions that say something, ranked."""
        return tuple(c for c in self.conclusions if c.actionable)

    @property
    def undetermined(self) -> tuple[Conclusion, ...]:
        return tuple(c for c in self.conclusions if c.stance is Stance.UNDETERMINED)

    @property
    def top(self) -> Conclusion | None:
        return self.actionable[0] if self.actionable else None

    @property
    def silence_explained(self) -> str:
        """
        Why no alert was raised, in one line.

        Empty when something did alert. The likeliest question about A01 today
        is why it is quiet, and the answer is doctrine rather than a fault.
        """
        if not self.alerts.silent:
            return ""
        reasons = self.alerts.reasons()
        if reasons.get("unvalidated_detector"):
            return (
                "no detector has a measured error rate, so none may alert "
                "(capabilities.md §3, detection-catalog.md §7.3)"
            )
        if not self.actionable:
            return "nothing actionable was concluded"
        if not self.alerts.suppressed:
            return "no subscription covers these detectors"
        return "; ".join(f"{reason}: {count}" for reason, count in reasons.items())

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "conclusions": [c.as_dict() for c in self.conclusions],
            "actionable_count": len(self.actionable),
            "undetermined_count": len(self.undetermined),
            "alerts": self.alerts.as_dict(),
            "silence_explained": self.silence_explained,
            "recommendations": [r.as_dict() for r in self.recommendations],
            "constraint": self.constraint.as_dict() if self.constraint else None,
            "decided_at": self.decided_at.isoformat(),
        }


class DecisionEngine:
    """
    The decision layer's single entry point.

    Composed of the maturity gate, the conclusion builder, the alert policy and
    the recommendation engine, all sharing one gate so a ceiling applied in one
    place cannot be bypassed in another.
    """

    def __init__(
        self,
        *,
        subscriptions: Iterable[Subscription] = (),
        gate: MaturityGate | None = None,
    ) -> None:
        self._gate = gate if gate is not None else MaturityGate()
        self._conclusions = ConclusionBuilder(self._gate)
        self._alerts = AlertPolicy(subscriptions, gate=self._gate)
        self._recommendations = RecommendationEngine()

    @property
    def gate(self) -> MaturityGate:
        return self._gate

    @property
    def alert_policy(self) -> AlertPolicy:
        return self._alerts

    def decide(self, package: Any, *, now: datetime | None = None) -> Decision:
        """
        Decide on one intelligence package.

        ``now`` is injectable so alert budgets are testable without the test
        depending on the wall clock.
        """
        moment = now or datetime.now(UTC)
        conclusions = self._conclusions.build(package)

        subject_map = getattr(package, "subject", {}) or {}
        subject = str(subject_map.get("address") or subject_map.get("chain") or "unknown")
        coverage = subject_map.get("coverage") or {}

        alerts = self._alerts.decide(conclusions, now=moment)
        recommendations = self._recommendations.recommend(
            conclusions, coverage=coverage
        )
        constraint = binding_constraint(
            [(c.claim, c.confidence) for c in conclusions if c.actionable]
        )

        if alerts.silent and conclusions:
            logger.info(
                "decision for %s raised no alert: %s",
                subject,
                alerts.reasons() or "no subscriptions configured",
            )

        return Decision(
            subject=subject,
            conclusions=conclusions,
            alerts=alerts,
            recommendations=recommendations,
            constraint=constraint,
            decided_at=moment,
        )

    def rank(self, decisions: Iterable[Decision]) -> tuple[Decision, ...]:
        """
        Order decisions across subjects, most pressing first.

        Ranked on the top actionable conclusion's priority -- severity
        discounted by confidence. A subject with nothing actionable ranks last
        however severe its undetermined findings would have been.
        """
        return tuple(
            sorted(
                decisions,
                key=lambda d: d.top.priority if d.top else -1.0,
                reverse=True,
            )
        )

    def health(self) -> dict[str, Any]:
        return {
            "gate": self._gate.health(),
            "alerts": self._alerts.health(),
        }

    def __repr__(self) -> str:
        return (
            f"DecisionEngine(detectors={len(self._gate)}, "
            f"subscriptions={len(self._alerts.subscriptions)})"
        )


__all__ = ["Decision", "DecisionEngine"]
