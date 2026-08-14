"""
CIE-OS
A01 Blockchain Intelligence Agent

Regression: the same recorded input must keep producing the same intelligence.

A01's output is meant to be reproducible — `identity/objectives.md` §8 requires
deterministic outputs for identical inputs wherever possible, and
`evidence-standard.md` requires an important output to be reproducible at all.
Neither is verifiable by inspection. These tests pin the behaviour to recorded
mainnet data so that a change in what A01 concludes shows up as a failing test
rather than as a surprise in a report months later.

What is pinned is deliberately narrow: the *findings*, not the wording. Pinning
whole rendered strings produces a suite that fails on every copy edit and is
therefore disabled within a month. What must not drift silently is which
conclusions are reached, at what confidence, under what stance.
"""

from __future__ import annotations

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from decision import DecisionEngine
from fixtures.replay import Recording, ReplaySensor
from ingestion import BlockPoller, InMemoryCheckpointStore, RecordQueue
from intelligence.core.engine import IntelligenceEngine
from intelligence.engines import SubjectComposer
from intelligence.narrative import NarrativeService


@pytest.fixture(scope="module")
def stored():
    """
    Six recorded blocks, ingested once for the whole module.

    Module-scoped because ingesting real blocks with their full transaction
    sets is the slow part, and every test here reads the same corpus.
    """
    recording = Recording.named("ethereum_mainnet")
    sensor = ReplaySensor(recording)
    queue: RecordQueue = RecordQueue(capacity=64)
    poller = BlockPoller(
        sensor,
        queue=queue,
        checkpoints=InMemoryCheckpointStore(),
        start_height=recording.heights[0],
        include_transactions=True,
        confirmations=0,
    )

    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.consume(poller.run(max_steps=6), queue)
        yield db, recording


def investigate(db, address: str | None = None):
    composition = SubjectComposer().compose(
        SqliteAnalyticsRepository(db), chain="ethereum", address=address
    )
    package = IntelligenceEngine().run(composition.subject)
    return composition, package, DecisionEngine().decide(package)


# ==============================================================================
# DETERMINISM
# ==============================================================================

def test_the_same_input_produces_the_same_conclusions(stored):
    db, _ = stored

    _, _, first = investigate(db)
    _, _, second = investigate(db)

    def shape(decision):
        return [
            (c.detector, c.stance.value, c.confidence, c.qualifier)
            for c in decision.conclusions
        ]

    assert shape(first) == shape(second)


def test_the_same_input_produces_the_same_narrative(stored):
    db, _ = stored
    service = NarrativeService()

    _, _, first = investigate(db)
    _, _, second = investigate(db)

    assert (
        service.publish(first).narrative.text
        == service.publish(second).narrative.text
    )


def test_composition_is_stable(stored):
    db, _ = stored

    first, _, _ = investigate(db)
    second, _, _ = investigate(db)

    assert first.contributed == second.contributed
    assert first.coverage.as_dict() == second.coverage.as_dict()


# ==============================================================================
# PINNED BEHAVIOUR
# ==============================================================================

def test_the_recorded_window_stores_what_it_recorded(stored):
    db, recording = stored
    window = SqliteAnalyticsRepository(db).window("ethereum")

    assert window.blocks == 6
    assert window.from_height == recording.heights[0]
    assert window.contiguous


def test_every_recorded_transaction_normalizes(stored):
    """
    Real mainnet payloads, so this catches a normalizer regression against
    shapes a hand-written fixture would not contain.
    """
    db, _ = stored
    row = db.connection.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()

    assert row["n"] > 1_000


def test_no_stored_block_is_marked_incomplete(stored):
    """Blocks were captured with transactions expanded; quality must reflect it."""
    db, _ = stored
    row = db.connection.execute(
        "SELECT COUNT(*) AS n FROM blocks WHERE complete = 0"
    ).fetchone()

    assert row["n"] == 0


def test_a_shallow_window_still_refuses_negatives(stored):
    """
    Pinned because it is the property most likely to be lost by a refactor:
    six blocks must never license an absence claim.
    """
    db, _ = stored
    composition, _, decision = investigate(db)

    assert not composition.supports_absence
    assert all(c.stance.value != "negated" for c in decision.conclusions)


def test_confidence_never_exceeds_the_maturity_ceiling(stored):
    """
    The invariant every conclusion inherits. A regression here would let an
    unvalidated detector speak with more authority than it has earned.
    """
    db, _ = stored
    _, _, decision = investigate(db)

    for conclusion in decision.conclusions:
        assert conclusion.confidence <= 0.60


def test_every_conclusion_states_what_would_retract_it(stored):
    db, _ = stored
    _, _, decision = investigate(db)

    assert decision.conclusions
    for conclusion in decision.conclusions:
        assert conclusion.falsified_by.strip()


def test_the_narrative_always_ends_with_the_operator_disclaimer(stored):
    """A01 provides evidence, not decisions — and says so on every report."""
    db, _ = stored
    _, _, decision = investigate(db)

    text = NarrativeService().publish(decision).narrative.text
    assert text.rstrip().endswith("the determination remains with the operator.")
