"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    decision.conclusions

Purpose:
    Turn an intelligence package's findings into conclusions that state their
    own limits: what is claimed, how strongly, what bounds it, and what would
    retract it.

Design goals:
    - Confidence bounded by the maturity gate, never by the analyzer alone
    - The binding constraint reported, never an average
    - `falsified_by` required; an unfalsifiable claim is not a conclusion
    - Coverage carried through, so a negative claim needs a window to stand on
    - No interpretation: the finding's meaning was decided upstream

Notes:
    The decision layer decides *what to conclude*, not what the data means.
    That distinction is what keeps this module thin: it reads findings the
    intelligence layer already produced and applies policy -- ceilings,
    vocabulary, falsifiability, coverage -- without re-reading a transfer or
    re-deciding whether it was large.

    Two rules do most of the work here.

    **Negative conclusions need coverage.** "No whale activity" from a window
    of six blocks is a statement about the window. The composer already reports
    whether absence is licensed; this module refuses to state a negative when it
    is not, and downgrades it to "not determinable" -- which is a different
    claim and the true one.

    **`falsified_by` is mandatory.** ``detection-catalog.md`` §7.2: a detection
    that cannot be falsified is not a detection. Requiring the field at
    construction means the obligation cannot be deferred to a later cleanup that
    never happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from schemas.stance import Stance
from .maturity import GateDecision, MaturityGate
from .vocabulary import BindingConstraint, binding_constraint, qualifier


@dataclass(frozen=True, slots=True)
class Conclusion:
    """
    One decided claim, with everything needed to judge it.

    ``qualifier`` is derived, not supplied. A caller that could set its own verb
    would eventually set a stronger one than its confidence supports, which is
    exactly the laundering the evidence standard prohibits.
    """

    subject: str
    claim: str
    stance: Stance
    confidence: float
    #: What would retract this. Required -- see detection-catalog.md §7.2.
    falsified_by: str
    analyzer: str = ""
    detector: str = ""
    severity: float = 0.0
    constraint: BindingConstraint | None = None
    evidence_refs: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("a conclusion must state a claim")
        if not self.falsified_by.strip():
            raise ValueError(
                f"conclusion {self.claim!r} has no falsified_by; an unfalsifiable "
                "claim is not a detection (detection-catalog.md 7.2)"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    @property
    def qualifier(self) -> str:
        """The verb this confidence permits."""
        return qualifier(self.confidence)

    @property
    def actionable(self) -> bool:
        """
        Whether this says anything a reader should act on.

        An undetermined conclusion is worth reporting and never worth acting
        on; conflating the two is how a thin window becomes a decision.
        """
        return self.stance is not Stance.UNDETERMINED and self.confidence > 0.0

    @property
    def priority(self) -> float:
        """
        Ranking weight: severity discounted by confidence.

        Multiplied rather than averaged. A severe claim held at 0.1 confidence
        should rank below a moderate one held at 0.6, and an average would put
        it above.
        """
        return round(self.severity * self.confidence, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "claim": self.claim,
            "stance": self.stance.value,
            "confidence": self.confidence,
            "qualifier": self.qualifier,
            "severity": self.severity,
            "priority": self.priority,
            "analyzer": self.analyzer,
            "detector": self.detector,
            "falsified_by": self.falsified_by,
            "constraint": self.constraint.as_dict() if self.constraint else None,
            "evidence_refs": list(self.evidence_refs),
            "caveats": list(self.caveats),
            "actionable": self.actionable,
            "decided_at": self.decided_at.isoformat(),
        }


#: What each analyzer claims, what would retract it, and how much it matters.
#: Severity is the claim's inherent weight before confidence discounts it.
_CLAIM_SPECS: dict[str, dict[str, Any]] = {
    "whale": {
        "detector": "DET-WHALE-01",
        "affirmed": "whale-scale transfer activity observed",
        "negated": "no whale-scale transfer activity in the observed window",
        "open": "whether whale-scale transfer activity occurred",
        "falsified_by": (
            "the transfer resolving to an internal rebalance between addresses "
            "under one owner, or the value falling below its percentile once a "
            "fuller population is loaded"
        ),
        "severity": 55.0,
        "flag": "is_whale",
    },
    "dormant": {
        "detector": "DET-DORMANT-01",
        "affirmed": "dormant wallet reactivation observed",
        "negated": "no dormant reactivation in the observed window",
        "open": "whether a dormant wallet reactivated",
        "falsified_by": (
            "an outbound transaction inside the dormancy window appearing in a "
            "wider backfill, or the balance proving immaterial once balance "
            "state is available"
        ),
        "severity": 45.0,
        "flag": "reactivated",
    },
    "anomaly": {
        "detector": "DET-ANOMALY-01",
        # Worded as a measurement throughout. The detector establishes that a
        # value sits outside its population; it establishes nothing about why,
        # and a claim phrased as "suspicious activity" would smuggle in an
        # interpretation the evidence does not carry.
        "affirmed": "transfer values observed outside their statistical population",
        "negated": "no transfer value outside its population in the observed window",
        "open": "whether any transfer value lies outside its population",
        "falsified_by": (
            "the population proving unrepresentative once a wider window is "
            "loaded, or the outlying values sharing a single routine cause such "
            "as one contract's fixed-size transfers"
        ),
        "severity": 30.0,
        "flag": "is_anomalous",
    },
    "exchange_flow": {
        "detector": "DET-EXCHANGE-01",
        # Direction, never intent. "Sell pressure" is the phrasing this claim
        # would naturally attract and the one thing native value cannot
        # establish: the same deposit is consistent with selling, with posting
        # collateral, and with an operator moving its own custody.
        "affirmed": (
            "net directional movement between labelled exchange addresses and "
            "the rest of the chain observed"
        ),
        "negated": (
            "movement against labelled exchange addresses was two-way in the "
            "observed window, with no net direction"
        ),
        "open": "whether flow against labelled exchange addresses had a net direction",
        "falsified_by": (
            "the label list attributing an address to the wrong operator or "
            "missing the counterparty entirely, or the token and stablecoin "
            "transfers this detector cannot see running the other way"
        ),
        # Below whale and dormant. The measurement is sound and the attribution
        # under it is an unverified external claim, which is a weaker footing
        # than either of those detectors stands on.
        "severity": 40.0,
        "flag": "is_directional",
    },
}


class ConclusionBuilder:
    """
    Derives conclusions from an intelligence package's findings.

    Holds the maturity gate because every confidence must pass through it.
    Constructing conclusions without the gate is possible and is what a test
    does; production callers go through :class:`decision.engine.DecisionEngine`,
    which supplies it.
    """

    def __init__(self, gate: MaturityGate | None = None) -> None:
        self._gate = gate if gate is not None else MaturityGate()

    @property
    def gate(self) -> MaturityGate:
        return self._gate

    def build(self, package: Any) -> tuple[Conclusion, ...]:
        """
        Read a package's findings and decide what may be concluded from each.

        Accepts the package rather than a findings dict so the subject and the
        evidence travel with it; a builder handed loose findings cannot attach
        either, and a conclusion without evidence refs cannot be audited.
        """
        metadata = getattr(package, "metadata", {}) or {}
        findings = metadata.get("findings", {}) or {}
        subject_map = getattr(package, "subject", {}) or {}
        subject = str(subject_map.get("address") or subject_map.get("chain") or "unknown")

        absence_licensed = bool(subject_map.get("absence_meaningful"))
        coverage = subject_map.get("coverage") or {}

        conclusions: list[Conclusion] = []
        for analyzer, spec in _CLAIM_SPECS.items():
            finding = findings.get(analyzer)
            if not isinstance(finding, dict) or finding.get("ok") is False:
                continue
            conclusions.append(
                self._from_finding(
                    analyzer=analyzer,
                    spec=spec,
                    finding=finding,
                    subject=subject,
                    absence_licensed=absence_licensed,
                    coverage=coverage,
                )
            )

        return tuple(sorted(conclusions, key=lambda c: c.priority, reverse=True))

    # -- internals --------------------------------------------------------

    def _from_finding(
        self,
        *,
        analyzer: str,
        spec: dict[str, Any],
        finding: dict[str, Any],
        subject: str,
        absence_licensed: bool,
        coverage: dict[str, Any],
    ) -> Conclusion:
        data = finding.get("data", {}) or {}
        fired = bool(data.get(spec["flag"]))
        requested = float(finding.get("confidence", 0.0) or 0.0)

        decision: GateDecision = self._gate.evaluate(analyzer, requested)
        caveats: list[str] = []
        if decision.reason:
            caveats.append(decision.reason)

        evidence_refs = tuple(
            str(item.get("content_hash") or item.get("claim", ""))
            for item in finding.get("evidence", []) or []
            if isinstance(item, dict)
        )

        if fired:
            stance = Stance.AFFIRMED
            claim = spec["affirmed"]
            confidence = decision.confidence
        elif absence_licensed:
            stance = Stance.NEGATED
            claim = spec["negated"]
            confidence = decision.confidence
        else:
            # The important branch. Not finding something in a shallow window is
            # not evidence that it did not happen, and reporting it as a negative
            # would be the most confident wrong answer the system can produce.
            stance = Stance.UNDETERMINED
            # Phrased as the open question rather than as a negative with a
            # disclaimer attached. A reader skimming "no whale activity (but…)"
            # takes the negative and drops the parenthesis.
            claim = spec["open"]
            confidence = 0.0
            caveats.append(
                str(coverage.get("limitation"))
                if coverage.get("limitation")
                else "stored history is too shallow for an absence to mean anything"
            )

        constraint = binding_constraint(
            [
                (f"{analyzer} detector", decision.confidence),
                *(
                    [("coverage", 0.0)]
                    if stance is Stance.UNDETERMINED
                    else []
                ),
            ]
        )

        return Conclusion(
            subject=subject,
            claim=claim,
            stance=stance,
            confidence=confidence,
            falsified_by=spec["falsified_by"],
            analyzer=analyzer,
            detector=spec["detector"],
            severity=float(spec["severity"]) if stance is Stance.AFFIRMED else 0.0,
            constraint=constraint,
            evidence_refs=evidence_refs,
            caveats=tuple(caveats),
        )

    def __repr__(self) -> str:
        return f"ConclusionBuilder(detectors={len(self._gate)})"


__all__ = ["Conclusion", "ConclusionBuilder", "Stance"]
