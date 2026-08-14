"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.backfill

Purpose:
    Fill a deliberate range of historical heights, resumably, without
    disturbing the head-following poller's position.

Design goals:
    - Explicit bounded range; never "everything since genesis" by accident
    - Resumable: an interrupted run continues where it stopped
    - Its own progress record, kept apart from the live checkpoint
    - Missing heights reported, never silently skipped
    - Stepped, like the poller, so it is testable and interruptible

Notes:
    Backfill is separated from polling because they fail differently and must
    not share a position. The poller's checkpoint says "the chain is ingested up
    to here"; a backfill runs behind that point, and writing its progress into
    the same record would move the live position backwards and re-ingest the
    present.

    Reorg tracking is deliberately absent. A range that is thousands of blocks
    behind the head is settled -- reorgs do not reach it -- and running linkage
    checks against a tracker that holds the *current* tip would report a reorg
    at every historical block, since none of them are the tracker's parent.
    Historical corruption is caught by re-reading and comparing, which belongs
    to a verification pass, not to capture.

    Failures are collected rather than raised. A 50,000-block backfill that
    aborts on the first unavailable height wastes everything before it; one
    that records the misses and finishes lets the gaps be retried as a much
    smaller second pass. :attr:`BackfillProgress.missing` is that retry list.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field, replace
from typing import Any

from core.exceptions import IngestionError
from sensors.base import Sensor
from sensors.envelope import CaptureGap, RawRecord

from .dedup import SeenSet
from .linkage import LinkageError, block_ref_from_record
from .queue import RecordQueue

logger = logging.getLogger(__name__)

#: Heights attempted per :meth:`Backfill.run` call. Bounded so a caller keeps
#: control: progress can be reported, budget checked, and the run stopped.
DEFAULT_BATCH = 50


@dataclass(slots=True)
class BackfillProgress:
    """
    How far a backfill got, and what it could not read.

    ``missing`` is the retry list, not an error log. A height lands there when
    the chain could not be read or the payload could not be trusted; both are
    worth another attempt, possibly against a different provider.
    """

    chain: str
    start: int
    end: int
    cursor: int
    captured: int = 0
    duplicates: int = 0
    missing: list[int] = field(default_factory=list)
    logs_captured: int = 0
    #: Heights whose logs were requested and refused. The blocks were still
    #: stored -- marked incomplete, so nothing reads them as transfer-free.
    logs_undetermined: int = 0
    logs_dropped: int = 0

    @property
    def complete(self) -> bool:
        return self.cursor > self.end

    @property
    def total(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining(self) -> int:
        return max(self.end - self.cursor + 1, 0)

    @property
    def fraction(self) -> float:
        done = self.total - self.remaining
        return done / self.total if self.total else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "range": [self.start, self.end],
            "cursor": self.cursor,
            "complete": self.complete,
            "captured": self.captured,
            "duplicates": self.duplicates,
            "missing": list(self.missing),
            "logs_captured": self.logs_captured,
            "logs_undetermined": self.logs_undetermined,
            "logs_dropped": self.logs_dropped,
            "fraction": round(self.fraction, 4),
        }


class Backfill:
    """
    Walks a historical height range and queues what it finds.

    Holds its own cursor rather than a checkpoint store entry, because a
    backfill is a task with a defined end, not a position that persists. A
    caller that needs it to survive a restart records
    :attr:`BackfillProgress.cursor` alongside whatever scheduled it.
    """

    def __init__(
        self,
        sensor: Sensor,
        start: int,
        end: int,
        *,
        queue: RecordQueue[RawRecord] | None = None,
        seen: SeenSet | None = None,
        include_transactions: bool = False,
        include_logs: bool = False,
    ) -> None:
        if start < 0:
            raise IngestionError(f"backfill start must be >= 0, got {start}")
        if end < start:
            raise IngestionError(f"backfill range {start}-{end} is inverted")

        self._sensor = sensor
        self._chain = sensor.chain
        self._queue: RecordQueue[RawRecord] = queue if queue is not None else RecordQueue()
        self._seen = seen if seen is not None else SeenSet()
        self._include_transactions = include_transactions
        self._include_logs = include_logs

        self.progress = BackfillProgress(
            chain=self._chain, start=start, end=end, cursor=start
        )

    # -- accessors --------------------------------------------------------

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def queue(self) -> RecordQueue[RawRecord]:
        return self._queue

    @property
    def complete(self) -> bool:
        return self.progress.complete

    def resume_at(self, height: int) -> None:
        """
        Move the cursor, for continuing an interrupted run.

        Refuses a position outside the range: silently clamping it would make
        a caller's off-by-one look like a successful resume, and the heights
        between the two positions would never be read.
        """
        if height < self.progress.start or height > self.progress.end + 1:
            raise IngestionError(
                f"resume height {height} is outside backfill range "
                f"{self.progress.start}-{self.progress.end}"
            )
        self.progress.cursor = height

    # -- stepping ---------------------------------------------------------

    def step(self) -> bool:
        """
        Attempt one height. Returns False when the range is finished.

        A single height per call, so the caller can pace requests against a
        rate budget it owns and this class does not know about.
        """
        if self.progress.complete:
            return False
        if self._queue.is_full:
            # Same reasoning as the poller: do not spend a request on a record
            # that cannot be handed off.
            return True

        height = self.progress.cursor
        read = self._sensor.block(
            height, include_transactions=self._include_transactions
        )

        if not read.determined or read.record is None:
            self.progress.missing.append(height)
            logger.debug(
                "%s: backfill height %d unavailable: %s",
                self._chain,
                height,
                read.reason,
            )
            self.progress.cursor += 1
            return True

        record = read.record
        try:
            # Validated for linkage even though no tracker consumes it here: a
            # payload that cannot state which block it is has no place in
            # storage, and finding that out at read time costs nothing.
            block_ref_from_record(record)
        except LinkageError as exc:
            logger.warning("%s: backfill height %d malformed: %s", self._chain, height, exc)
            self.progress.missing.append(height)
            self.progress.cursor += 1
            return True

        outcome = self._seen.check(record)
        if outcome.is_duplicate:
            self.progress.duplicates += 1
            self.progress.cursor += 1
            return True

        # Same ordering as the poller, for the same two reasons: the log
        # outcome has to reach the block's own record, and the log batch has to
        # reach storage after the block it references.
        #
        # This path had no log handling at all, which made it the more
        # dangerous of the two. A historical range is exactly what a deep
        # coverage window is built from, and every block it captured was stored
        # looking whole whether or not its transfers had ever been fetched.
        logs: RawRecord | None = None
        if self._include_logs:
            logs = self._read_logs(height)
            if logs is not None and len(self._queue) + 2 > self._queue.capacity:
                self.progress.logs_dropped += 1
                logger.warning(
                    "%s: logs for height %d dropped, queue full", self._chain, height
                )
                logs = None
            if logs is None:
                record = replace(
                    record, capture_gaps=(*record.capture_gaps, CaptureGap.LOGS)
                )

        if not self._queue.put(record).accepted:  # pragma: no cover - checked above
            return True

        if logs is not None:
            if self._queue.put(logs).accepted:
                self.progress.logs_captured += 1
            else:  # pragma: no cover - capacity checked above
                self.progress.logs_dropped += 1

        self._seen.add(record)
        self.progress.captured += 1
        self.progress.cursor += 1
        return True

    def _read_logs(self, height: int) -> RawRecord | None:
        """
        Fetch this height's event logs. ``None`` when they could not be had.

        Not fatal to the block, for the reason the poller states: log reads are
        the first thing a free provider rate-limits, and dropping a good block
        over them would stall a backfill on its least reliable call. The block
        is kept and marked instead, so it supports positive claims and no
        negative ones.
        """
        read = self._sensor.logs(from_height=height, to_height=height)

        if not read.determined or read.record is None:
            self.progress.logs_undetermined += 1
            logger.debug(
                "%s: backfill logs for height %d undetermined: %s",
                self._chain,
                height,
                read.reason,
            )
            return None

        return read.record

    def run(self, batch: int = DEFAULT_BATCH) -> BackfillProgress:
        """Attempt up to ``batch`` heights and report progress."""
        if batch <= 0:
            raise ValueError("batch must be > 0")

        for _ in range(batch):
            if not self.step():
                break
            if self._queue.is_full:
                logger.info(
                    "%s: backfill paused at %d, queue full",
                    self._chain,
                    self.progress.cursor,
                )
                break
        return self.progress

    def retry_missing(self) -> BackfillProgress:
        """
        Re-attempt the heights that could not be read.

        Kept as a separate pass so a caller can change the conditions first --
        add a provider key, wait out a throttle -- rather than retrying into
        the same wall.
        """
        pending, self.progress.missing = self.progress.missing, []
        saved_cursor = self.progress.cursor

        for height in pending:
            self.progress.cursor = height
            self.step()

        self.progress.cursor = saved_cursor
        return self.progress

    def health(self) -> dict[str, Any]:
        return {
            "sensor": self._sensor.name,
            "progress": self.progress.as_dict(),
            "queue": self._queue.snapshot(),
            "dedup": self._seen.snapshot(),
        }

    def __repr__(self) -> str:
        return (
            f"Backfill(chain={self._chain!r}, "
            f"cursor={self.progress.cursor}, end={self.progress.end})"
        )


__all__ = ["DEFAULT_BATCH", "Backfill", "BackfillProgress"]
