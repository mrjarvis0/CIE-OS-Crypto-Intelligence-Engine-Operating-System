"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    tiers.hot

Purpose:
    Tier H. Per-block aggregates: what a block contained, computed once at
    capture from transactions that were then discarded.

Design goals:
    - One small row per block, whatever the block's transaction count
    - Atomic idempotent writes, matching the rest of the storage layer
    - Completeness travels with the row, as it does on ``blocks``
    - The materiality threshold in force is recorded, never assumed
    - No network I/O

Notes:
    This table is what allows the transaction mirror to go away. A block with
    334 transactions produced ~0.70 MB of rows so that a handful of figures
    could later be derived from them; those figures are now derived once, here,
    and the rows they came from are dropped.

    ``materiality_floor`` is stored per block rather than read from config at
    query time, and that distinction matters. The floor moves -- it is a
    percentile against a rolling distribution, and it rises when a rate budget
    runs low. A block captured under a raised floor holds fewer material
    transactions than an identical block captured under a normal one, and
    without the floor recorded a reader cannot tell a quiet chain from a
    throttled capture.

    ``complete`` carries the same meaning it does on ``blocks``: whether the
    capture obtained everything it asked for. An aggregate over a block whose
    logs were refused cannot license a claim about what that block did not
    contain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from database.connection import Database
from schemas.amount import Amount

from .retention import Tier


def _iso(value: datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class BlockAggregate:
    """
    One block, reduced to what is worth keeping.

    Every count here covers the *whole* block, including the transactions that
    were discarded. That is the point: the aggregate is the only surviving
    statement about them, so it has to be complete about what it summarises
    even though the summarised rows are gone.
    """

    chain: str
    number: int
    block_hash: str
    timestamp: datetime
    tx_count: int
    tx_value_total: Amount
    tx_value_max: Amount
    unique_senders: int = 0
    unique_receivers: int = 0
    gas_used: int | None = None
    material_tx_count: int = 0
    material_value_total: Amount = Amount(0)
    materiality_floor: Amount = Amount(0)
    complete: bool = True
    source_provider: str = ""
    source_record_id: str = ""
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("aggregate must name its chain")
        if self.number < 0:
            raise ValueError("block number must be >= 0")
        if self.tx_count < 0:
            raise ValueError("tx_count must be >= 0")
        if self.material_tx_count > self.tx_count:
            # Not a nitpick: a material count above the total means the gate and
            # the counter disagreed about what they were looking at, and every
            # ratio derived from this row would be wrong.
            raise ValueError(
                f"material_tx_count {self.material_tx_count} exceeds "
                f"tx_count {self.tx_count}"
            )

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.block_hash}"

    @property
    def material_share(self) -> float:
        """Fraction of the block that cleared the gate. The compression ratio."""
        return self.material_tx_count / self.tx_count if self.tx_count else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "number": self.number,
            "block_hash": self.block_hash,
            "timestamp": _iso(self.timestamp),
            "tx_count": self.tx_count,
            "tx_value_total": str(self.tx_value_total.raw),
            "tx_value_max": str(self.tx_value_max.raw),
            "unique_senders": self.unique_senders,
            "unique_receivers": self.unique_receivers,
            "material_tx_count": self.material_tx_count,
            "material_share": round(self.material_share, 6),
            "materiality_floor": str(self.materiality_floor.raw),
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class WindowTotals:
    """
    What a time range held, summed from aggregates.

    ``complete_blocks`` is reported beside ``blocks`` rather than folded into
    it, because a total drawn partly from incomplete captures is a floor. The
    caller decides whether that is good enough for the claim it wants to make;
    this type refuses to make that decision for it.
    """

    chain: str
    blocks: int = 0
    complete_blocks: int = 0
    tx_count: int = 0
    tx_value_total: Amount = Amount(0)
    material_tx_count: int = 0
    material_value_total: Amount = Amount(0)
    first_number: int | None = None
    last_number: int | None = None

    @property
    def all_complete(self) -> bool:
        return self.blocks > 0 and self.complete_blocks == self.blocks

    @property
    def incomplete_blocks(self) -> int:
        return self.blocks - self.complete_blocks

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "blocks": self.blocks,
            "complete_blocks": self.complete_blocks,
            "incomplete_blocks": self.incomplete_blocks,
            "all_complete": self.all_complete,
            "tx_count": self.tx_count,
            "tx_value_total": str(self.tx_value_total.raw),
            "material_tx_count": self.material_tx_count,
            "material_value_total": str(self.material_value_total.raw),
            "range": [self.first_number, self.last_number],
        }


class BlockAggregateRepository:
    """
    Reads and writes Tier H aggregates.

    Holds a :class:`Database` rather than a connection, so a write here can join
    the same transaction as the material transactions it summarises. Splitting
    them across two transactions would allow an aggregate claiming three
    material transfers to be committed while the transfers themselves were not.
    """

    tier = Tier.HOT

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- writing ----------------------------------------------------------

    def save(self, aggregate: BlockAggregate) -> bool:
        """
        Store one aggregate. Returns False when it was already present.

        ``ON CONFLICT DO NOTHING`` for the same reason the blocks table uses it:
        replaying a range must be free, and the first observation of a block is
        the one to keep.
        """
        observed = aggregate.observed_at or datetime.now(aggregate.timestamp.tzinfo)

        with self._db.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO block_aggregates (
                    key, chain, number, block_hash, timestamp,
                    tx_count, tx_value_total, tx_value_max,
                    unique_senders, unique_receivers, gas_used,
                    material_tx_count, material_value_total, materiality_floor,
                    complete, source_provider, source_record_id, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (key) DO NOTHING
                """,
                (
                    aggregate.key,
                    aggregate.chain,
                    aggregate.number,
                    aggregate.block_hash,
                    _iso(aggregate.timestamp),
                    aggregate.tx_count,
                    aggregate.tx_value_total.stored(),
                    aggregate.tx_value_max.stored(),
                    aggregate.unique_senders,
                    aggregate.unique_receivers,
                    aggregate.gas_used,
                    aggregate.material_tx_count,
                    aggregate.material_value_total.stored(),
                    aggregate.materiality_floor.stored(),
                    1 if aggregate.complete else 0,
                    aggregate.source_provider,
                    aggregate.source_record_id,
                    _iso(observed),
                ),
            )
            return cursor.rowcount > 0

    def save_many(self, aggregates: Sequence[BlockAggregate]) -> int:
        """Store a batch in one transaction. Returns rows inserted."""
        return sum(1 for aggregate in aggregates if self.save(aggregate))

    # -- reading ----------------------------------------------------------

    def totals_between(
        self, chain: str, start: datetime, end: datetime
    ) -> WindowTotals:
        """
        What moved between two timestamps.

        The query behind "how much moved in the last four hours", which is the
        question the old design answered by summing a table of every
        transaction that had ever been seen.
        """
        # Counts are summed in SQL; values are not.
        #
        # Value columns are zero-padded TEXT precisely because SQLite's INTEGER
        # is signed 64-bit, whose ceiling is about 9.22e18 -- roughly nine ether
        # in wei. `SUM(CAST(value AS INTEGER))` would silently truncate every
        # transfer above that, which is exactly the set this system exists to
        # measure, and the total would come back plausible and wrong. Python
        # integers are unbounded, so the summing happens here.
        counts = self._db.connection.execute(
            """
            SELECT COUNT(*)               AS blocks,
                   SUM(complete)          AS complete_blocks,
                   SUM(tx_count)          AS tx_count,
                   SUM(material_tx_count) AS material_count,
                   MIN(number)            AS lo,
                   MAX(number)            AS hi
              FROM block_aggregates
             WHERE chain = ? AND timestamp >= ? AND timestamp <= ?
            """,
            (chain, _iso(start), _iso(end)),
        ).fetchone()

        if counts is None or not counts["blocks"]:
            return WindowTotals(chain=chain)

        values = self._db.connection.execute(
            """
            SELECT tx_value_total, material_value_total
              FROM block_aggregates
             WHERE chain = ? AND timestamp >= ? AND timestamp <= ?
            """,
            (chain, _iso(start), _iso(end)),
        )

        value_total = 0
        material_total = 0
        for row in values:
            value_total += int(row["tx_value_total"])
            material_total += int(row["material_value_total"])

        return WindowTotals(
            chain=chain,
            blocks=int(counts["blocks"]),
            complete_blocks=int(counts["complete_blocks"] or 0),
            tx_count=int(counts["tx_count"] or 0),
            tx_value_total=Amount(value_total),
            material_tx_count=int(counts["material_count"] or 0),
            material_value_total=Amount(material_total),
            first_number=int(counts["lo"]),
            last_number=int(counts["hi"]),
        )

    def highest(self, chain: str) -> int | None:
        """How far aggregation has got, which is not the same as ingestion."""
        row = self._db.connection.execute(
            "SELECT MAX(number) AS hi FROM block_aggregates WHERE chain = ?",
            (chain,),
        ).fetchone()
        return int(row["hi"]) if row and row["hi"] is not None else None

    def count(self, chain: str) -> int:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS n FROM block_aggregates WHERE chain = ?",
            (chain,),
        ).fetchone()
        return int(row["n"]) if row else 0


__all__ = ["BlockAggregate", "BlockAggregateRepository", "WindowTotals"]
