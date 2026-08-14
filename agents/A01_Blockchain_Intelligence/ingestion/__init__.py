"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    ingestion

Purpose:
    Turn individual sensor reads into an ordered, resumable, reorg-safe stream
    of chain observations.

Layer contract
--------------
Sensors decide *how* to read; ingestion decides *when* to read, *in what
order*, and *what an arriving block means for what was already recorded*. It
still interprets nothing about the content -- a block is a payload with linkage
until normalization gives it meaning.

The four conditions ``identity/design_rules.md`` DR-11 calls normal, not
exceptional, are each handled by a named component here:

===================== ==========================================
Condition             Handled by
===================== ==========================================
Chain reorganizations :mod:`ingestion.poller` over ``blockchain.reorg``
Duplicate events      :mod:`ingestion.dedup`
Delayed confirmations Confirmation lag in :class:`BlockPoller`
Replay processing     :mod:`ingestion.checkpoint`
Historical backfill   :mod:`ingestion.backfill`
===================== ==========================================

One condition is deliberately *not* absorbed: a reorg reaching below an
observed finalized height raises :class:`core.exceptions.FinalityViolationError`
and stops the loop. It cannot legitimately occur, so it is evidence that a
provider is wrong rather than that the chain moved.
"""

from __future__ import annotations

from .backfill import DEFAULT_BATCH, Backfill, BackfillProgress
from .checkpoint import (
    CHECKPOINT_VERSION,
    Checkpoint,
    CheckpointStore,
    FileCheckpointStore,
    InMemoryCheckpointStore,
)
from .dedup import Seen, SeenResult, SeenSet
from .events import PollResult, PollerStats, PollStatus
from .linkage import (
    LinkageError,
    block_ref_from_payload,
    block_ref_from_record,
    has_linkage,
)
from .poller import DEFAULT_FINALITY_EVERY, BlockPoller
from .queue import DEFAULT_CAPACITY, Overflow, PutResult, RecordQueue
from .recovery import RecoveryPlan, ReorgRecovery

__all__ = [
    "CHECKPOINT_VERSION",
    "DEFAULT_BATCH",
    "DEFAULT_CAPACITY",
    "DEFAULT_FINALITY_EVERY",
    "Backfill",
    "BackfillProgress",
    "BlockPoller",
    "Checkpoint",
    "CheckpointStore",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
    "LinkageError",
    "Overflow",
    "PollResult",
    "PollStatus",
    "PollerStats",
    "PutResult",
    "RecordQueue",
    "RecoveryPlan",
    "ReorgRecovery",
    "Seen",
    "SeenResult",
    "SeenSet",
    "block_ref_from_payload",
    "block_ref_from_record",
    "has_linkage",
]
