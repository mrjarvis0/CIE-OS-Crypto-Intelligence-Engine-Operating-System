"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.repositories

Purpose:
    The only code that issues SQL against the system of record.

Design goals:
    - Repository pattern mandatory; no SQL escapes this module (DR-09)
    - Writes atomic and idempotent, so a replay is free
    - Reads canonical-only unless the caller asks otherwise
    - Withdrawal by flag, never by delete
    - Amounts round-tripped through the padded text form

Notes:
    Reads exclude withdrawn blocks by default and require
    ``include_withdrawn=True`` to see them. This is the single most consequential
    default in the package. After a reorg the abandoned blocks are still in the
    table -- correctly, because deleting them would erase the evidence a reorg
    occurred -- and a query that forgets to filter reads abandoned history as
    fact while looking entirely ordinary. Making the safe read the default means
    a forgotten filter fails safe; making the unsafe read explicit means anyone
    asking for abandoned history has said so.

    Writes are idempotent through ``ON CONFLICT DO NOTHING`` keyed on the same
    identity the dedup window uses. The in-memory window in
    :mod:`ingestion.dedup` is a fast path that empties on restart, so the durable
    guarantee has to live here: a replayed block hits the primary key and the
    write becomes a no-op rather than a duplicate row or an error.

    ``DO NOTHING`` rather than ``DO UPDATE`` is deliberate. An observation
    should not change after it is made. If a second capture of the same block
    disagrees with the first, that disagreement is a fact about the providers
    worth investigating, and overwriting hides it.
"""

from __future__ import annotations

import logging
import sqlite3

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from schemas.address import Address
from schemas.amount import Amount
from schemas.block import CanonicalBlock, CanonicalTransaction

from .connection import Database, DatabaseError

logger = logging.getLogger(__name__)


def _iso(value: datetime) -> str:
    """Store timestamps as explicit ISO text, not via a driver adapter."""
    return value.astimezone(UTC).isoformat()


def parse_stored_time(value: Any) -> datetime:
    """
    Read a stored ISO timestamp back, refusing anything unreadable.

    Refuses rather than returning None so a corrupt column surfaces where it is
    read. A silently absent timestamp would make a block look undated, and a
    dormancy calculation over undated blocks returns a plausible number.
    """
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    raise DatabaseError(f"stored timestamp is unreadable: {value!r}")


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """
    What a write actually did.

    ``inserted`` false with no error means the row was already present. Callers
    need that apart from a failure: it is the normal result of a replay, and
    counting it as an error would make a resumed run look broken.
    """

    inserted: bool
    block_key: str
    transactions_written: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "inserted": self.inserted,
            "block_key": self.block_key,
            "transactions_written": self.transactions_written,
        }


class BlockRepository(ABC):
    """The contract every storage backend for blocks implements."""

    @abstractmethod
    def save(
        self,
        block: CanonicalBlock,
        *,
        complete: bool = True,
        plausible: bool = True,
        incomplete_reason: str = "",
        capture_floor: Amount | None = None,
    ) -> WriteOutcome:
        """Persist a block and its transactions atomically and idempotently."""

    @abstractmethod
    def get(self, chain: str, block_hash: str) -> CanonicalBlock | None:
        """One block by hash, whether canonical or withdrawn."""

    @abstractmethod
    def at_height(self, chain: str, number: int, *, include_withdrawn: bool = False) -> tuple[CanonicalBlock, ...]:
        """Blocks recorded at a height. More than one only after a reorg."""

    @abstractmethod
    def highest(self, chain: str) -> CanonicalBlock | None:
        """The highest canonical block, which is how far storage has got."""

    @abstractmethod
    def withdraw(self, chain: str, heights: Sequence[int]) -> int:
        """Mark blocks at these heights non-canonical. Returns rows affected."""


class SqliteBlockRepository(BlockRepository):
    """
    SQLite-backed block storage.

    Holds a :class:`Database` rather than a raw connection so that transaction
    boundaries stay in one place: a repository that opened its own transactions
    would make a two-repository write non-atomic without anything looking wrong.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- writing ----------------------------------------------------------

    def save(
        self,
        block: CanonicalBlock,
        *,
        complete: bool = True,
        plausible: bool = True,
        incomplete_reason: str = "",
        capture_floor: Amount | None = None,
    ) -> WriteOutcome:
        """
        Write one block with its transactions in a single transaction.

        The two must land together. A committed block whose transactions failed
        looks exactly like a block that genuinely had none, and because the
        block row exists the next run will not retry it -- so the shortfall is
        permanent and invisible.

        ``incomplete_reason`` and ``capture_floor`` are stored beside
        ``complete`` rather than derived later, because they cannot be derived
        later. Which checks fired is known only to the capture that made the
        request, and a block whose transactions were all dropped at a floor is
        indistinguishable, by inspection, from one fetched without expansion.
        A reader who has to guess between them guesses the worse case.
        """
        with self._db.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO blocks (
                    key, chain, number, block_hash, parent_hash, timestamp,
                    tx_count, canonical, withdrawn_at, gas_used, gas_limit,
                    miner, source_record_id, source_provider, observed_at,
                    complete, plausible, incomplete_reason, capture_floor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (key) DO NOTHING
                """,
                (
                    block.key,
                    block.chain,
                    block.number,
                    block.block_hash,
                    block.parent_hash,
                    _iso(block.timestamp),
                    block.transaction_count,
                    1 if block.canonical else 0,
                    _iso(block.withdrawn_at) if block.withdrawn_at else None,
                    block.gas_used,
                    block.gas_limit,
                    block.miner.value if block.miner else None,
                    block.source_record_id,
                    block.source_provider,
                    _iso(block.observed_at),
                    1 if complete else 0,
                    1 if plausible else 0,
                    incomplete_reason,
                    # Padded, like every other amount column, so MAX() over a
                    # window returns the highest floor and not the longest text.
                    capture_floor.stored() if capture_floor is not None else "",
                ),
            )

            if cursor.rowcount == 0:
                # Already stored. A replay, not a failure.
                return WriteOutcome(inserted=False, block_key=block.key)

            written = self._insert_transactions(connection, block)

        return WriteOutcome(
            inserted=True, block_key=block.key, transactions_written=written
        )

    def _insert_transactions(
        self, connection: sqlite3.Connection, block: CanonicalBlock
    ) -> int:
        """Insert a block's transactions inside the caller's transaction."""
        if not block.transactions:
            return 0

        rows = [
            (
                tx.key,
                tx.chain,
                tx.tx_hash,
                block.key,
                tx.block_number,
                tx.index,
                tx.from_address.value,
                tx.to_address.value if tx.to_address else None,
                tx.value.stored(),
                tx.value.decimals,
                tx.gas_limit,
                tx.gas_price.stored() if tx.gas_price else None,
                tx.nonce,
                tx.input_size,
                tx.source_record_id,
            )
            for tx in block.transactions
        ]

        connection.executemany(
            """
            INSERT INTO transactions (
                key, chain, tx_hash, block_key, block_number, tx_index,
                from_address, to_address, value, value_decimals,
                gas_limit, gas_price, nonce, input_size, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO NOTHING
            """,
            rows,
        )
        return len(rows)

    def withdraw(self, chain: str, heights: Sequence[int]) -> int:
        """
        Mark every block at these heights non-canonical.

        Called with the ``withdrawn`` heights from a reorg poll result. Nothing
        is deleted: the observations were correct, and the record that a reorg
        happened is exactly what an analyst investigating a double spend needs.
        """
        if not heights:
            return 0

        now = _iso(datetime.now(UTC))
        placeholders = ",".join("?" for _ in heights)

        with self._db.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE blocks
                   SET canonical = 0, withdrawn_at = ?
                 WHERE chain = ? AND canonical = 1 AND number IN ({placeholders})
                """,
                (now, chain, *heights),
            )
            affected = cursor.rowcount

        if affected:
            logger.warning("%s: withdrew %d block(s) from the canonical chain", chain, affected)
        return affected

    # -- reading ----------------------------------------------------------

    def get(self, chain: str, block_hash: str) -> CanonicalBlock | None:
        row = self._db.connection.execute(
            "SELECT * FROM blocks WHERE key = ?", (f"{chain}:{block_hash.lower()}",)
        ).fetchone()
        return self._hydrate(row) if row else None

    def at_height(
        self, chain: str, number: int, *, include_withdrawn: bool = False
    ) -> tuple[CanonicalBlock, ...]:
        """
        Every block recorded at a height.

        Returns more than one only where a reorg happened, which makes this the
        query for auditing one: two rows at a height with different hashes is
        the durable record of the fork.
        """
        sql = "SELECT * FROM blocks WHERE chain = ? AND number = ?"
        if not include_withdrawn:
            sql += " AND canonical = 1"
        rows = self._db.connection.execute(sql + " ORDER BY canonical DESC", (chain, number))
        return tuple(self._hydrate(row) for row in rows)

    def highest(self, chain: str) -> CanonicalBlock | None:
        """How far storage has got on this chain, ignoring abandoned blocks."""
        row = self._db.connection.execute(
            """
            SELECT * FROM blocks
             WHERE chain = ? AND canonical = 1
             ORDER BY number DESC LIMIT 1
            """,
            (chain,),
        ).fetchone()
        return self._hydrate(row) if row else None

    def count(self, chain: str | None = None, *, include_withdrawn: bool = False) -> int:
        sql = "SELECT COUNT(*) FROM blocks WHERE 1 = 1"
        params: list[Any] = []
        if chain is not None:
            sql += " AND chain = ?"
            params.append(chain)
        if not include_withdrawn:
            sql += " AND canonical = 1"
        row = self._db.connection.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def transactions_of(self, block: CanonicalBlock) -> tuple[CanonicalTransaction, ...]:
        """A stored block's transactions, in block order."""
        rows = self._db.connection.execute(
            "SELECT * FROM transactions WHERE block_key = ? ORDER BY tx_index",
            (block.key,),
        )
        return tuple(self._hydrate_transaction(row) for row in rows)

    def largest_transfers(
        self, chain: str, *, limit: int = 10, include_withdrawn: bool = False
    ) -> tuple[CanonicalTransaction, ...]:
        """
        The highest-value transfers stored for a chain.

        Correct only because values are zero-padded: an unpadded text column
        orders ``"9"`` after ``"10"``, so this query would return small
        transfers and report them as the largest.
        """
        if limit <= 0:
            raise ValueError("limit must be > 0")

        sql = """
            SELECT t.* FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ?
        """
        if not include_withdrawn:
            sql += " AND b.canonical = 1"
        sql += " ORDER BY t.value DESC LIMIT ?"

        rows = self._db.connection.execute(sql, (chain, limit))
        return tuple(self._hydrate_transaction(row) for row in rows)

    def activity_of(
        self, address: Address, *, limit: int = 50
    ) -> tuple[CanonicalTransaction, ...]:
        """
        Transactions where an address is sender or recipient.

        Matches on the normalized form, which is the reason
        :class:`schemas.address.Address` folds case: a checksummed literal
        compared against stored lowercase would return nothing and read as an
        address with no history.
        """
        if limit <= 0:
            raise ValueError("limit must be > 0")

        rows = self._db.connection.execute(
            """
            SELECT t.* FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
               AND (t.from_address = ? OR t.to_address = ?)
             ORDER BY t.block_number DESC, t.tx_index DESC
             LIMIT ?
            """,
            (address.chain, address.value, address.value, limit),
        )
        return tuple(self._hydrate_transaction(row) for row in rows)

    # -- hydration --------------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> CanonicalBlock:
        chain = row["chain"]
        return CanonicalBlock(
            chain=chain,
            number=int(row["number"]),
            block_hash=row["block_hash"],
            parent_hash=row["parent_hash"],
            timestamp=parse_stored_time(row["timestamp"]),
            transaction_count=int(row["tx_count"]),
            canonical=bool(row["canonical"]),
            withdrawn_at=parse_stored_time(row["withdrawn_at"]) if row["withdrawn_at"] else None,
            gas_used=row["gas_used"],
            gas_limit=row["gas_limit"],
            miner=Address.parse(row["miner"], chain) if row["miner"] else None,
            source_record_id=row["source_record_id"],
            source_provider=row["source_provider"],
            observed_at=parse_stored_time(row["observed_at"]),
        )

    def _hydrate_transaction(self, row: sqlite3.Row) -> CanonicalTransaction:
        chain = row["chain"]
        decimals = int(row["value_decimals"])
        return CanonicalTransaction(
            chain=chain,
            tx_hash=row["tx_hash"],
            block_number=int(row["block_number"]),
            block_hash="",  # carried by the parent row; not duplicated here
            index=int(row["tx_index"]),
            from_address=Address.parse(row["from_address"], chain),
            to_address=Address.parse(row["to_address"], chain) if row["to_address"] else None,
            value=Amount.from_stored(row["value"], decimals),
            gas_limit=row["gas_limit"],
            gas_price=Amount.from_stored(row["gas_price"], decimals) if row["gas_price"] else None,
            nonce=row["nonce"],
            input_size=int(row["input_size"]),
            source_record_id=row["source_record_id"],
        )


__all__ = [
    "BlockRepository",
    "SqliteBlockRepository",
    "WriteOutcome",
    "parse_stored_time",
]
