"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for skill composition -- the point where the two halves of A01 meet.

The composed subject is what the detectors read, so a caveat lost here is a
caveat lost everywhere downstream. These tests are mostly about what survives
the merge: the weakest coverage, the disagreements, and the failures.
"""

from __future__ import annotations

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from intelligence.core.engine import IntelligenceEngine
from intelligence.engines import SubjectComposer
from sensors.envelope import Provenance, RawRecord, RecordKind
from skills.base import Coverage, Skill, SkillRequest, SkillResult
from skills.registry import Readiness, SkillEntry, SkillRegistry

TIMESTAMP = 1_700_000_000
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20


def block_record(number: int, transfers: list[tuple[str, str, int]]) -> RawRecord:
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", "ethereum", "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": f"0xa{number:06d}",
            "parentHash": f"0xa{number - 1:06d}",
            "timestamp": hex(TIMESTAMP + number * 12),
            "transactions": [
                {
                    "hash": f"0xtx{number:05d}{i:03d}",
                    "from": sender,
                    "to": recipient,
                    "value": hex(value),
                    "transactionIndex": hex(i),
                    "input": "0x",
                }
                for i, (sender, recipient, value) in enumerate(transfers)
            ],
        },
    )


@pytest.fixture
def stored():
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.write(block_record(100, [(ALICE, BOB, 10**24)]))
        writer.write(block_record(101, [(BOB, ALICE, 10**18)]))
        yield SqliteAnalyticsRepository(db)


class StubSkill(Skill):
    """A skill with a scripted result, for testing the merge itself."""

    def __init__(
        self,
        name: str,
        *,
        subject: dict | None = None,
        blocks: int = 10,
        supports_absence: bool = True,
        raises: bool = False,
    ) -> None:
        super().__init__(absence_threshold=1 if supports_absence else 10**9)
        self.name = name
        self._subject = subject or {}
        self._blocks = blocks
        self._raises = raises

    def run(self, request: SkillRequest, analytics) -> SkillResult:  # noqa: ANN001
        if self._raises:
            raise RuntimeError("scripted skill failure")
        coverage = self.coverage_for(request, analytics)
        if not self._subject:
            return self.undetermined(coverage, "scripted decline")
        return self.answer(coverage, {"stub": True}, dict(self._subject))


def registry_of(*skills: Skill) -> SkillRegistry:
    return SkillRegistry(
        tuple(SkillEntry(s, Readiness.IMPLEMENTED) for s in skills)
    )


# ==============================================================================
# THE JOIN
# ==============================================================================

def test_composition_builds_a_subject_from_stored_history(stored):
    """
    The gap this closes: before composition the detectors could only analyse a
    subject a human had already written out by hand.
    """
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)

    assert composition.usable
    assert composition.subject["address"] == ALICE
    assert composition.subject["large_transfers"]
    assert composition.subject["transfer_population"]


def test_a_composed_subject_drives_the_real_detectors(stored):
    """End to end: storage to a scored intelligence package, no hand-written input."""
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)
    package = IntelligenceEngine().run(composition.subject)

    findings = package.metadata["findings"]
    assert "whale" in findings
    assert findings["whale"]["data"]["address"] == ALICE


def test_all_three_skills_contribute(stored):
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)

    assert set(composition.contributed) == {
        "wallet_profile",
        "whale_transfers",
        "token_flow",
    }
    assert not composition.failed


# ==============================================================================
# COVERAGE SURVIVES THE MERGE
# ==============================================================================

def test_coverage_reduces_to_the_weakest_contributor(stored):
    """
    A subject is only as trustworthy as its thinnest input. Taking the best
    would let a deep window license absence claims about a shallow field.
    """
    deep = StubSkill("deep", subject={"a": 1}, supports_absence=True)
    shallow = StubSkill("shallow", subject={"b": 2}, supports_absence=False)

    composition = SubjectComposer(registry_of(deep, shallow)).compose(
        stored, chain="ethereum", address=ALICE
    )

    assert not composition.supports_absence


def test_absence_is_licensed_only_when_every_contributor_agrees(stored):
    both = registry_of(
        StubSkill("one", subject={"a": 1}, supports_absence=True),
        StubSkill("two", subject={"b": 2}, supports_absence=True),
    )
    composition = SubjectComposer(both).compose(stored, chain="ethereum", address=ALICE)

    assert composition.supports_absence


def test_coverage_reaches_the_subject_so_detectors_can_see_it(stored):
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)

    assert "coverage" in composition.subject
    assert composition.subject["absence_meaningful"] is False


def test_the_report_states_whether_negatives_are_licensed(stored):
    """
    A null signal over a thin window means 'nothing was looked at', not
    'nothing is there', and only this flag separates the two.
    """
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)
    package = IntelligenceEngine().run(composition.subject)

    report = package.metadata["findings"]["report"]
    assert report["negative_claims_licensed"] is False
    assert report["coverage"]["blocks"] == 2


def test_limitations_are_collected_from_every_skill(stored):
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)

    assert any("balance sensor" in note for note in composition.limitations)
    assert any("price feed" in note for note in composition.limitations)
    assert any("event-log decoding" in note for note in composition.limitations)


def test_limitations_are_deduplicated(stored):
    composition = SubjectComposer().compose(stored, chain="ethereum", address=ALICE)

    assert len(composition.limitations) == len(set(composition.limitations))


# ==============================================================================
# FAILURE CONTAINMENT
# ==============================================================================

def test_one_failing_skill_does_not_cost_the_others(stored):
    """
    The pipeline isolates stages; this isolates within one, so a broken flow
    skill does not discard the profile that succeeded.
    """
    registry = registry_of(
        StubSkill("good", subject={"a": 1}),
        StubSkill("broken", raises=True),
    )
    composition = SubjectComposer(registry).compose(stored, chain="ethereum")

    assert composition.contributed == ("good",)
    assert composition.failed == ("broken",)
    assert composition.subject["a"] == 1


def test_a_declining_skill_is_recorded_apart_from_a_failing_one(stored):
    """Declining is an answer; failing is a defect. They need different responses."""
    registry = registry_of(
        StubSkill("quiet", subject={}),
        StubSkill("broken", raises=True),
    )
    composition = SubjectComposer(registry).compose(stored, chain="ethereum")

    assert composition.declined == ("quiet",)
    assert composition.failed == ("broken",)


def test_conflicts_are_recorded_not_resolved(stored):
    """
    Last-write-wins would hide a genuine disagreement between skills behind a
    plausible value.
    """
    registry = registry_of(
        StubSkill("first", subject={"shared": "left"}),
        StubSkill("second", subject={"shared": "right"}),
    )
    composition = SubjectComposer(registry).compose(stored, chain="ethereum")

    assert composition.conflicts
    assert composition.subject["shared"] == "left"


def test_a_malformed_address_is_refused_not_passed_through(stored):
    """
    Handing the skills layer a typo makes every one report 'not found', which
    reads as an address with no history.
    """
    composition = SubjectComposer().compose(stored, chain="ethereum", address="0x123")

    assert not composition.usable
    assert any("address rejected" in note for note in composition.limitations)


def test_composition_over_an_empty_database_declines_cleanly():
    with Database() as empty:
        composition = SubjectComposer().compose(
            SqliteAnalyticsRepository(empty), chain="ethereum", address=ALICE
        )

    assert not composition.usable
    assert set(composition.declined) == {
        "wallet_profile",
        "whale_transfers",
        "token_flow",
        # Declines for a different reason from the other three: they have no
        # history to read, and it has no labels to attribute history to. Both
        # are refusals to answer, which is what this asserts.
        "exchange_flow",
    }


def test_composition_without_an_address_still_answers_chain_questions(stored):
    composition = SubjectComposer().compose(stored, chain="ethereum")

    assert "token_flow" in composition.contributed
    assert "address" not in composition.subject
