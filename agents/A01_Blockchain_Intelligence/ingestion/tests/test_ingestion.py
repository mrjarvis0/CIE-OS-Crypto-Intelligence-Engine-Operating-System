"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for ingestion -- ordering, resumability, deduplication, and reorg
handling.

Every condition that matters here is unschedulable on a real chain. Reorgs are
rare, deep reorgs essentially never happen on demand, and a provider serving a
different network cannot be arranged. So the chain is scripted: a fake sensor
returns whatever block sequence a test needs, including sequences no honest
chain would produce, because those are exactly the ones the pipeline has to
survive.
"""

from __future__ import annotations

import pytest

from blockchain.reorg import BlockRef, ChainTracker
from core.exceptions import CheckpointError, FinalityViolationError, IngestionError
from ingestion import (
    Backfill,
    BlockPoller,
    Checkpoint,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    LinkageError,
    Overflow,
    PollStatus,
    RecordQueue,
    Seen,
    SeenSet,
    block_ref_from_payload,
    has_linkage,
)
from sensors.base import Capability, Sensor
from sensors.envelope import (
    CaptureGap,
    Provenance,
    RawRecord,
    RecordKind,
    SensorResult,
)


# ==============================================================================
# SCRIPTED CHAIN
# ==============================================================================

def evm_block(number: int, tag: str = "a", parent_tag: str | None = None) -> dict:
    """
    A block whose hash encodes its height and branch.

    Encoding the branch in the hash makes a fork readable in a failure message:
    ``0xb000101`` is plainly not ``0xa000101``.
    """
    parent = parent_tag if parent_tag is not None else tag
    return {
        "number": hex(number),
        "hash": f"0x{tag}{number:06d}",
        "parentHash": f"0x{parent}{number - 1:06d}" if number else "0x0",
    }


class FakeChain(Sensor):
    """
    A sensor over a scripted block map.

    Serves whatever a test puts in ``blocks``, which is what allows a fork to be
    installed mid-run: rewrite the entries above the fork point and the next
    read returns the competing branch, exactly as a reorg presents itself.
    """

    name = "fake_chain"

    def __init__(
        self,
        *,
        chain: str = "ethereum",
        head: int = 0,
        confirmations: int = 0,
        finalized: int | None = None,
    ) -> None:
        self._chain = chain
        self.blocks: dict[int, dict] = {}
        self.head_height = head
        self.confirmations = confirmations
        self.finalized = finalized
        self.reads: list[int] = []
        self.head_fails = False
        self.serves_logs = False

    # -- scripting -------------------------------------------------------

    def extend(self, upto: int, tag: str = "a", parent_tag: str | None = None) -> None:
        """Populate heights 0..upto on one branch."""
        for number in range(upto + 1):
            self.blocks[number] = evm_block(number, tag, parent_tag)
        self.head_height = upto

    def fork_from(self, height: int, upto: int, tag: str = "b") -> None:
        """
        Replace heights ``height``..``upto`` with a competing branch.

        The block at ``height`` keeps its parent on the original branch, which
        is what makes the fork point discoverable rather than a total rewrite.
        """
        self.blocks[height] = evm_block(height, tag, parent_tag="a")
        for number in range(height + 1, upto + 1):
            self.blocks[number] = evm_block(number, tag)
        self.head_height = max(self.head_height, upto)

    # -- Sensor ----------------------------------------------------------

    @property
    def chain(self) -> str:
        return self._chain

    def capability(self) -> Capability:
        return Capability(chain=self._chain, reachable=True, logs=True)

    def _record(self, kind: RecordKind, height: int, payload: object) -> RawRecord:
        return RawRecord(
            chain=self._chain,
            kind=kind,
            payload=payload,
            height=height,
            provenance=Provenance("fake", self._chain, "scripted", "ok"),
        )

    def head(self) -> SensorResult:
        if self.head_fails:
            return SensorResult(
                determined=False,
                chain=self._chain,
                method="head",
                outcome="all_endpoints_failed",
                reason="scripted head failure",
            )
        return SensorResult(
            determined=True,
            record=self._record(RecordKind.HEAD, self.head_height, self.head_height),
            chain=self._chain,
            method="head",
        )

    def finalized_head(self) -> SensorResult:
        if self.finalized is None:
            return SensorResult(
                determined=False,
                chain=self._chain,
                method="finalized_head",
                outcome="capability_unavailable",
                reason="not scripted",
            )
        payload = self.blocks.get(self.finalized) or evm_block(self.finalized)
        return SensorResult(
            determined=True,
            record=self._record(RecordKind.FINALIZED_HEAD, self.finalized, payload),
            chain=self._chain,
            method="finalized_head",
        )

    def logs(
        self,
        from_height: int,
        to_height: int,
        *,
        address: str | None = None,
        topics: list | None = None,
    ) -> SensorResult:
        """
        Scripted log reads.

        ``serves_logs`` defaults to False because that is the behaviour of the
        base sensor and of every open endpoint A01 currently runs on: blocks
        are served, ``eth_getLogs`` is refused.
        """
        if not self.serves_logs:
            return SensorResult(
                determined=False,
                chain=self._chain,
                method="logs",
                outcome="all_endpoints_failed",
                reason="scripted log refusal",
            )
        return SensorResult(
            determined=True,
            record=self._record(RecordKind.LOGS, from_height, []),
            chain=self._chain,
            method="logs",
        )

    def block(self, height: int, *, include_transactions: bool = False) -> SensorResult:
        self.reads.append(height)
        payload = self.blocks.get(height)
        if payload is None:
            return SensorResult(
                determined=True,
                record=None,
                chain=self._chain,
                method="block",
                reason=f"block {height} not present",
            )
        return SensorResult(
            determined=True,
            record=self._record(RecordKind.BLOCK, height, payload),
            chain=self._chain,
            method="block",
        )


def poller_over(sensor: FakeChain, **kwargs) -> BlockPoller:
    """A poller with an in-memory store, starting at height 0 unless told otherwise."""
    kwargs.setdefault("start_height", 0)
    kwargs.setdefault("checkpoints", InMemoryCheckpointStore())
    return BlockPoller(sensor, **kwargs)


# ==============================================================================
# LINKAGE
# ==============================================================================

def test_linkage_reads_the_three_fields_that_establish_a_chain():
    ref = block_ref_from_payload(evm_block(100))
    assert ref.number == 100
    assert ref.hash == "0x" + "a" + "000100"
    assert ref.parent_hash == "0xa000099"


def test_absent_parent_hash_is_refused_above_genesis():
    """
    Defaulting the parent to 0x0 would fabricate linkage to a genesis that is
    not there, and the tracker would report a clean extension across a break.
    """
    payload = evm_block(100)
    del payload["parentHash"]
    with pytest.raises(LinkageError):
        block_ref_from_payload(payload)


def test_genesis_may_have_no_parent():
    ref = block_ref_from_payload({"number": "0x0", "hash": "0xgenesis"})
    assert ref.number == 0


def test_unreadable_number_is_refused_not_treated_as_zero():
    with pytest.raises(LinkageError):
        block_ref_from_payload({"number": "junk", "hash": "0xa", "parentHash": "0xb"})


def test_has_linkage_does_not_raise():
    assert has_linkage(evm_block(1))
    assert not has_linkage({"number": "0x1"})
    assert not has_linkage("not an object")


# ==============================================================================
# CHECKPOINTS
# ==============================================================================

def test_checkpoint_requires_a_hash_not_just_a_height():
    """
    Height alone is unsafe across a reorg: resuming at 500 after the chain
    reorganised below 500 continues on withdrawn blocks, and nothing in the
    resumed run can detect it.
    """
    with pytest.raises(ValueError):
        Checkpoint(chain="ethereum", height=500, block_hash="")


def test_checkpoint_refuses_to_move_backwards_silently():
    store = InMemoryCheckpointStore()
    store.advance(Checkpoint(chain="ethereum", height=100, block_hash="0xa"))

    with pytest.raises(CheckpointError):
        store.advance(Checkpoint(chain="ethereum", height=90, block_hash="0xb"))


def test_rewind_is_the_explicit_way_backwards():
    store = InMemoryCheckpointStore()
    store.advance(Checkpoint(chain="ethereum", height=100, block_hash="0xa"))

    store.rewind("ethereum", 90, "0xb")

    assert store.load("ethereum").height == 90


def test_file_store_round_trips(tmp_path):
    store = FileCheckpointStore(tmp_path / "checkpoints.json")
    store.advance(Checkpoint(chain="ethereum", height=42, block_hash="0xa"))

    reopened = FileCheckpointStore(tmp_path / "checkpoints.json")
    loaded = reopened.load("ethereum")

    assert loaded is not None
    assert loaded.height == 42
    assert loaded.block_hash == "0xa"


def test_corrupt_checkpoint_file_is_refused_not_reset(tmp_path):
    """
    Resetting to zero re-ingests history; resetting to a default leaves a hole
    nobody knows about. An operator told the file is unreadable can fix it.
    """
    path = tmp_path / "checkpoints.json"
    path.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(CheckpointError):
        FileCheckpointStore(path).load("ethereum")


def test_checkpoint_file_from_a_future_version_is_refused(tmp_path):
    path = tmp_path / "checkpoints.json"
    path.write_text('{"version": 99, "chains": {}}', encoding="utf-8")

    with pytest.raises(CheckpointError):
        FileCheckpointStore(path).load("ethereum")


# ==============================================================================
# DEDUP
# ==============================================================================

def record_at(height: int, tag: str = "a") -> RawRecord:
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        payload=evm_block(height, tag),
        height=height,
        provenance=Provenance("fake", "ethereum", "scripted", "ok"),
    )


def test_duplicate_is_recognised_by_content():
    seen = SeenSet()
    seen.add(record_at(1))

    assert seen.check(record_at(1)).state is Seen.DUPLICATE


def test_eviction_makes_absence_stop_proving_novelty():
    """
    A bounded window can forget. Reporting a forgotten record as NEW would let
    a caller conclude it had never been stored.
    """
    seen = SeenSet(window=2)
    for height in range(4):
        seen.add(record_at(height))

    assert seen.check(record_at(0)).state is Seen.UNKNOWN
    assert seen.snapshot()["lossy"]


def test_unknown_records_are_processed_not_skipped():
    """
    Re-processing costs one rejected write. Skipping loses the record forever
    and nothing later notices.
    """
    seen = SeenSet(window=1)
    seen.add(record_at(0))
    seen.add(record_at(1))

    assert seen.check(record_at(0)).should_process


def test_forget_lets_a_withdrawn_block_be_reingested():
    seen = SeenSet()
    record = record_at(5)
    seen.add(record)
    seen.forget(record)

    assert seen.check(record).should_process


# ==============================================================================
# QUEUE
# ==============================================================================

def test_full_queue_rejects_by_default_so_nothing_is_lost():
    queue: RecordQueue[int] = RecordQueue(capacity=1)
    assert queue.put(1).accepted
    assert not queue.put(2).accepted
    assert list(queue) == [1]


def test_drop_oldest_loses_history_and_says_so():
    queue: RecordQueue[int] = RecordQueue(capacity=2, on_overflow=Overflow.DROP_OLDEST)
    queue.put(1)
    queue.put(2)
    result = queue.put(3)

    assert result.accepted
    assert result.dropped == 1
    assert list(queue) == [2, 3]


def test_high_water_survives_draining():
    """After an incident the useful question is how full it got, not how full it is."""
    queue: RecordQueue[int] = RecordQueue(capacity=10)
    for value in range(5):
        queue.put(value)
    queue.drain()

    assert len(queue) == 0
    assert queue.high_water == 5


# ==============================================================================
# POLLING
# ==============================================================================

def test_poller_walks_the_chain_in_order():
    sensor = FakeChain()
    sensor.extend(4)
    poller = poller_over(sensor)

    results = poller.run(max_steps=10)
    advanced = [r.height for r in results if r.status is PollStatus.ADVANCED]

    assert advanced == [0, 1, 2, 3, 4]
    assert len(poller.queue) == 5


def test_confirmation_lag_keeps_the_tip_uningested():
    """
    The tip is the least settled part of the chain. Ingesting it means
    recording what is most likely to be withdrawn.
    """
    sensor = FakeChain(confirmations=2)
    sensor.extend(10)
    poller = poller_over(sensor)

    poller.run(max_steps=20)
    highest = max(r.height for r in poller.run(max_steps=1) if r.height is not None)

    assert poller.checkpoint.height == 8, "should stop 2 blocks below head 10"
    assert highest <= 10


def test_caught_up_is_not_an_error():
    sensor = FakeChain()
    sensor.extend(1)
    poller = poller_over(sensor)
    poller.run(max_steps=5)

    result = poller.poll_once()

    assert result.status is PollStatus.CAUGHT_UP
    assert not result.should_retry


def test_unreadable_head_does_not_advance_anything():
    sensor = FakeChain()
    sensor.extend(3)
    sensor.head_fails = True
    poller = poller_over(sensor)

    result = poller.poll_once()

    assert result.status is PollStatus.UNDETERMINED
    assert poller.checkpoint is None
    assert not sensor.reads, "a failed head read must not trigger a block fetch"


def test_missing_block_is_not_yet_rather_than_a_failure():
    sensor = FakeChain()
    sensor.extend(3)
    del sensor.blocks[2]
    poller = poller_over(sensor)

    results = poller.run(max_steps=6)

    assert results[-1].status is PollStatus.NOT_YET
    assert poller.checkpoint.height == 1


def test_malformed_block_is_reported_not_stored():
    sensor = FakeChain()
    sensor.extend(2)
    sensor.blocks[1] = {"number": "0x1", "hash": "0xa000001"}  # no parentHash
    poller = poller_over(sensor)

    results = poller.run(max_steps=5)

    assert any(r.status is PollStatus.MALFORMED for r in results)
    assert len(poller.queue) == 1, "only block 0 should have been queued"


def test_backpressure_stops_fetching_rather_than_dropping():
    sensor = FakeChain()
    sensor.extend(5)
    poller = poller_over(sensor, queue=RecordQueue(capacity=2))

    results = poller.run(max_steps=10)

    assert results[-1].status is PollStatus.BACKPRESSURE
    assert len(sensor.reads) == 2, "must not spend requests it cannot hand off"


def test_restart_resumes_from_the_checkpoint():
    """Resumability is the whole point of the checkpoint; verify across instances."""
    store = InMemoryCheckpointStore()
    sensor = FakeChain()
    sensor.extend(4)

    first = BlockPoller(sensor, checkpoints=store, start_height=0)
    first.run(max_steps=3)
    stopped_at = first.checkpoint.height

    second = BlockPoller(sensor, checkpoints=store, start_height=0)
    second.run(max_steps=10)

    assert second.queue.peek().height == stopped_at + 1
    assert second.checkpoint.height == 4


# ==============================================================================
# CAPTURE GAPS
# ==============================================================================

def test_a_block_whose_logs_were_refused_says_so():
    """
    The regression. Free endpoints serve blocks and refuse `eth_getLogs`, and
    before this the block was stored looking whole: no transfers, nothing to
    distinguish it from a block that emitted none. A window of those licensed
    "no transfers for this address" from a fetch that never happened.
    """
    sensor = FakeChain()
    sensor.extend(2)
    sensor.serves_logs = False
    poller = poller_over(sensor, include_logs=True)

    poller.run(max_steps=4)

    blocks = [r for r in poller.queue if r.kind is RecordKind.BLOCK]
    assert blocks, "the blocks themselves must still be captured"
    assert all(CaptureGap.LOGS in record.capture_gaps for record in blocks)
    assert poller.stats.logs_undetermined == len(blocks)


def test_a_block_whose_logs_arrived_carries_no_gap():
    """
    The other direction. A gap that is always set is the same as no gap at all
    -- it would cap every window at "cannot support an absence" forever.
    """
    sensor = FakeChain()
    sensor.extend(2)
    sensor.serves_logs = True
    poller = poller_over(sensor, include_logs=True)

    poller.run(max_steps=4)

    blocks = [r for r in poller.queue if r.kind is RecordKind.BLOCK]
    assert blocks
    assert all(record.capture_gaps == () for record in blocks)
    assert poller.stats.logs_undetermined == 0
    assert poller.stats.logs_captured == len(blocks)


def test_a_block_captured_without_logs_requested_carries_no_gap():
    """
    A caller that never asked for logs has no shortfall. Marking one would
    report a gap against a capture that was exactly what it intended to be.
    """
    sensor = FakeChain()
    sensor.extend(2)
    poller = poller_over(sensor, include_logs=False)

    poller.run(max_steps=4)

    blocks = [r for r in poller.queue if r.kind is RecordKind.BLOCK]
    assert blocks
    assert all(record.capture_gaps == () for record in blocks)


def test_a_capture_gap_does_not_change_the_record_identity():
    """
    ``record_id`` hashes the payload alone. Two captures of one block are the
    same observation whether or not one of them also got that block's logs, and
    folding the gap into the identity would break the dedup the record exists
    to provide.
    """
    refused = FakeChain()
    refused.extend(0)
    refused.serves_logs = False
    served = FakeChain()
    served.extend(0)
    served.serves_logs = True

    a = poller_over(refused, include_logs=True)
    b = poller_over(served, include_logs=True)
    a.run(max_steps=2)
    b.run(max_steps=2)

    first = next(r for r in a.queue if r.kind is RecordKind.BLOCK)
    second = next(r for r in b.queue if r.kind is RecordKind.BLOCK)

    assert first.capture_gaps != second.capture_gaps
    assert first.record_id == second.record_id


# ==============================================================================
# REORGS
# ==============================================================================

def test_shallow_reorg_delivers_the_replacing_block_immediately():
    """
    The replacing block must reach the queue in the reorg step itself. The
    tracker adopts it as the new tip, so a later poll of that height reads as a
    duplicate and skips it -- and the height stays withdrawn from storage with
    nothing to refill it.
    """
    sensor = FakeChain()
    sensor.extend(4)
    poller = poller_over(sensor)
    poller.run(max_steps=10)
    poller.queue.drain()

    # Height 4 alone is replaced; the new block hangs off the recorded 3.
    sensor.fork_from(4, 4, tag="b")
    poller._checkpoints.rewind("ethereum", 3, sensor.blocks[3]["hash"])

    result = poller.poll_once()

    assert result.status is PollStatus.REORG
    assert result.withdrawn == (4,)
    assert result.record is not None, "the replacement must be handed off here"
    assert result.record.payload["hash"] == "0xb000004"
    assert poller.checkpoint.height == 4


def test_deep_reorg_rewalks_the_branch_instead_of_skipping_heights():
    """
    When the replacing block sits above the fork point, the heights between
    them exist only on the new branch and have never been read. Adopting it as
    the tip would make the next arrival look like ordinary progress, and those
    heights would never be asked for again.
    """
    sensor = FakeChain()
    sensor.extend(5)
    poller = poller_over(sensor)
    poller.run(max_steps=10)
    poller.queue.drain()
    assert poller.checkpoint.height == 5

    # Heights 5 and 6 are replaced by a branch forking at 4, and the poller
    # meets it at 6 -- so height 5 on the new branch has never been seen.
    sensor.fork_from(5, 6, tag="b")
    poller._checkpoints.rewind("ethereum", 5, sensor.blocks[5]["hash"])

    reorg = poller.poll_once()

    assert reorg.status is PollStatus.REORG
    assert reorg.record is None, "an out-of-order block must not be taken"
    assert poller.checkpoint.height == 4, "position returns to the fork point"

    poller.run(max_steps=5)
    delivered = [record.height for record in poller.queue]

    assert delivered == [5, 6], "the new branch must be walked, not jumped over"


def test_reorg_below_finality_stops_the_loop():
    """
    On a deterministic chain this cannot legitimately happen, so it means a
    provider is wrong about which network it is on. Rolling back finalized
    history on that word would let one endpoint rewrite A01's record.
    """
    sensor = FakeChain(finalized=4)
    sensor.extend(5)
    poller = poller_over(sensor)
    poller.run(max_steps=10)

    sensor.fork_from(3, 6, tag="b")
    poller._checkpoints.rewind("ethereum", 2, sensor.blocks[2]["hash"])

    with pytest.raises(FinalityViolationError) as excinfo:
        poller.run(max_steps=5)

    assert excinfo.value.chain == "ethereum"


def test_reorg_forking_below_the_window_refuses_to_guess():
    """
    An unknown fork point cannot be rewound to. A wrong guess leaves a hole in
    history that nothing afterwards detects.
    """
    tracker = ChainTracker("ethereum", window=2)
    sensor = FakeChain()
    sensor.extend(5)
    poller = poller_over(sensor, tracker=tracker)
    poller.run(max_steps=10)

    # Fork at a height the two-block window has already evicted.
    sensor.fork_from(1, 6, tag="b")
    poller._checkpoints.rewind("ethereum", 0, sensor.blocks[0]["hash"])

    with pytest.raises(IngestionError):
        poller.run(max_steps=5)


def test_withdrawn_blocks_can_be_reingested_at_the_same_height():
    """
    A stale dedup entry would make the replacement block look like a duplicate
    of the block it replaces, leaving the height permanently empty.
    """
    sensor = FakeChain()
    sensor.extend(3)
    poller = poller_over(sensor)
    poller.run(max_steps=10)
    poller.queue.drain()

    sensor.fork_from(3, 4, tag="b")
    poller._checkpoints.rewind("ethereum", 2, sensor.blocks[2]["hash"])
    poller.poll_once()

    results = poller.run(max_steps=5)
    statuses = {r.status for r in results}

    assert PollStatus.ADVANCED in statuses
    assert PollStatus.DUPLICATE not in statuses


def test_duplicate_delivery_is_absorbed():
    sensor = FakeChain()
    sensor.extend(2)
    tracker = ChainTracker("ethereum")
    poller = poller_over(sensor, tracker=tracker)
    poller.run(max_steps=5)

    # Re-observe a block the tracker already holds.
    tracker.observe(BlockRef(**{k: v for k, v in [
        ("number", 1),
        ("hash", sensor.blocks[1]["hash"]),
        ("parent_hash", sensor.blocks[1]["parentHash"]),
    ]}))

    assert poller.stats.reorgs == 0


# ==============================================================================
# BACKFILL
# ==============================================================================

def test_backfilled_blocks_whose_logs_were_refused_say_so():
    """
    The same defect, on the more dangerous path.

    A historical range is what a deep coverage window is actually built from,
    and this path had no log handling at all — every block it captured was
    stored looking whole whether or not its transfers had ever been fetched.
    """
    sensor = FakeChain()
    sensor.extend(4)
    sensor.serves_logs = False
    queue: RecordQueue = RecordQueue(capacity=16)
    job = Backfill(sensor, 0, 2, queue=queue, include_logs=True)

    progress = job.run()

    blocks = [r for r in queue if r.kind is RecordKind.BLOCK]
    assert len(blocks) == 3, "the blocks themselves must still be captured"
    assert all(CaptureGap.LOGS in record.capture_gaps for record in blocks)
    assert progress.logs_undetermined == 3


def test_backfilled_blocks_whose_logs_arrived_carry_no_gap():
    sensor = FakeChain()
    sensor.extend(4)
    sensor.serves_logs = True
    queue: RecordQueue = RecordQueue(capacity=16)
    job = Backfill(sensor, 0, 2, queue=queue, include_logs=True)

    progress = job.run()

    blocks = [r for r in queue if r.kind is RecordKind.BLOCK]
    assert len(blocks) == 3
    assert all(record.capture_gaps == () for record in blocks)
    assert progress.logs_captured == 3
    assert progress.logs_undetermined == 0


def test_a_backfill_that_never_asked_for_logs_marks_no_gap():
    sensor = FakeChain()
    sensor.extend(4)
    queue: RecordQueue = RecordQueue(capacity=16)
    job = Backfill(sensor, 0, 2, queue=queue)

    job.run()

    blocks = [r for r in queue if r.kind is RecordKind.BLOCK]
    assert all(record.capture_gaps == () for record in blocks)


def test_backfill_walks_a_bounded_range():
    sensor = FakeChain()
    sensor.extend(20)
    backfill = Backfill(sensor, 5, 9)

    progress = backfill.run()

    assert progress.complete
    assert progress.captured == 5
    assert sensor.reads == [5, 6, 7, 8, 9]


def test_backfill_records_missing_heights_instead_of_aborting():
    """
    A 50,000-block run that aborts on the first miss wastes everything before
    it; recording the gaps turns the retry into a much smaller second pass.
    """
    sensor = FakeChain()
    sensor.extend(10)
    del sensor.blocks[7]
    backfill = Backfill(sensor, 5, 9)

    progress = backfill.run()

    assert progress.complete
    assert progress.missing == [7]
    assert progress.captured == 4


def test_retry_missing_reattempts_only_the_gaps():
    sensor = FakeChain()
    sensor.extend(10)
    missing_payload = sensor.blocks.pop(7)
    backfill = Backfill(sensor, 5, 9)
    backfill.run()

    sensor.blocks[7] = missing_payload
    sensor.reads.clear()
    progress = backfill.retry_missing()

    assert sensor.reads == [7]
    assert progress.missing == []
    assert progress.captured == 5


def test_backfill_resumes_from_a_recorded_cursor():
    sensor = FakeChain()
    sensor.extend(20)
    backfill = Backfill(sensor, 0, 9)
    backfill.run(batch=4)
    cursor = backfill.progress.cursor

    resumed = Backfill(sensor, 0, 9)
    resumed.resume_at(cursor)
    resumed.run()

    assert resumed.progress.complete
    assert cursor == 4


def test_backfill_refuses_an_inverted_range():
    sensor = FakeChain()
    with pytest.raises(IngestionError):
        Backfill(sensor, 10, 5)


def test_backfill_refuses_a_resume_outside_its_range():
    """Clamping would make an off-by-one look like a successful resume."""
    sensor = FakeChain()
    backfill = Backfill(sensor, 10, 20)
    with pytest.raises(IngestionError):
        backfill.resume_at(5)


def test_backfill_pauses_on_backpressure():
    sensor = FakeChain()
    sensor.extend(20)
    backfill = Backfill(sensor, 0, 9, queue=RecordQueue(capacity=3))

    backfill.run()

    assert not backfill.complete
    assert len(sensor.reads) == 3


def test_backfill_does_not_disturb_a_live_checkpoint():
    """
    Writing backfill progress into the poller's checkpoint would move the live
    position backwards and re-ingest the present.
    """
    store = InMemoryCheckpointStore()
    sensor = FakeChain()
    sensor.extend(20)

    poller = BlockPoller(sensor, checkpoints=store, start_height=15)
    poller.run(max_steps=5)
    live = store.load("ethereum").height

    Backfill(sensor, 0, 5).run()

    assert store.load("ethereum").height == live


# ==============================================================================
# HEALTH
# ==============================================================================

def test_poller_health_reports_position_and_pressure():
    sensor = FakeChain()
    sensor.extend(3)
    poller = poller_over(sensor)
    poller.run(max_steps=5)

    health = poller.health()

    assert health["chain"] == "ethereum"
    assert health["checkpoint"]["height"] == 3
    assert health["queue"]["depth"] == 4
    assert health["stats"]["advanced"] == 4
