"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.events

Purpose:
    The vocabulary a poll step reports in: what happened, to which height, and
    what a consumer must do about it.

Design goals:
    - Every outcome named, including the ones that are not failures
    - Withdrawals carried as data, not left in a log line
    - Importable without pulling in the polling machinery
    - No behaviour; these are results, not actors

Notes:
    Separated from the poller so a consumer -- a storage writer, a metrics
    exporter, a test -- can depend on the outcome vocabulary without depending
    on the loop that produces it.

    Four of the eight statuses describe conditions that are not errors, and
    naming them separately is the point. ``CAUGHT_UP`` means there is nothing
    to read; ``NOT_YET`` means the provider has not reached a height the head
    implied; ``DUPLICATE`` means the work was already done; ``BACKPRESSURE``
    means the consumer is behind. Collapsing any of these into a generic
    failure would make an ordinary quiet minute look like an outage, and the
    alert that follows trains an operator to ignore alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from blockchain.reorg import ReorgEvent
from sensors.envelope import RawRecord


class PollStatus(StrEnum):
    """What one poll step accomplished."""

    #: A block was captured, queued, and checkpointed.
    ADVANCED = "advanced"
    #: Nothing to do: the next height is above the settled boundary.
    CAUGHT_UP = "caught_up"
    #: The chain could not be read. Not the same as having nothing to read.
    UNDETERMINED = "undetermined"
    #: The provider does not have this height yet, though the head implied it.
    NOT_YET = "not_yet"
    #: Already processed. Replay or an overlapping backfill.
    DUPLICATE = "duplicate"
    #: Parent linkage broke; the recorded chain was withdrawn and rewound.
    REORG = "reorg"
    #: A provider answered with a payload that cannot be trusted.
    MALFORMED = "malformed"
    #: The queue is full. The consumer is behind; do not advance.
    BACKPRESSURE = "backpressure"


@dataclass(frozen=True, slots=True)
class PollResult:
    """
    Outcome of one step, with everything a caller needs to react.

    ``withdrawn`` is the field a storage consumer must not ignore. After a
    reorg those heights hold blocks that are no longer canonical, and leaving
    them in place is worse than never having ingested them: later analysis
    reads them as history.
    """

    status: PollStatus
    chain: str
    height: int | None = None
    record: RawRecord | None = None
    reorg: ReorgEvent | None = None
    #: Heights withdrawn by a reorg. The consumer must delete these.
    withdrawn: tuple[int, ...] = ()
    reason: str = ""

    @property
    def progressed(self) -> bool:
        """Whether the chain position moved forward."""
        return self.status is PollStatus.ADVANCED

    @property
    def should_retry(self) -> bool:
        """Whether stepping again immediately could help."""
        return self.status in {
            PollStatus.ADVANCED,
            PollStatus.DUPLICATE,
            PollStatus.REORG,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "chain": self.chain,
            "height": self.height,
            "record_id": self.record.record_id if self.record else None,
            "reorg": self.reorg.as_dict() if self.reorg else None,
            "withdrawn": list(self.withdrawn),
            "reason": self.reason,
        }


@dataclass(slots=True)
class PollerStats:
    """
    Counters for doctor and for spotting a stall.

    ``undetermined`` and ``malformed`` are counted apart on purpose. A rising
    undetermined count means the network or the provider is unavailable; a
    rising malformed count means a reachable provider is returning payloads
    that cannot be trusted, which is a different problem with a different fix.
    """

    steps: int = 0
    advanced: int = 0
    duplicates: int = 0
    reorgs: int = 0
    undetermined: int = 0
    malformed: int = 0
    backpressure: int = 0
    logs_captured: int = 0
    logs_undetermined: int = 0
    logs_dropped: int = 0
    withdrawn_blocks: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "advanced": self.advanced,
            "duplicates": self.duplicates,
            "reorgs": self.reorgs,
            "undetermined": self.undetermined,
            "malformed": self.malformed,
            "backpressure": self.backpressure,
            "logs_captured": self.logs_captured,
            "logs_undetermined": self.logs_undetermined,
            "logs_dropped": self.logs_dropped,
            "withdrawn_blocks": self.withdrawn_blocks,
        }


__all__ = ["PollResult", "PollStatus", "PollerStats"]
