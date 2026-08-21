"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.writer

Purpose:
    Drain captured records out of the ingestion queue, through normalization,
    into the system of record.

Design goals:
    - Only validated data written, per DR-08
    - Rejections retained, not dropped, so a bad provider is visible
    - Withdrawals applied before the replacing block is stored
    - Batch-oriented, because per-row commits pace ingestion at fsync speed
    - Counters for every outcome, including the ones that are not failures

Notes:
    This is the component that closes the pipeline. Everything before it moves
    data; this is where data stops being in flight and becomes A01's record.

    Ordering is the part that has to be right. A reorg result carries both the
    heights to withdraw and the block that replaced them, and the withdrawal has
    to be applied first. The other order leaves a moment where two blocks at the
    same height are both marked canonical, and any read landing in that moment
    sees a chain that forked and never rejoined -- which is not a state the chain
    was ever in.

    Rejected records are kept rather than discarded. A provider that starts
    serving malformed payloads produces a rising rejection count, and that count
    is the only signal distinguishing it from a chain that went quiet. Dropping
    rejections silently makes the two identical.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

from ingestion.events import PollResult, PollStatus
from ingestion.linkage import LinkageError, block_ref_from_record
from ingestion.queue import RecordQueue
from normalization.approvals import normalize_approvals
from normalization.normalizer import NormalizationResult, Normalizer
from sensors.envelope import RawRecord

from .approvals import SqliteApprovalRepository
from .repositories import BlockRepository
from .tokens import SqliteTokenRepository

logger = logging.getLogger(__name__)

#: Records normalized and written per :meth:`RecordWriter.drain` call. Batched
#: because each transaction costs a commit, and committing per block turns
#: ingestion throughput into a function of disk flush latency.
DEFAULT_BATCH = 64


@dataclass(slots=True)
class WriterStats:
    """Counters for doctor and for spotting a provider gone bad."""

    drained: int = 0
    written: int = 0
    duplicates: int = 0
    rejected: int = 0
    incomplete: int = 0
    withdrawn_blocks: int = 0
    transactions_written: int = 0
    token_transfers_written: int = 0
    nft_transfers_written: int = 0
    #: Token records whose block is not stored. Counted rather than raised:
    #: logs can arrive for a block ingestion has not reached, and a persistent
    #: count is the signal that block and log capture have drifted apart.
    orphaned_token_records: int = 0
    #: Approval grants stored from the same log batches. Zero for a writer with
    #: no approval repository configured, which is every caller that has not
    #: opted into approval-risk capture.
    approvals_written: int = 0
    orphaned_approvals: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "drained": self.drained,
            "written": self.written,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "incomplete": self.incomplete,
            "withdrawn_blocks": self.withdrawn_blocks,
            "transactions_written": self.transactions_written,
            "token_transfers_written": self.token_transfers_written,
            "nft_transfers_written": self.nft_transfers_written,
            "orphaned_token_records": self.orphaned_token_records,
            "approvals_written": self.approvals_written,
            "orphaned_approvals": self.orphaned_approvals,
        }


@dataclass(frozen=True, slots=True)
class DrainReport:
    """
    Outcome of one drain pass.

    ``rejections`` carries the failed results rather than a count, so a caller
    can log which field of which provider's payload was wrong. A count alone
    tells an operator that something is broken but not what.
    """

    drained: int
    written: int
    duplicates: int
    rejections: tuple[NormalizationResult, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.rejections

    def as_dict(self) -> dict[str, Any]:
        return {
            "drained": self.drained,
            "written": self.written,
            "duplicates": self.duplicates,
            "rejections": [r.as_dict() for r in self.rejections],
        }


class RecordWriter:
    """
    The consumer at the end of the ingestion pipeline.

    Owns neither the queue nor the repository, so the same writer serves an
    in-memory test database and a live file without changing a line of the
    path that decides what gets written.
    """

    def __init__(
        self,
        repository: BlockRepository,
        *,
        normalizer: Normalizer | None = None,
        tokens: SqliteTokenRepository | None = None,
        approvals: SqliteApprovalRepository | None = None,
    ) -> None:
        self._repository = repository
        self._normalizer = normalizer if normalizer is not None else Normalizer()
        # Optional: a caller ingesting blocks only has no use for it, and
        # requiring one would make the token schema a dependency of every
        # write path rather than of the token write path.
        self._tokens = tokens
        # Optional in the same way, and off by default: approval capture is a
        # screen an operator opts into, not a cost every ingestion run pays.
        # A writer with no approval repository captures approvals nowhere and
        # behaves exactly as it did before the schema existed.
        self._approvals = approvals
        self.stats = WriterStats()

    @property
    def normalizer(self) -> Normalizer:
        return self._normalizer

    @property
    def repository(self) -> BlockRepository:
        return self._repository

    @property
    def tokens(self) -> SqliteTokenRepository | None:
        return self._tokens

    @property
    def approvals(self) -> SqliteApprovalRepository | None:
        return self._approvals

    # -- writing ----------------------------------------------------------

    def write(self, record: RawRecord) -> NormalizationResult:
        """
        Normalize and store one record.

        Returns the normalization result whether or not it was stored, so a
        caller always learns why nothing was written.
        """
        result = self._normalizer.normalize(record)

        if result.is_token_activity:
            # Approvals ride in the same log batch as transfers. They are
            # decoded from the raw record here rather than through the token
            # normalizer, which refuses them as non-transfers on purpose -- an
            # approval in flow analysis inflates every total it touches.
            self._write_approvals(record)
            return self._write_tokens(result)

        if not result.storable or result.block is None:
            self.stats.rejected += 1
            return result

        outcome = self._repository.save(
            result.block,
            complete=result.quality.complete,
            plausible=result.quality.plausible,
            # No floor on this path: it stores whatever the capture obtained, so
            # anything missing is missing because a fetch failed.
            incomplete_reason=result.quality.incomplete_reason,
        )

        if outcome.inserted:
            self.stats.written += 1
            self.stats.transactions_written += outcome.transactions_written
        else:
            # Already stored. The durable half of idempotency, which the
            # in-memory dedup window cannot provide across a restart.
            self.stats.duplicates += 1

        if not result.quality.complete:
            self.stats.incomplete += 1

        return result

    def _write_tokens(self, result: NormalizationResult) -> NormalizationResult:
        """
        Store one block's token movements.

        Silently dropping these when no token repository is configured would
        make a chain look free of token activity, so the absence is logged
        rather than assumed to be intentional every time.
        """
        activity = result.activity
        if activity is None or not result.storable:
            self.stats.rejected += 1
            return result

        if self._tokens is None:
            logger.debug(
                "%s: %d token record(s) discarded; no token repository configured",
                activity.chain,
                len(activity.transfers) + len(activity.nft_transfers),
            )
            return result

        outcome = self._tokens.save(activity)
        self.stats.token_transfers_written += outcome.transfers_written
        self.stats.nft_transfers_written += outcome.nfts_written
        self.stats.orphaned_token_records += outcome.orphaned
        return result

    def _write_approvals(self, record: RawRecord) -> None:
        """
        Store the approval grants carried in one log batch.

        A no-op unless an approval repository is configured, so a caller that
        has not opted into approval capture pays nothing and stores nothing.
        The grants are decoded straight from the raw record: they never entered
        the token activity, which excludes them by design.

        Failures to file are counted, not raised. An approval whose block is
        not yet stored is orphaned exactly as a token record is, and the same
        counter distinguishes a transient ordering gap from a persistent drift
        between block and log capture.
        """
        if self._approvals is None:
            return

        activity, _issues = normalize_approvals(
            record.payload,
            chain=record.chain,
            source_record_id=record.record_id,
        )
        if activity is None or activity.empty:
            return

        outcome = self._approvals.save(activity)
        self.stats.approvals_written += outcome.written
        self.stats.orphaned_approvals += outcome.orphaned

    def drain(
        self, queue: RecordQueue[RawRecord], *, batch: int = DEFAULT_BATCH
    ) -> DrainReport:
        """Take up to ``batch`` records from the queue and store them."""
        if batch <= 0:
            raise ValueError("batch must be > 0")

        records = queue.drain(limit=batch)
        if not records:
            return DrainReport(drained=0, written=0, duplicates=0)

        before_written = self.stats.written
        before_duplicates = self.stats.duplicates
        rejections: list[NormalizationResult] = []

        for record in records:
            result = self.write(record)
            if not result.storable:
                rejections.append(result)

        self.stats.drained += len(records)

        if rejections:
            logger.warning(
                "%d of %d record(s) rejected before storage", len(rejections), len(records)
            )

        return DrainReport(
            drained=len(records),
            written=self.stats.written - before_written,
            duplicates=self.stats.duplicates - before_duplicates,
            rejections=tuple(rejections),
        )

    # -- reorg ------------------------------------------------------------

    def apply(
        self,
        result: PollResult,
        *,
        queue: RecordQueue[RawRecord] | None = None,
    ) -> int:
        """
        Apply a reorg result's withdrawal. Returns rows withdrawn.

        Two things happen, in this order, and both are necessary:

        1. **Purge the queue.** Records captured on the abandoned branch may
           still be buffered, unwritten. The withdrawal below cannot reach them
           because they are not rows yet, so draining afterwards would insert
           abandoned blocks marked canonical, with nothing to show they are
           stale.
        2. **Withdraw the stored rows.** Only after the queue is clean, so no
           later drain can reintroduce what was just withdrawn.

        The purge matches on **block hash, not height**. Height is the obvious
        discriminator and it is wrong: after a shallow reorg the replacing block
        sits at a withdrawn height too, so a height filter throws away the very
        record that was supposed to take its place -- and the checkpoint has
        already advanced past it, so nothing re-fetches it and the height stays
        permanently empty. The orphaned hashes name the abandoned branch
        exactly.

        The replacing block is deliberately *not* written here. It is in the
        queue like any other capture, and :meth:`drain` stores it -- after this
        method has removed everything the reorg invalidated.
        """
        if not result.withdrawn:
            return 0

        if queue is not None:
            self._purge(result, queue)

        affected = self._repository.withdraw(result.chain, result.withdrawn)
        self.stats.withdrawn_blocks += affected
        return affected

    def _purge(self, result: PollResult, queue: RecordQueue[RawRecord]) -> int:
        """Drop buffered captures belonging to the abandoned branch."""
        if result.reorg is None:
            # Without the event the abandoned captures cannot be told apart
            # from the replacement, and dropping the replacement leaves a hole
            # the checkpoint has already moved past. Refusing to guess leaves a
            # recoverable duplicate instead of an unrecoverable gap.
            logger.warning(
                "%s: reorg result carries no event; queued captures cannot be "
                "purged safely and may be stale",
                result.chain,
            )
            return 0

        orphaned = {orphan.hash.lower() for orphan in result.reorg.orphaned}
        if not orphaned:
            return 0

        chain = result.chain

        def is_abandoned(record: RawRecord) -> bool:
            if record.chain != chain:
                return False
            try:
                return block_ref_from_record(record).hash.lower() in orphaned
            except LinkageError:
                # A record with no readable linkage cannot be matched, and
                # dropping it on suspicion would discard a good capture.
                # Normalization will reject it on its own merits.
                return False

        purged = queue.discard(is_abandoned)
        if purged:
            logger.warning(
                "%s: dropped %d queued capture(s) from the abandoned branch",
                chain,
                purged,
            )
        return purged

    def consume(
        self,
        results: list[PollResult],
        queue: RecordQueue[RawRecord],
        *,
        batch: int = DEFAULT_BATCH,
    ) -> DrainReport:
        """
        Apply a poll run end to end: withdrawals first, then the queue.

        The single entry point a caller should use after
        :meth:`ingestion.poller.BlockPoller.run`. Doing the two steps in the
        other order stores the replacing block while the block it replaced is
        still canonical at the same height, and a read landing in that window
        sees a chain that forked and never rejoined.

        ``batch`` sizes the *commit*, not the run. Draining once and returning
        was silent data loss: the poller advances the checkpoint when a record
        is queued, so anything left in the queue when the process exits is
        checkpointed as done and never fetched again. A 100-block run with
        tokens queues 200 records, a single 64-record drain stored 32 blocks,
        and heights 33-100 became a permanent hole in a window that still
        reported itself contiguous.
        """
        for result in results:
            if result.status is PollStatus.REORG:
                self.apply(result, queue=queue)

        drained = written = duplicates = 0
        rejections: list[NormalizationResult] = []

        while True:
            report = self.drain(queue, batch=batch)
            if not report.drained:
                break
            drained += report.drained
            written += report.written
            duplicates += report.duplicates
            rejections.extend(report.rejections)

        return DrainReport(
            drained=drained,
            written=written,
            duplicates=duplicates,
            rejections=tuple(rejections),
        )

    # -- reporting --------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "writer": self.stats.as_dict(),
            "normalizer": self._normalizer.stats.as_dict(),
        }

    def __repr__(self) -> str:
        return f"RecordWriter(written={self.stats.written}, rejected={self.stats.rejected})"


__all__ = ["DEFAULT_BATCH", "DrainReport", "RecordWriter", "WriterStats"]
