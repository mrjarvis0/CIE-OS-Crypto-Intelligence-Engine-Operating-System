"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the AI layer -- what a model is allowed to say, and what happens
when it says something else.

Most of these describe a hallucination and assert that it does not reach a
reader. The grounding check exists for exactly one purpose, and a test suite
that only exercised the happy path would not show whether it works.
"""

from __future__ import annotations

import pytest

from decision import DecisionEngine, Subscription
from decision.conclusions import Conclusion, Stance
from intelligence.core.engine import IntelligenceEngine
from intelligence.narrative import (
    GroundingCheck,
    ModelIdentity,
    Narrative,
    NarrativeComposer,
    NarrativeService,
)
from intelligence.schemas.evidence import EvidenceArtifact, EvidenceSource

ADDRESS = "0x31a1b2c3d4e5f60718293a4b5c6d7e8f90a1d07b"
OTHER = "0x99f1b2c3d4e5f60718293a4b5c6d7e8f90a1ffff"


@pytest.fixture
def evidence():
    return [
        EvidenceArtifact(
            claim="whale-scale transfer observed",
            source_type=EvidenceSource.ON_CHAIN,
            content_hash="ev-1",
            data={"address": ADDRESS, "value": 773.64, "transactions": 176},
        )
    ]


@pytest.fixture
def decision():
    subject = {
        "address": ADDRESS,
        "chain": "ethereum",
        "coverage": {
            "blocks": 6,
            "threshold": 3600,
            "supports_absence": False,
            "limitation": "only 6 blocks stored",
            "window": {"contiguous": True},
        },
        "large_transfers": [
            {
                "value": 5e21,
                "kind": "transfer",
                "direction": "out",
                "counterparty_type": "exchange",
            }
        ],
        "transfer_population": [1e18] * 1200 + [5e21],
        "circulating_supply": 1e26,
    }
    package = IntelligenceEngine().run(subject)
    return DecisionEngine(subscriptions=[Subscription("desk")]).decide(package)


class FakeProvider:
    """A provider returning scripted text, standing in for a model."""

    def __init__(self, text: str, *, raises: bool = False) -> None:
        self.identity = ModelIdentity("fake-model", "1", temperature=0.7)
        self._text = text
        self._raises = raises

    def rewrite(self, draft: Narrative, evidence) -> str:  # noqa: ANN001
        if self._raises:
            raise RuntimeError("provider unavailable")
        return self._text


# ==============================================================================
# GROUNDING — the particulars
# ==============================================================================

def test_a_fabricated_address_is_caught(evidence):
    report = GroundingCheck().check(f"Funds moved to {OTHER}.", evidence)

    assert not report.publishable
    assert OTHER in report.reason()


def test_a_fabricated_quantity_is_caught(evidence):
    report = GroundingCheck().check("The address moved 9999.99 ETH.", evidence)

    assert not report.publishable


def test_a_real_address_grounds(evidence):
    report = GroundingCheck().check(f"Activity from {ADDRESS}.", evidence)

    assert report.publishable
    assert report.cited == ("ev-1",)


def test_an_abbreviated_address_grounds(evidence):
    """A01 renders 0xabcd…wxyz; requiring full addresses would block every report."""
    report = GroundingCheck().check("Activity from 0x31a1…d07b.", evidence)

    assert report.publishable


def test_a_fabricated_suffix_on_a_real_prefix_is_caught(evidence):
    """
    The half a reader uses to tell two similar addresses apart. Checking only
    the prefix would leave it free to be invented.
    """
    report = GroundingCheck().check("Activity from 0x31a1…ffff.", evidence)

    assert not report.publishable


def test_ends_spliced_from_two_addresses_are_caught(evidence):
    """Both ends must belong to the same address, not merely exist somewhere."""
    with_two = evidence + [
        EvidenceArtifact(
            claim="second address",
            source_type=EvidenceSource.ON_CHAIN,
            content_hash="ev-2",
            data={"address": OTHER},
        )
    ]
    report = GroundingCheck().check("Activity from 0x31a1…ffff.", with_two)

    assert not report.publishable


def test_prose_without_particulars_passes(evidence):
    """The doctrine permits structuring and explanation; only facts are checked."""
    report = GroundingCheck().check(
        "The window is shallow, so no absence can be concluded.", evidence
    )

    assert report.publishable
    assert report.checked == 0


def test_rounded_figures_ground_within_tolerance(evidence):
    """Narratives round; a check that forbade it would forbid readable prose."""
    assert GroundingCheck().check("Roughly 773.6 ETH moved.", evidence).publishable


def test_small_counts_are_prose_not_data(evidence):
    """Demanding evidence for 'two of three sources' trains a reader to skip the report."""
    report = GroundingCheck().check("Two of three checks agreed.", evidence)

    assert report.publishable


def test_a_blocked_narrative_is_replaced_not_edited(evidence):
    """
    Redacting spans leaves prose whose surrounding sentences still assert the
    removed facts, which reads as a complete report and is not one.

    The fabricated value does appear in the rejection reason, and should: that
    is a diagnostic naming what failed, not an assertion that it is true.
    """
    text, report = GroundingCheck().publish(f"Funds went to {OTHER}.", evidence)

    assert not report.publishable
    assert text.startswith("[withheld]")
    assert "Funds went to" not in text
    assert OTHER in report.reason()


def test_grounding_is_deterministic(evidence):
    check = GroundingCheck()
    text = f"Activity from {ADDRESS} totalling 773.64 ETH."

    assert check.check(text, evidence).as_dict() == check.check(text, evidence).as_dict()


# ==============================================================================
# COMPOSER
# ==============================================================================

def test_the_composer_needs_no_model(decision):
    narrative = NarrativeComposer().compose(decision)

    assert narrative.text
    assert narrative.method == "deterministic_composer@1"
    assert narrative.reproducibility == "deterministic"


def test_composed_output_is_grounded_by_construction(decision, evidence):
    """
    It never writes a particular it was not handed, which is what makes the
    grounding check a backstop rather than the primary defence.

    Checked against the same corpus the service uses — evidence plus the
    decision. A narrative legitimately states figures the system produced (a
    threshold, a block count) and those are not chain observations, but they
    are not fabrications either.
    """
    narrative = NarrativeComposer().compose(decision)
    corpus = NarrativeService()._corpus(decision, evidence)
    report = GroundingCheck().check(narrative.text, corpus)

    assert report.publishable, report.reason()


def test_the_composer_prints_the_decision_s_verb_not_its_own(decision):
    narrative = NarrativeComposer().compose(decision)
    affirmed = next(c for c in decision.conclusions if c.stance is Stance.AFFIRMED)

    assert affirmed.qualifier in narrative.text


def test_the_composer_states_why_negatives_are_withheld(decision):
    narrative = NarrativeComposer().compose(decision)

    assert "Negative findings are withheld" in narrative.text


def test_the_composer_states_falsifiability(decision):
    narrative = NarrativeComposer().compose(decision)

    assert "would be retracted by" in narrative.text


def test_the_composer_is_deterministic(decision):
    composer = NarrativeComposer()

    assert composer.compose(decision).text == composer.compose(decision).text


def test_an_empty_decision_still_produces_prose():
    from decision.engine import Decision

    narrative = NarrativeComposer().compose(Decision(subject=ADDRESS))

    assert "No analysis was produced" in narrative.text


# ==============================================================================
# SERVICE — the publication path
# ==============================================================================

def test_without_a_provider_the_composer_is_the_answer(decision, evidence):
    publication = NarrativeService().publish(decision, evidence=evidence)

    assert not publication.model_authored
    assert not publication.fell_back
    assert publication.narrative.text


def test_a_grounded_model_narrative_is_published(decision, evidence):
    provider = FakeProvider(f"The address {ADDRESS} moved 773.64 ETH.")
    publication = NarrativeService(provider=provider).publish(
        decision, evidence=evidence
    )

    assert publication.model_authored
    assert publication.narrative.method == "fake-model@1"
    assert publication.narrative.reproducibility == "stochastic"


def test_an_ungrounded_model_narrative_never_reaches_a_reader(decision, evidence):
    """The whole point of the layer: fluent text asserting a fabricated address."""
    provider = FakeProvider(f"Funds were routed through {OTHER} to an exchange.")
    publication = NarrativeService(provider=provider).publish(
        decision, evidence=evidence
    )

    assert publication.fell_back
    assert not publication.model_authored
    assert OTHER not in publication.narrative.text


def test_a_rejected_narrative_falls_back_rather_than_being_hedged(decision, evidence):
    """A hedged hallucination is still a hallucination."""
    provider = FakeProvider(f"Possibly {OTHER} was involved.")
    publication = NarrativeService(provider=provider).publish(
        decision, evidence=evidence
    )

    assert publication.fell_back
    assert publication.narrative.method == "deterministic_composer@1"


def test_a_failing_provider_does_not_cost_the_explanation(decision, evidence):
    """
    No path produces no explanation. A system whose only narrator is a model
    has nothing to say when the model is down.
    """
    publication = NarrativeService(provider=FakeProvider("", raises=True)).publish(
        decision, evidence=evidence
    )

    assert publication.fell_back
    assert "provider error" in publication.fallback_reason
    assert publication.narrative.text


def test_model_identity_is_recorded(decision, evidence):
    provider = FakeProvider(f"The address {ADDRESS} moved 773.64 ETH.")
    publication = NarrativeService(provider=provider).publish(
        decision, evidence=evidence
    )

    identity = publication.identity.as_dict()
    assert identity["method"] == "fake-model@1"
    assert identity["temperature"] == 0.7


def test_a_pinned_model_reports_deterministic_reproducibility():
    identity = ModelIdentity("m", "1", temperature=0.0, seed=7)

    assert identity.reproducibility == "deterministic"


def test_a_model_without_a_seed_is_stochastic():
    assert ModelIdentity("m", "1", temperature=0.0).reproducibility == "stochastic"


def test_evidence_is_fenced_before_reaching_a_prompt(evidence):
    """
    Chain data is attacker-controlled: a contract can be named after an
    instruction. It is untrusted input, not a formatting concern.
    """
    context = NarrativeService().prompt_context(evidence)

    assert "whale-scale transfer observed" in context
    assert len(context) > len("whale-scale transfer observed")


def test_health_states_that_no_model_is_configured():
    health = NarrativeService().health()

    assert health["model_configured"] is False
    assert health["grounding"] == "enforced"
