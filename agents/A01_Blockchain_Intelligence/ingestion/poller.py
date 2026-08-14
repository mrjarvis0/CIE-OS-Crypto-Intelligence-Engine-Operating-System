"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.poller

Purpose:
    Follow one chain's head, block by block, surviving reorgs, gaps, duplicate
    deliveries and restarts.

Design goals:
    - Stepped, not looping: one call processes at most one block
    - Confirmation lag applied, so the tip is never treated as settled
    - Reorgs detected through parent linkage and applied deliberately
    - Finality violations stop the loop instead of rewriting history
    - Checkpoint advanced only after a block is fully handed off
    - No sleeping, no threads; pacing belongs to the caller

Notes:
    ``poll_once`` is a step function rather than a loop because every
    interesting condition in blockchain ingestion is a transition, and
    transitions inside a ``while True`` are only observable through logs. A
    stepped driver lets the reorg case, the gap case, and the provider-behind
    case each be played through in a test with a scripted block sequence, which
    is the only way any of them are testable at all -- a real reorg cannot be
    scheduled.

    Blocks are read at ``head - confirmations``, never at the head. The tip is
    the least settled part of the chain, and ingesting it means recording data
    that is most likely to be withdrawn. The lag comes from the chain registry
    so it is a property of the chain rather than a constant in this file.

    The checkpoint advances after the record is queued, not after it is
    fetched. Ordering them the other way makes a crash between the two lose the
    block silently: the next run resumes past a height that was never handed
    off, and nothing afterwards can tell.

    A reorg that crossed finality raises. It is the one condition here that is
    not a normal blockchain event: on a deterministic chain it cannot happen, so
    observing it means a provider is wrong about which network it is on. Rolling
    back finalized history on that basis would let one bad endpoint rewrite
    A01's record, so the loop stops and a human decides.
"""

from __future__ import annotations

import logging

from dataclasses import replace
from typing import Any

from blockchain.reorg import BlockRef, ChainTracker, Observation, ReorgEvent
from core.exceptions import IngestionError
from sensors.base import Sensor
from sensors.envelope import CaptureGap, RawRecord

from .checkpoint import Checkpoint, CheckpointStore, InMemoryCheckpointStore
from .dedup import SeenSet
from .events import PollResult, PollerStats, PollStatus
from .linkage import LinkageError, block_ref_from_record
from .queue import RecordQueue
from .recovery import ReorgRecovery

logger = logging.getLogger(__name__)

#: Polls between finalized-head refreshes. The finalized tag moves every epoch,
#: not every block, so reading it per block spends requests to learn nothing --
#: and the request budget is the scarce resource on a free tier.
DEFAULT_FINALITY_EVERY = 32


class BlockPoller:
    """
    Drives one chain forward one block per step.

    Owns no transport and no storage. The sensor supplies blocks, the queue
    accepts them, the checkpoint store remembers the position; this class only
    decides what each arriving block means and what to do about it.
    """

    def __init__(
        self,
        sensor: Sensor,
        *,
        queue: RecordQueue[RawRecord] | None = None,
        checkpoints: CheckpointStore | None = None,
        tracker: ChainTracker | None = None,
        seen: SeenSet | None = None,
        confirmations: int | None = None,
        start_height: int | None = None,
        finality_every: int = DEFAULT_FINALITY_EVERY,
        include_transactions: bool = False,
        include_logs: bool = False,
    ) -> None:
        if finality_every <= 0:
            raise ValueError("finality_every must be > 0")
        if start_height is not None and start_height < 0:
            raise ValueError("start_height must be >= 0")

        self._sensor = sensor
        self._chain = sensor.chain
        self._queue: RecordQueue[RawRecord] = queue if queue is not None else RecordQueue()
        self._checkpoints = checkpoints if checkpoints is not None else InMemoryCheckpointStore()
        self._tracker = tracker if tracker is not None else ChainTracker(self._chain)
        self._seen = seen if seen is not None else SeenSet()
        self._finality_every = finality_every
        self._include_transactions = include_transactions
        self._include_logs = include_logs

        # The lag comes from the sensor when it can state one, because it is a
        # property of the chain rather than of this loop.
        if confirmations is not None:
            if confirmations < 0:
                raise ValueError("confirmations must be >= 0")
            self._confirmations = confirmations
        else:
            self._confirmations = int(getattr(sensor, "confirmations", 12))

        self._start_height = start_height
        self._head: int | None = None
        self._recovery = ReorgRecovery(self._chain, self._tracker, self._seen)

        self.stats = PollerStats()

    # -- accessors --------------------------------------------------------

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def queue(self) -> RecordQueue[RawRecord]:
        return self._queue

    @property
    def tracker(self) -> ChainTracker:
        return self._tracker

    @property
    def seen(self) -> SeenSet:
        return self._seen

    @property
    def confirmations(self) -> int:
        return self._confirmations

    @property
    def checkpoint(self) -> Checkpoint | None:
        return self._checkpoints.load(self._chain)

    @property
    def head(self) -> int | None:
        """Last head observed, or None before the first successful read."""
        return self._head

    def next_height(self) -> int | None:
        """
        The height this poller will attempt next.

        None means the start position is not yet known: with no checkpoint and
        no configured start, it depends on a head read that has not happened.
        """
        stored = self._checkpoints.load(self._chain)
        if stored is not None:
            return stored.next_height
        if self._start_height is not None:
            return self._start_height
        if self._head is None:
            return None
        return max(self._head - self._confirmations, 0)

    # -- stepping ---------------------------------------------------------

    def poll_once(self) -> PollResult:
        """Process at most one block. Never blocks, never sleeps."""
        self.stats.steps += 1

        head_result = self._sensor.head()
        if not head_result.ok:
            self.stats.undetermined += 1
            return PollResult(
                PollStatus.UNDETERMINED,
                self._chain,
                reason=head_result.reason or "head undetermined",
            )

        head = head_result.unwrap().height
        if head is None:  # pragma: no cover - sensor guarantees a height
            self.stats.malformed += 1
            return PollResult(
                PollStatus.MALFORMED, self._chain, reason="head record has no height"
            )
        self._head = head

        if self.stats.steps % self._finality_every == 1:
            self._refresh_finality()

        target = max(head - self._confirmations, 0)
        height = self.next_height()
        if height is None:  # pragma: no cover - head is set above
            height = target

        if height > target:
            return PollResult(
                PollStatus.CAUGHT_UP,
                self._chain,
                height=height,
                reason=(
                    f"next height {height} is within {self._confirmations} "
                    f"confirmations of head {head}"
                ),
            )

        # Refuse to fetch what cannot be handed off. Fetching anyway would burn
        # request budget and then drop the result.
        if self._queue.is_full:
            self.stats.backpressure += 1
            return PollResult(
                PollStatus.BACKPRESSURE,
                self._chain,
                height=height,
                reason=f"queue at capacity {self._queue.capacity}; consumer is behind",
            )

        return self._process_height(height)

    def run(self, max_steps: int = 100) -> list[PollResult]:
        """
        Step until caught up, undetermined, or ``max_steps`` is reached.

        Bounded on purpose. An unbounded catch-up loop on a chain millions of
        blocks behind is indistinguishable from a hang, and the caller cannot
        report progress or stop it. Use :class:`ingestion.backfill.Backfill`
        for deliberate historical ranges.
        """
        if max_steps <= 0:
            raise ValueError("max_steps must be > 0")

        results: list[PollResult] = []
        for _ in range(max_steps):
            result = self.poll_once()
            results.append(result)
            if not result.should_retry:
                break
        return results

    # -- block handling ---------------------------------------------------

    def _process_height(self, height: int) -> PollResult:
        """Fetch one height and classify what it means for the recorded chain."""
        read = self._sensor.block(height, include_transactions=self._include_transactions)

        if not read.determined:
            self.stats.undetermined += 1
            return PollResult(
                PollStatus.UNDETERMINED,
                self._chain,
                height=height,
                reason=read.reason or "block undetermined",
            )

        # Determined with no record: the height is not yet available at this
        # provider even though the head implied it. A wait, not a failure.
        if read.record is None:
            return PollResult(
                PollStatus.NOT_YET,
                self._chain,
                height=height,
                reason=read.reason or f"block {height} not present",
            )

        record = read.record
        try:
            ref = block_ref_from_record(record)
        except LinkageError as exc:
            self.stats.malformed += 1
            return PollResult(
                PollStatus.MALFORMED, self._chain, height=height, reason=str(exc)
            )

        observation = self._tracker.observe(ref)

        if observation.observation is Observation.REORG:
            return self._handle_reorg(observation.reorg, ref, record)

        if observation.observation is Observation.DUPLICATE:
            self.stats.duplicates += 1
            self._advance(height, ref)
            return PollResult(
                PollStatus.DUPLICATE, self._chain, height=height, record=record
            )

        if observation.observation is Observation.GAP:
            # Stepping one height at a time makes this unreachable in a healthy
            # run, so reaching it means the tracker and the checkpoint have
            # diverged. Guessing which is right would paper over a real bug.
            missing = observation.missing_range
            raise IngestionError(
                f"{self._chain}: gap at height {height}; tracker tip and "
                f"checkpoint disagree, heights {missing} were never observed",
                details={"chain": self._chain, "height": height, "missing": list(missing or ())},
            )

        seen = self._seen.check(record)
        if seen.is_duplicate:
            self.stats.duplicates += 1
            self._advance(height, ref)
            return PollResult(
                PollStatus.DUPLICATE, self._chain, height=height, record=record
            )

        # Logs are *read* before the block is queued and *queued* after it, and
        # both halves of that are load-bearing.
        #
        # Read first, because the outcome belongs on the block's own record. A
        # block stored without the logs it was asked for is otherwise
        # indistinguishable from a block that emitted none, and "no transfers
        # here" then gets asserted from a fetch that never happened.
        #
        # Queued after, because token transfers reference their block by
        # foreign key: a log batch reaching storage first would find no block
        # to attach to and every transfer in it would be dropped as orphaned.
        logs: RawRecord | None = None
        if self._include_logs:
            logs = self._read_logs(height)
            if logs is not None and len(self._queue) + 2 > self._queue.capacity:
                # Room for the block but not for its logs. Queueing the block
                # regardless would store it claiming completeness while the
                # logs already in hand are discarded -- so the batch is dropped
                # and the block says so, which is the recoverable failure.
                self.stats.logs_dropped += 1
                logger.warning(
                    "%s: logs for height %d dropped, queue full", self._chain, height
                )
                logs = None
            if logs is None:
                record = replace(
                    record, capture_gaps=(*record.capture_gaps, CaptureGap.LOGS)
                )

        put = self._queue.put(record)
        if not put.accepted:  # pragma: no cover - fullness checked before fetch
            self.stats.backpressure += 1
            return PollResult(
                PollStatus.BACKPRESSURE,
                self._chain,
                height=height,
                reason=put.reason,
            )

        if logs is not None:
            put_logs = self._queue.put(logs)
            if put_logs.accepted:
                self.stats.logs_captured += 1
            else:  # pragma: no cover - capacity checked above
                self.stats.logs_dropped += 1
                logger.warning(
                    "%s: logs for height %d dropped after the block was queued; "
                    "the block will be stored claiming completeness",
                    self._chain,
                    height,
                )

        # Committed only now: the record is queued, so recording the position
        # cannot skip a block that was never handed off.
        self._seen.add(record)
        self._advance(height, ref, record_id=record.record_id)
        self.stats.advanced += 1

        return PollResult(
            PollStatus.ADVANCED, self._chain, height=height, record=record
        )

    def _read_logs(self, height: int) -> RawRecord | None:
        """
        Fetch this height's event logs. ``None`` when they could not be had.

        Failure here is deliberately not fatal to the block. Log reads are the
        first thing a free provider rate-limits, and abandoning a good block
        because its logs were refused would stall ingestion on the least
        reliable call in the pipeline. The shortfall is counted instead, so a
        provider that never serves logs is visible rather than merely quiet.

        Returning rather than queueing is what lets the caller put the outcome
        on the block. The block is still worth storing; what it can no longer
        do is support a claim about what it did *not* contain.
        """
        read = self._sensor.logs(from_height=height, to_height=height)

        if not read.determined or read.record is None:
            self.stats.logs_undetermined += 1
            logger.debug(
                "%s: logs for height %d undetermined: %s",
                self._chain,
                height,
                read.reason,
            )
            return None

        return read.record

    def _handle_reorg(
        self, event: ReorgEvent | None, ref: BlockRef, record: RawRecord
    ) -> PollResult:
        """
        Repair recorded state, and take the replacing block when it is the next
        one.

        The decision and the state repair belong to
        :class:`ingestion.recovery.ReorgRecovery`, including the two conditions
        that refuse to recover at all. What stays here is the queueing and the
        checkpoint write, because their ordering is what decides whether a crash
        loses a block, and that ordering should be readable in one place.
        """
        plan = self._recovery.plan(event, ref)
        assert event is not None  # plan() raises when it is None

        withdrawn = self._recovery.apply(plan, event)
        self.stats.reorgs += 1
        self.stats.withdrawn_blocks += len(withdrawn)

        if not plan.contiguous:
            # The branch has to be re-walked from the fork point, so this block
            # is not taken: the heights below it have never been read.
            self._checkpoints.rewind(self._chain, plan.ancestor, plan.ancestor_hash)
            return PollResult(
                PollStatus.REORG,
                self._chain,
                height=ref.number,
                reorg=event,
                withdrawn=withdrawn,
                reason=(
                    f"depth {plan.depth} reorg forking at {plan.ancestor}; "
                    f"{len(withdrawn)} block(s) withdrawn, re-walking the new "
                    f"branch from {plan.resume_height}"
                ),
            )

        # A slot is guaranteed: poll_once refuses to fetch into a full queue,
        # so the replacing block cannot be stranded here.
        put = self._queue.put(record)
        if not put.accepted:  # pragma: no cover - capacity checked before fetch
            raise IngestionError(
                f"{self._chain}: reorg at {ref.number} could not be handed off; "
                "the orphaned segment would be withdrawn with no replacement",
                details={"chain": self._chain, "height": ref.number},
            )

        self._seen.add(record)
        self._recovery.remember(ref.number, record.record_id)

        # The position moves to the replacing block, not to the fork point:
        # everything above it was withdrawn, and this height is now processed.
        self._checkpoints.rewind(self._chain, ref.number, ref.hash)
        self.stats.advanced += 1

        return PollResult(
            PollStatus.REORG,
            self._chain,
            height=ref.number,
            record=record,
            reorg=event,
            withdrawn=withdrawn,
            reason=(
                f"depth {plan.depth} reorg forking at {plan.ancestor}; "
                f"{len(withdrawn)} block(s) withdrawn, {ref.number} replaced"
            ),
        )

    # -- bookkeeping ------------------------------------------------------

    def _advance(self, height: int, ref: BlockRef, record_id: str | None = None) -> None:
        """Record the new position and remember the id for reorg recovery."""
        stored = self._checkpoints.load(self._chain)
        if stored is None:
            checkpoint = Checkpoint(chain=self._chain, height=height, block_hash=ref.hash)
        else:
            checkpoint = stored.advanced_to(height, ref.hash)
        self._checkpoints.advance(checkpoint)

        if record_id is not None:
            self._recovery.remember(height, record_id)

    def _refresh_finality(self) -> None:
        """
        Read the finalized head, if the chain publishes one.

        A failure here is not fatal. Without a finalized height the tracker
        simply cannot classify a reorg as crossing finality, which makes it
        more permissive rather than wrong -- and on a free tier the tag is
        frequently unavailable.
        """
        result = self._sensor.finalized_head()
        if not result.ok:
            logger.debug("%s: finalized head unavailable: %s", self._chain, result.reason)
            return

        height = result.unwrap().height
        if height is not None:
            self._tracker.mark_finalized(height)

    # -- reporting --------------------------------------------------------

    def health(self) -> dict[str, Any]:
        stored = self._checkpoints.load(self._chain)
        tip = self._tracker.tip
        return {
            "chain": self._chain,
            "sensor": self._sensor.name,
            "head": self._head,
            "confirmations": self._confirmations,
            "next_height": self.next_height(),
            "checkpoint": stored.as_dict() if stored else None,
            "tracker_tip": tip.as_dict() if tip else None,
            "finalized_height": self._tracker.finalized_height,
            "reorgs_seen": self._tracker.reorgs_seen,
            "deepest_reorg": self._tracker.deepest_reorg,
            "queue": self._queue.snapshot(),
            "dedup": self._seen.snapshot(),
            "stats": self.stats.as_dict(),
        }

    def __repr__(self) -> str:
        return f"BlockPoller(chain={self._chain!r}, next={self.next_height()})"


# PollResult, PollStatus and PollerStats are re-exported from ``.events`` so
# that importing this module keeps working; they live there because a consumer
# reacting to results has no reason to import the loop that produces them.
__all__ = [
    "DEFAULT_FINALITY_EVERY",
    "BlockPoller",
    "PollResult",
    "PollStatus",
    "PollerStats",
]
