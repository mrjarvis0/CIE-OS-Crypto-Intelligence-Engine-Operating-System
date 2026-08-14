"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.writer

Purpose:
    Store a block the selective way: one aggregate row, plus only the
    transactions that cleared the materiality gate.

Design goals:
    - Same queue, same normalizer, same reorg handling as the full path
    - Aggregate and material transactions land in one transaction
    - The floor in force travels with every block
    - Counts describe the chain, never the filter
    - Drop-in for RecordWriter at the call site

Notes:
    This is the seam. Everything upstream of it -- sensors, the poller, reorg
    detection, normalization -- is unchanged and shared with the full path.
    What changes is that ``block.transactions`` is filtered before the block is
    handed to storage, and the figures the discarded rows would have answered
    are computed first.

    ``transaction_count`` is deliberately **not** rewritten to the material
    count. It is the chain's own figure, and lowering it to match what was kept
    would make a busy block look quiet -- the precise misreading the aggregate
    exists to prevent. The block row therefore says "334 transactions", stores
    two of them, and the quality report says which floor separated them.

    Both writers can run against the same database. Nothing here migrates or
    deletes what the full path already stored.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, replace
from typing import Any

from database.repositories import BlockRepository
from database.writer import RecordWriter
from normalization.normalizer import NormalizationResult
from normalization.quality import assess_block
from schemas.amount import Amount
from sensors.envelope import RawRecord
from tiers.hot import BlockAggregateRepository

from .aggregate import FilterStats, accumulate
from .materiality import MaterialityGate

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SelectiveStats:
    """
    What a selective run stored, and what it declined to.

    ``dropped`` is the number the redesign exists to make large. Reported
    rather than inferred, so an operator can see the compression actually being
    achieved instead of trusting that the gate is doing something.
    """

    blocks: int = 0
    aggregates_written: int = 0
    transactions_seen: int = 0
    transactions_kept: int = 0
    rejected: int = 0

    @property
    def dropped(self) -> int:
        return self.transactions_seen - self.transactions_kept

    @property
    def kept_share(self) -> float:
        return (
            self.transactions_kept / self.transactions_seen
            if self.transactions_seen
            else 0.0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks,
            "aggregates_written": self.aggregates_written,
            "transactions_seen": self.transactions_seen,
            "transactions_kept": self.transactions_kept,
            "dropped": self.dropped,
            "kept_share": round(self.kept_share, 6),
            "rejected": self.rejected,
        }


class SelectiveWriter:
    """
    Writes blocks through the materiality gate.

    Wraps a :class:`~database.writer.RecordWriter` rather than replacing it, so
    reorg withdrawal, idempotency and rejection reporting stay in one place.
    Only the decision about *which transactions reach storage* lives here.
    """

    def __init__(
        self,
        repository: BlockRepository,
        aggregates: BlockAggregateRepository,
        *,
        gate: MaterialityGate,
        writer: RecordWriter | None = None,
    ) -> None:
        self._repository = repository
        self._aggregates = aggregates
        self._gate = gate
        self._writer = writer if writer is not None else RecordWriter(repository)
        self.stats = SelectiveStats()
        self.filter_stats = FilterStats()

    @property
    def gate(self) -> MaterialityGate:
        return self._gate

    @property
    def normalizer(self):
        return self._writer.normalizer

    def retune(self, floor: Amount) -> None:
        """
        Raise or lower the floor mid-run.

        Used when a call budget tightens: keeping fewer transactions is a
        recoverable loss of resolution, and failing the capture is not. Every
        block records the floor that was in force for it, so the change is
        visible afterwards rather than inferred.
        """
        self._gate = self._gate.with_floor(floor)

    def write(self, record: RawRecord) -> NormalizationResult:
        """
        Normalize one record, filter it, and store what survives.

        Token and log records pass straight through to the wrapped writer: they
        are already the selective half of the capture, and a second gate over
        them would drop transfers the first one deliberately kept.
        """
        result = self._writer.normalizer.normalize(record)

        if result.is_token_activity:
            return self._writer.write(record)

        if not result.storable or result.block is None:
            self.stats.rejected += 1
            return result

        block = result.block
        aggregate, material = accumulate(
            chain=block.chain,
            number=block.number,
            block_hash=block.block_hash,
            timestamp=block.timestamp,
            transactions=block.transactions,
            gate=self._gate,
            stats=self.filter_stats,
            gas_used=block.gas_used,
            complete=result.quality.complete,
            source_provider=block.source_provider,
            source_record_id=block.source_record_id,
        )

        # transaction_count is left at the chain's own figure. Lowering it to
        # the material count would make a busy block read as a quiet one.
        trimmed = replace(block, transactions=tuple(material))

        # Re-assessed against the trimmed block so the report names the floor
        # rather than blaming normalization for a deliberate omission.
        quality = assess_block(
            trimmed,
            capture_gaps=record.capture_gaps,
            capture_floor=self._gate.floor.raw if material or block.transactions else None,
        )

        # The floor is stored only when the report actually names it. A block
        # with no transactions at all was not filtered, and stamping a floor on
        # it would raise the floor a later window reports having been captured
        # at -- narrowing an absence claim on the strength of an empty block.
        filtered = "selective_capture" in quality.incomplete_reason

        outcome = self._repository.save(
            trimmed,
            complete=quality.complete,
            plausible=quality.plausible,
            incomplete_reason=quality.incomplete_reason,
            capture_floor=self._gate.floor if filtered else None,
        )
        if self._aggregates.save(aggregate):
            self.stats.aggregates_written += 1

        self.stats.blocks += 1
        self.stats.transactions_seen += aggregate.tx_count
        self.stats.transactions_kept += aggregate.material_tx_count

        if not outcome.inserted:
            logger.debug(
                "%s: block %d already stored; aggregate upserted",
                block.chain,
                block.number,
            )

        return replace(result, block=trimmed, quality=quality)

    def consume(self, results, queue, *, batch: int = 64):
        """
        Apply a poll run: withdrawals first, then the queue, selectively.

        Mirrors :meth:`database.writer.RecordWriter.consume`, including the
        drain-until-empty behaviour. Draining once leaves records in a queue
        that dies with the process while the checkpoint has already advanced
        past them, which is a permanent hole.
        """
        from ingestion.events import PollStatus

        for result in results:
            if result.status is PollStatus.REORG:
                self._writer.apply(result, queue=queue)

        drained = 0
        while True:
            records = queue.drain(limit=batch)
            if not records:
                break
            for record in records:
                self.write(record)
            drained += len(records)

        return drained

    def health(self) -> dict[str, Any]:
        return {
            "selective": self.stats.as_dict(),
            "filter": self.filter_stats.as_dict(),
            "floor": str(self._gate.floor.raw),
            "limitation": self._gate.limitation(),
        }


__all__ = ["SelectiveStats", "SelectiveWriter"]
