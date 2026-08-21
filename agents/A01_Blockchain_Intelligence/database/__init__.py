"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    database

Purpose:
    A01's system of record. Where an observation stops being in flight and
    becomes history.

Layer contract
--------------
Design rule DR-09 governs this package: atomic writes only, idempotent
operations, immutable historical records, no direct SQL outside a repository.
DR-10 separates it from ``memory/`` -- runtime recall lives there, permanent
chain history lives here.

Three decisions carry the weight, each preventing a silent failure:

* **Blocks are keyed by hash, not height.** A reorg produces two different
  blocks at one height; a height-keyed table can hold only one, so the evidence
  that a reorg happened is destroyed by the storage layout itself.
* **Withdrawal is a flag.** The abandoned block was a correct observation of a
  state that was later abandoned, so it stays. Reads therefore exclude it *by
  default* and must opt in to see it -- a forgotten filter fails safe.
* **Amounts are padded text.** ``INTEGER`` is 64-bit and overflows above roughly
  nine ether expressed in wei, which silently truncates exactly the transfers a
  whale detector exists to find. See :mod:`schemas.amount`.

Usage
-----
::

    with Database("data/a01.db") as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        results = poller.run(max_steps=50)
        report = writer.consume(results, poller.queue)

:meth:`RecordWriter.consume` is the correct entry point: it applies reorg
withdrawals -- including purging records the reorg invalidated while they were
still queued -- before storing anything new.
"""

from __future__ import annotations

from .analytics import (
    DEFAULT_POPULATION_LIMIT,
    AddressSummary,
    HeightWindow,
    HourQuality,
    SqliteAnalyticsRepository,
    TransferRecord,
)
from .approvals import ApprovalWriteOutcome, SqliteApprovalRepository
from .connection import BUSY_TIMEOUT, MEMORY, Database, DatabaseError
from .migrations import (
    CURRENT_VERSION,
    MIGRATIONS,
    Migration,
    applied_version,
    migrate,
)
from .repositories import (
    BlockRepository,
    SqliteBlockRepository,
    WriteOutcome,
    parse_stored_time,
)
from .tokens import SqliteTokenRepository, TokenWriteOutcome
from .writer import DEFAULT_BATCH, DrainReport, RecordWriter, WriterStats

__all__ = [
    "BUSY_TIMEOUT",
    "CURRENT_VERSION",
    "DEFAULT_BATCH",
    "DEFAULT_POPULATION_LIMIT",
    "MEMORY",
    "MIGRATIONS",
    "AddressSummary",
    "ApprovalWriteOutcome",
    "BlockRepository",
    "Database",
    "DatabaseError",
    "DrainReport",
    "HeightWindow",
    "HourQuality",
    "Migration",
    "RecordWriter",
    "SqliteAnalyticsRepository",
    "SqliteApprovalRepository",
    "SqliteBlockRepository",
    "SqliteTokenRepository",
    "TokenWriteOutcome",
    "TransferRecord",
    "WriteOutcome",
    "WriterStats",
    "applied_version",
    "migrate",
    "parse_stored_time",
]
