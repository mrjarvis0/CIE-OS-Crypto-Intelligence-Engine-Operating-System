"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the decision layer -- the gate, the vocabulary, and the silence.

The most important assertion in this file is that A01 raises no alerts. That is
not a placeholder: capabilities.md §3 reserves alerting for detectors with a
measured error rate, both detectors are `Implemented`, and a test that passed
while an unvalidated detector alerted would be asserting the wrong thing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from decision import (
    Action,
    AlertPolicy,
    Conclusion,
    ConclusionBuilder,
    Decision,
    DecisionEngine,
    DetectorMaturity,
    Maturity,
    MaturityGate,
    RecommendationEngine,
    Stance,
    Subscription,
    Suppression,
    VocabularyError,
    band_for,
    binding_constraint,
    enforce,
    qualifier,
    violations,
)
from intelligence.core.engine import IntelligenceEngine

ADDRESS = "0x" + "a1" * 20


def subject_with_whale(*, absence: bool = False, population: int = 1200) -> dict:
    """A subject the whale detector fires on, with a reachable percentile."""
    return {
        "address": ADDRESS,
        "chain": "ethereum",
        "absence_meaningful": absence,
        "coverage": {
            "blocks": 5000 if absence else 6,
            "threshold": 3600,
            "supports_absence": absence,
            "limitation": "" if absence else "only 6 blocks stored",
            "window": {"contiguous": True, "span": 6, "blocks": 6},
        },
        "large_transfers": [
            {
                "value": 5e21,
                "kind": "transfer",
                "direction": "out",
                "counterparty_type": "exchange",
            }
        ],
        "transfer_population": [1e18] * population + [5e21],
        "circulating_supply": 1e26,
    }


def package_for(subject: dict):
    return IntelligenceEngine().run(subject)


def validated_gate() -> MaturityGate:
    """A gate where the whale detector has been promoted, for alert tests."""
    return MaturityGate(
        (
            DetectorMaturity(
                detector="DET-WHALE-01",
                analyzer="whale",
                maturity=Maturity.VALIDATED,
            ),
            DetectorMaturity(
                detector="DET-DORMANT-01",
                analyzer="dormant",
                maturity=Maturity.IMPLEMENTED,
                blocked_by="never backtested",
            ),
        )
    )


# ==============================================================================
# MATURITY GATE
# ==============================================================================

def test_no_shipped_detector_may_alert():
    """
    The state of the system, asserted rather than assumed. If this ever fails,
    either a detector was backtested or the registry was edited without one.
    """
    assert MaturityGate().alerting_detectors() == ()


def test_implemented_maturity_caps_confidence_at_060():
    decision = MaturityGate().evaluate("whale", 0.95)

    assert decision.confidence == 0.60
    assert decision.capped
    assert "caps confidence" in decision.reason


def test_a_confidence_below_the_ceiling_is_untouched():
    decision = MaturityGate().evaluate("whale", 0.4)

    assert decision.confidence == 0.4
    assert not decision.capped


def test_an_unknown_detector_gets_nothing():
    """A typo in a name must silence a detector, not grant it privileges."""
    decision = MaturityGate().evaluate("typo", 0.99)

    assert decision.confidence == 0.0
    assert not decision.may_alert
    assert "not in the maturity registry" in decision.reason


def test_a_detector_below_validated_must_say_what_blocks_it():
    with pytest.raises(ValueError):
        DetectorMaturity(
            detector="DET-X", analyzer="x", maturity=Maturity.IMPLEMENTED
        )


def test_validated_detectors_may_alert_at_full_confidence():
    decision = validated_gate().evaluate("whale", 0.95)

    assert decision.confidence == 0.95
    assert decision.may_alert


# ==============================================================================
# VOCABULARY
# ==============================================================================

@pytest.mark.parametrize(
    "confidence,expected",
    [
        (0.95, "is"),
        (0.75, "almost certainly"),
        (0.55, "likely"),
        (0.35, "possibly"),
        (0.10, "cannot be determined"),
    ],
)
def test_the_verb_follows_the_confidence(confidence, expected):
    assert qualifier(confidence) == expected


def test_asserting_a_fact_at_moderate_confidence_is_refused():
    """
    Laundering an inference into a fact is what the evidence standard exists to
    prevent, so this raises rather than quietly softening the wording.
    """
    with pytest.raises(VocabularyError):
        enforce("the address is an exchange wallet", 0.55)


def test_wording_within_its_band_passes():
    text = "the address likely belongs to an exchange"
    assert enforce(text, 0.55) == text


def test_violation_matching_respects_word_boundaries():
    """'is' must not fire inside 'this' or 'analysis'."""
    assert violations("this analysis covers the window", 0.55) == ()


def test_bands_cover_the_range_without_gaps():
    for value in (0.0, 0.29, 0.30, 0.49, 0.50, 0.69, 0.70, 0.89, 0.90, 1.0):
        assert band_for(value) is not None


def test_out_of_range_confidence_is_clamped_not_rejected():
    assert band_for(1.5).label == "established"
    assert band_for(-2.0).label == "insufficient"


# ==============================================================================
# BINDING CONSTRAINT
# ==============================================================================

def test_the_constraint_is_the_weakest_link_not_the_average():
    """
    A 0.95 fact and a 0.30 inference must not present as 0.62 — the average
    hides that the conclusion fails if the inference does.
    """
    constraint = binding_constraint([("observation", 0.95), ("inference", 0.30)])

    assert constraint.confidence == 0.30
    assert constraint.source == "inference"
    assert constraint.qualifier == "possibly"


def test_no_evidence_yields_zero_not_a_vacuous_maximum():
    constraint = binding_constraint([])

    assert constraint.confidence == 0.0
    assert "no contributing evidence" in constraint.reason


# ==============================================================================
# CONCLUSIONS
# ==============================================================================

def test_a_conclusion_must_be_falsifiable():
    """detection-catalog.md §7.2: a detection that cannot be falsified is not one."""
    with pytest.raises(ValueError):
        Conclusion(
            subject=ADDRESS,
            claim="something happened",
            stance=Stance.AFFIRMED,
            confidence=0.5,
            falsified_by="",
        )


def test_a_fired_detector_produces_an_affirmed_conclusion():
    conclusions = ConclusionBuilder().build(package_for(subject_with_whale()))
    whale = next(c for c in conclusions if c.analyzer == "whale")

    assert whale.stance is Stance.AFFIRMED
    assert whale.confidence == 0.60
    assert whale.qualifier == "likely"
    assert whale.falsified_by


def test_a_negative_needs_coverage_or_it_becomes_undetermined():
    """
    'No whale activity' over six blocks is a statement about the six blocks.
    Reporting it as a negative is the most confident wrong answer available.
    """
    subject = subject_with_whale(absence=False)
    subject["large_transfers"] = []

    conclusions = ConclusionBuilder().build(package_for(subject))
    whale = next(c for c in conclusions if c.analyzer == "whale")

    assert whale.stance is Stance.UNDETERMINED
    assert whale.confidence == 0.0
    assert any("6 blocks" in caveat for caveat in whale.caveats)


def test_a_negative_is_stated_once_the_window_supports_it():
    subject = subject_with_whale(absence=True)
    subject["large_transfers"] = []

    conclusions = ConclusionBuilder().build(package_for(subject))
    whale = next(c for c in conclusions if c.analyzer == "whale")

    assert whale.stance is Stance.NEGATED


def test_priority_discounts_severity_by_confidence():
    """A severe claim at 0.1 must rank below a moderate one at 0.6."""
    severe = Conclusion(
        subject=ADDRESS, claim="c", stance=Stance.AFFIRMED, confidence=0.1,
        falsified_by="x", severity=90.0,
    )
    moderate = Conclusion(
        subject=ADDRESS, claim="c", stance=Stance.AFFIRMED, confidence=0.6,
        falsified_by="x", severity=40.0,
    )

    assert moderate.priority > severe.priority


def test_an_undetermined_conclusion_is_never_actionable():
    conclusion = Conclusion(
        subject=ADDRESS, claim="c", stance=Stance.UNDETERMINED, confidence=0.0,
        falsified_by="x",
    )
    assert not conclusion.actionable


# ==============================================================================
# ALERTS
# ==============================================================================

def test_an_unvalidated_detector_cannot_alert_however_confident():
    policy = AlertPolicy([Subscription("desk", min_confidence=0.0)])
    fired = Conclusion(
        subject=ADDRESS, claim="whale activity", stance=Stance.AFFIRMED,
        confidence=1.0, falsified_by="x", detector="DET-WHALE-01", severity=50.0,
    )

    outcome = policy.decide([fired])

    assert outcome.raised == ()
    assert outcome.suppressed[0].reason is Suppression.UNVALIDATED


def test_maturity_is_checked_before_confidence():
    """
    Reporting 'low confidence' for an unvalidated detector suggests a stronger
    result would have alerted, which is the wrong lesson.
    """
    policy = AlertPolicy([Subscription("desk", min_confidence=0.9)])
    weak = Conclusion(
        subject=ADDRESS, claim="c", stance=Stance.AFFIRMED, confidence=0.2,
        falsified_by="x", detector="DET-WHALE-01", severity=10.0,
    )

    outcome = policy.decide([weak])
    assert outcome.suppressed[0].reason is Suppression.UNVALIDATED


def test_a_validated_detector_alerts():
    policy = AlertPolicy([Subscription("desk")], gate=validated_gate())
    fired = Conclusion(
        subject=ADDRESS, claim="whale activity", stance=Stance.AFFIRMED,
        confidence=0.85, falsified_by="x", detector="DET-WHALE-01", severity=50.0,
    )

    outcome = policy.decide([fired])

    assert len(outcome.raised) == 1
    assert outcome.raised[0].subscription == "desk"


def test_a_validated_detector_below_the_floor_does_not_alert():
    policy = AlertPolicy([Subscription("desk", min_confidence=0.7)], gate=validated_gate())
    weak = Conclusion(
        subject=ADDRESS, claim="c", stance=Stance.AFFIRMED, confidence=0.5,
        falsified_by="x", detector="DET-WHALE-01", severity=10.0,
    )

    outcome = policy.decide([weak])
    assert outcome.suppressed[0].reason is Suppression.LOW_CONFIDENCE


def test_over_budget_conclusions_become_a_digest_not_a_flood():
    """
    Dropping the excess loses the tail, and the tail is where the unusual case
    sits. A digest keeps every conclusion while spending one interruption.
    """
    policy = AlertPolicy(
        [Subscription("desk", max_alerts_per_day=2)], gate=validated_gate()
    )
    fired = [
        Conclusion(
            subject=f"0x{i:040x}", claim="whale activity", stance=Stance.AFFIRMED,
            confidence=0.9, falsified_by="x", detector="DET-WHALE-01", severity=50.0,
        )
        for i in range(5)
    ]

    outcome = policy.decide(fired)

    assert len(outcome.raised) == 2
    assert len(outcome.digests) == 1
    assert outcome.digests[0].count == 3


def test_the_budget_is_per_day():
    policy = AlertPolicy(
        [Subscription("desk", max_alerts_per_day=1)], gate=validated_gate()
    )
    fired = Conclusion(
        subject=ADDRESS, claim="whale activity", stance=Stance.AFFIRMED,
        confidence=0.9, falsified_by="x", detector="DET-WHALE-01", severity=50.0,
    )
    today = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

    assert len(policy.decide([fired], now=today).raised) == 1
    assert len(policy.decide([fired], now=today).raised) == 0
    assert len(policy.decide([fired], now=today + timedelta(days=1)).raised) == 1


def test_a_subscription_only_receives_what_it_asked_for():
    policy = AlertPolicy(
        [Subscription("dormant-desk", detectors=frozenset({"DET-DORMANT-01"}))],
        gate=validated_gate(),
    )
    whale = Conclusion(
        subject=ADDRESS, claim="whale activity", stance=Stance.AFFIRMED,
        confidence=0.9, falsified_by="x", detector="DET-WHALE-01", severity=50.0,
    )

    outcome = policy.decide([whale])
    assert outcome.suppressed[0].reason is Suppression.NOT_SUBSCRIBED


def test_a_subscription_must_have_a_positive_budget():
    with pytest.raises(ValueError):
        Subscription("desk", max_alerts_per_day=0)


# ==============================================================================
# RECOMMENDATIONS
# ==============================================================================

def test_a_shallow_window_recommends_widening_it_first():
    engine = DecisionEngine()
    decision = engine.decide(package_for(subject_with_whale()))

    assert decision.recommendations[0].action is Action.WIDEN_WINDOW


def test_an_unmeasured_detector_recommends_backtesting():
    decision = DecisionEngine().decide(package_for(subject_with_whale()))
    actions = {r.action for r in decision.recommendations}

    assert Action.BACKTEST_DETECTOR in actions


def test_an_affirmed_conclusion_escalates_to_a_human():
    decision = DecisionEngine().decide(package_for(subject_with_whale()))
    actions = {r.action for r in decision.recommendations}

    assert Action.ESCALATE_TO_ANALYST in actions


def test_no_recommendation_concerns_buying_or_selling():
    """
    identity/scope.md §4 excludes investment advice. The catalogue is closed, so
    there is no path by which a market opinion reaches the output.
    """
    decision = DecisionEngine().decide(package_for(subject_with_whale()))
    forbidden = ("buy", "sell", "trade", "position", "invest", "price target")

    for recommendation in decision.recommendations:
        text = f"{recommendation.action.value} {recommendation.detail}".lower()
        assert not any(word in text for word in forbidden), text


def test_a_recommendation_must_name_what_it_unblocks():
    from decision.recommendations import Recommendation

    with pytest.raises(ValueError):
        Recommendation(action=Action.WIDEN_WINDOW, detail="do it", unblocks="")


# ==============================================================================
# ENGINE
# ==============================================================================

def test_the_engine_explains_its_silence():
    """The likeliest operational question about A01 today is why nothing fired."""
    engine = DecisionEngine(subscriptions=[Subscription("desk")])
    decision = engine.decide(package_for(subject_with_whale()))

    assert decision.alerts.silent
    assert "measured error rate" in decision.silence_explained


def test_the_engine_ranks_conclusions_by_priority():
    decision = DecisionEngine().decide(package_for(subject_with_whale()))
    priorities = [c.priority for c in decision.conclusions]

    assert priorities == sorted(priorities, reverse=True)


def test_decisions_rank_across_subjects():
    engine = DecisionEngine()
    strong = engine.decide(package_for(subject_with_whale()))
    quiet_subject = subject_with_whale()
    quiet_subject["large_transfers"] = []
    quiet = engine.decide(package_for(quiet_subject))

    ranked = engine.rank([quiet, strong])
    assert ranked[0] is strong


def test_an_empty_decision_is_well_formed():
    decision = Decision(subject=ADDRESS)

    assert decision.top is None
    assert decision.alerts.silent
    assert decision.as_dict()["actionable_count"] == 0
