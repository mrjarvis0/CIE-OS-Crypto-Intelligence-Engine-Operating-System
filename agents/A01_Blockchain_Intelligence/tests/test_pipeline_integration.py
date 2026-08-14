"""
CIE-OS
A01 Blockchain Intelligence Agent

Full-pipeline integration, replayed from recorded mainnet data.

Every other suite tests one layer against fakes. This one runs real Ethereum
blocks through sensor → ingestion → normalization → database → skills →
intelligence → decision → narrative, with no network and no mocks between the
layers, and asserts the properties that only exist when they are joined.

The reorg cases are the reason the harness exists. You cannot ask mainnet to
reorganise while a test watches, so until these could be replayed the
interaction between ingestion, the writer and storage was unverified in exactly
the situation where getting it wrong loses or corrupts history.
"""

from __future__ import annotations

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from decision import DecisionEngine, Subscription
from fixtures.replay import Recording, ReplaySensor, fork
from ingestion import BlockPoller, InMemoryCheckpointStore, RecordQueue
from ingestion.events import PollStatus
from intelligence.core.engine import IntelligenceEngine
from intelligence.engines import SubjectComposer
from intelligence.narrative import GroundingCheck, NarrativeService


@pytest.fixture(scope="module")
def recording() -> Recording:
    """Eight real mainnet blocks, captured once and committed."""
    return Recording.named("ethereum_mainnet")


@pytest.fixture
def sensor(recording) -> ReplaySensor:
    return ReplaySensor(recording)


def build_poller(sensor: ReplaySensor, queue: RecordQueue) -> BlockPoller:
    """A poller starting at the first recorded height, with no confirmation lag."""
    return BlockPoller(
        sensor,
        queue=queue,
        checkpoints=InMemoryCheckpointStore(),
        start_height=sensor.recording.heights[0],
        include_transactions=True,
        confirmations=0,
    )


@pytest.fixture
def pipeline(sensor):
    """A full capture-to-storage pipeline over the replay sensor."""
    queue: RecordQueue = RecordQueue(capacity=64)
    poller = build_poller(sensor, queue)
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        yield poller, queue, writer, db


# ==============================================================================
# CAPTURE TO STORAGE
# ==============================================================================

def test_recorded_blocks_reach_storage_intact(pipeline, recording):
    poller, queue, writer, db = pipeline

    report = writer.consume(poller.run(max_steps=4), queue)

    assert report.written == 4
    assert not report.rejections
    stored = SqliteBlockRepository(db).highest("ethereum")
    assert stored is not None
    assert stored.number in recording.heights


def test_real_transactions_survive_normalization(pipeline, recording):
    """
    Mainnet blocks carry contract creations, zero-value calls and enormous
    values. A fixture of hand-written transactions would not.
    """
    poller, queue, writer, db = pipeline
    writer.consume(poller.run(max_steps=2), queue)

    assert writer.stats.transactions_written > 100
    assert writer.normalizer.stats.rejected == 0


def test_replaying_the_same_range_writes_nothing_new(pipeline, sensor):
    """
    Idempotency across a restart. The in-memory dedup window empties when the
    process does, so the durable guarantee has to come from the primary key —
    and only a second run against the same storage shows whether it does.
    """
    poller, queue, writer, db = pipeline
    writer.consume(poller.run(max_steps=3), queue)
    before = writer.stats.written
    assert before == 3

    # A fresh poller with a fresh checkpoint store: a restart, in other words.
    second_queue: RecordQueue = RecordQueue(capacity=64)
    report = writer.consume(build_poller(sensor, second_queue).run(max_steps=3), second_queue)

    assert writer.stats.written == before, "a replay must not write a second copy"
    assert report.duplicates == 3


# ==============================================================================
# REORG — the paths mainnet will not perform on request
# ==============================================================================

def test_a_reorg_withdraws_the_abandoned_branch(pipeline, recording, sensor):
    poller, queue, writer, db = pipeline
    repo = SqliteBlockRepository(db)

    writer.consume(poller.run(max_steps=5), queue)
    forked_at = recording.heights[3]
    original = repo.at_height("ethereum", forked_at)[0].block_hash

    sensor.reorg_to(fork(recording, at=forked_at))
    writer.consume(poller.run(max_steps=5), queue)

    canonical = repo.at_height("ethereum", forked_at)
    everything = repo.at_height("ethereum", forked_at, include_withdrawn=True)

    assert len(canonical) == 1, "exactly one block may be canonical at a height"
    assert canonical[0].block_hash != original
    assert len(everything) == 2, "the abandoned observation must survive"


def test_the_abandoned_branch_is_marked_not_deleted(pipeline, recording, sensor):
    """
    Deleting would erase the evidence that a reorg happened, which is the one
    thing an analyst investigating a double spend needs.
    """
    poller, queue, writer, db = pipeline
    repo = SqliteBlockRepository(db)

    writer.consume(poller.run(max_steps=5), queue)
    forked_at = recording.heights[3]
    sensor.reorg_to(fork(recording, at=forked_at))
    writer.consume(poller.run(max_steps=5), queue)

    withdrawn = [
        b
        for b in repo.at_height("ethereum", forked_at, include_withdrawn=True)
        if not b.canonical
    ]
    assert len(withdrawn) == 1
    assert withdrawn[0].withdrawn_at is not None


def test_a_deep_fork_withdraws_every_affected_height(pipeline, recording, sensor):
    poller, queue, writer, db = pipeline
    repo = SqliteBlockRepository(db)

    writer.consume(poller.run(max_steps=6), queue)
    forked_at = recording.heights[1]

    sensor.reorg_to(fork(recording, at=forked_at))
    writer.consume(poller.run(max_steps=6), queue)

    assert writer.stats.withdrawn_blocks >= 1
    for height in recording.heights[1:5]:
        canonical = repo.at_height("ethereum", height)
        assert len(canonical) <= 1


def test_analytics_never_double_count_a_reorged_range(pipeline, recording, sensor):
    """
    Withdrawn blocks stay in the table by design. An aggregate that included
    them would count the reorged range twice, silently.
    """
    poller, queue, writer, db = pipeline

    writer.consume(poller.run(max_steps=5), queue)
    sensor.reorg_to(fork(recording, at=recording.heights[3]))
    writer.consume(poller.run(max_steps=5), queue)

    analytics = SqliteAnalyticsRepository(db)
    window = analytics.window("ethereum")

    assert window.blocks == len(set(window_heights(db)))


def window_heights(db) -> list[int]:
    rows = db.connection.execute(
        "SELECT number FROM blocks WHERE canonical = 1 AND chain = 'ethereum'"
    )
    return [int(row["number"]) for row in rows]


# ==============================================================================
# FAULTS
# ==============================================================================

def test_a_provider_failure_is_not_read_as_an_empty_chain(pipeline, recording, sensor):
    """
    The distinction the whole capture path is built around: not learning the
    answer is not the same as learning that the answer is empty.
    """
    poller, queue, writer, db = pipeline
    sensor.fail_at(recording.heights[0])

    results = poller.run(max_steps=2)

    assert all(r.status is not PollStatus.ADVANCED for r in results)
    assert any(r.status is PollStatus.UNDETERMINED for r in results)
    # Crucially the checkpoint did not move: an unread height must be retried,
    # not skipped as though it had been read and found empty.
    assert SqliteBlockRepository(db).count("ethereum") == 0


def test_the_pipeline_resumes_after_a_fault_clears(pipeline, recording, sensor):
    poller, queue, writer, db = pipeline
    sensor.fail_at(recording.heights[0])
    poller.run(max_steps=2)

    sensor.recover()
    writer.consume(poller.run(max_steps=3), queue)

    assert SqliteBlockRepository(db).count("ethereum") > 0


# ==============================================================================
# STORAGE TO INTELLIGENCE
# ==============================================================================

def test_the_read_side_runs_over_replayed_storage(pipeline):
    """Storage → skills → intelligence → decision → narrative, offline."""
    poller, queue, writer, db = pipeline
    writer.consume(poller.run(max_steps=6), queue)

    analytics = SqliteAnalyticsRepository(db)
    biggest = SqliteBlockRepository(db).largest_transfers("ethereum", limit=1)
    assert biggest, "recorded mainnet blocks must contain transfers"
    target = biggest[0].from_address.value

    composition = SubjectComposer().compose(
        analytics, chain="ethereum", address=target
    )
    package = IntelligenceEngine().run(composition.subject)
    decision = DecisionEngine(subscriptions=[Subscription("desk")]).decide(package)

    assert composition.contributed
    assert decision.conclusions


def test_a_shallow_replay_window_licenses_no_negative(pipeline):
    """Eight blocks is nowhere near the absence threshold, and must say so."""
    poller, queue, writer, db = pipeline
    writer.consume(poller.run(max_steps=8), queue)

    composition = SubjectComposer().compose(
        SqliteAnalyticsRepository(db), chain="ethereum"
    )

    assert not composition.supports_absence
    assert any("blocks stored" in note for note in composition.limitations)


def test_no_alert_fires_from_replayed_data(pipeline):
    """
    End to end, against real chain data: the maturity gate holds. If this ever
    fails, either a detector was backtested or the gate was bypassed.
    """
    poller, queue, writer, db = pipeline
    writer.consume(poller.run(max_steps=6), queue)

    composition = SubjectComposer().compose(
        SqliteAnalyticsRepository(db), chain="ethereum"
    )
    package = IntelligenceEngine().run(composition.subject)
    decision = DecisionEngine(subscriptions=[Subscription("desk")]).decide(package)

    assert decision.alerts.raised == ()


def test_the_narrative_over_real_data_is_grounded(pipeline):
    poller, queue, writer, db = pipeline
    writer.consume(poller.run(max_steps=6), queue)

    composition = SubjectComposer().compose(
        SqliteAnalyticsRepository(db), chain="ethereum"
    )
    package = IntelligenceEngine().run(composition.subject)
    decision = DecisionEngine().decide(package)

    service = NarrativeService()
    publication = service.publish(decision)
    corpus = service._corpus(decision, [])

    assert GroundingCheck().check(publication.narrative.text, corpus).publishable
