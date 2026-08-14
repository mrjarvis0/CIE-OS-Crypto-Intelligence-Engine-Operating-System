"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.tokens

Purpose:
    Store and read token and NFT movements.

Design goals:
    - Repository pattern; no SQL escapes this module (DR-09)
    - Writes idempotent on the log's own position
    - Reads canonical-only by default, like every other read path
    - Value comparisons scoped to one token, never across tokens
    - Amounts round-tripped through the padded text form

Notes:
    One rule here has no counterpart in :mod:`database.repositories`, and it is
    the one most likely to be broken by a well-meaning query: **raw token
    amounts are not comparable across tokens.** A transfer of ``1000000`` USDC
    units is one dollar; ``1000000`` units of an 18-decimal token is a
    millionth of one. Until decimals are resolved, ordering a chain-wide
    "largest token transfers" list produces a ranking of nothing.

    So :meth:`SqliteTokenRepository.largest_transfers` requires a token
    argument. It is not a convenience filter — it is the constraint that makes
    the ordering mean anything, and enforcing it in the signature is cheaper
    than catching the mistake in a report.

    Writes are idempotent on ``chain:tx_hash:log_index``. A replayed block
    re-emits identical logs, and ``ON CONFLICT DO NOTHING`` makes that a no-op
    rather than a duplicate row -- matching how blocks and transactions behave.
"""

from __future__ import annotations

import logging
import sqlite3

from dataclasses import dataclass
from typing import Any, Sequence

from schemas.address import Address
from schemas.amount import Amount
from schemas.token import CanonicalNftTransfer, CanonicalTokenTransfer, TokenActivity

from .connection import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TokenWriteOutcome:
    """What a token write actually did."""

    transfers_written: int = 0
    nfts_written: int = 0
    #: Records skipped because their block is not stored. Not an error: logs
    #: can arrive for a block that was withdrawn, or that ingestion has not
    #: reached. Counted so a persistent gap is visible.
    orphaned: int = 0

    @property
    def total(self) -> int:
        return self.transfers_written + self.nfts_written

    def as_dict(self) -> dict[str, Any]:
        return {
            "transfers_written": self.transfers_written,
            "nfts_written": self.nfts_written,
            "orphaned": self.orphaned,
            "total": self.total,
        }


class SqliteTokenRepository:
    """SQLite-backed storage for token and NFT movements."""

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- writing ----------------------------------------------------------

    def save(self, activity: TokenActivity) -> TokenWriteOutcome:
        """
        Write one block's token movements atomically.

        Records whose block is not stored are skipped rather than inserted.
        The foreign key would reject them anyway; catching it here lets the
        rest of the batch land and turns a hard failure into a counted gap.
        """
        if activity.empty:
            return TokenWriteOutcome()

        known = self._known_blocks(
            activity.chain,
            {t.block_hash for t in activity.transfers}
            | {n.block_hash for n in activity.nft_transfers},
        )

        transfers = [t for t in activity.transfers if t.block_hash in known]
        nfts = [n for n in activity.nft_transfers if n.block_hash in known]
        orphaned = (len(activity.transfers) - len(transfers)) + (
            len(activity.nft_transfers) - len(nfts)
        )

        if orphaned:
            logger.warning(
                "%s: %d token record(s) reference a block that is not stored",
                activity.chain,
                orphaned,
            )

        with self._db.transaction() as connection:
            written = self._insert_transfers(connection, transfers)
            nft_written = self._insert_nfts(connection, nfts)

        return TokenWriteOutcome(
            transfers_written=written,
            nfts_written=nft_written,
            orphaned=orphaned,
        )

    def _known_blocks(self, chain: str, hashes: set[str]) -> set[str]:
        """Which of these block hashes are actually stored."""
        if not hashes:
            return set()
        placeholders = ",".join("?" for _ in hashes)
        rows = self._db.connection.execute(
            f"SELECT block_hash FROM blocks WHERE chain = ? "
            f"AND block_hash IN ({placeholders})",
            (chain, *hashes),
        )
        return {row["block_hash"] for row in rows}

    def _insert_transfers(
        self, connection: sqlite3.Connection, transfers: Sequence[CanonicalTokenTransfer]
    ) -> int:
        if not transfers:
            return 0
        connection.executemany(
            """
            INSERT INTO token_transfers (
                key, chain, tx_hash, log_index, block_key, block_number,
                token, from_address, to_address, value, decimals_known,
                is_mint, is_burn, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO NOTHING
            """,
            [
                (
                    t.key,
                    t.chain,
                    t.tx_hash,
                    t.log_index,
                    f"{t.chain}:{t.block_hash}",
                    t.block_number,
                    t.token.value,
                    t.from_address.value,
                    t.to_address.value,
                    t.value.stored(),
                    1 if t.decimals_known else 0,
                    1 if t.is_mint else 0,
                    1 if t.is_burn else 0,
                    t.source_record_id,
                )
                for t in transfers
            ],
        )
        return len(transfers)

    def _insert_nfts(
        self, connection: sqlite3.Connection, nfts: Sequence[CanonicalNftTransfer]
    ) -> int:
        if not nfts:
            return 0
        connection.executemany(
            """
            INSERT INTO nft_transfers (
                key, chain, tx_hash, log_index, block_key, block_number,
                collection, from_address, to_address, token_id,
                is_mint, is_burn, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO NOTHING
            """,
            [
                (
                    n.key,
                    n.chain,
                    n.tx_hash,
                    n.log_index,
                    f"{n.chain}:{n.block_hash}",
                    n.block_number,
                    n.collection.value,
                    n.from_address.value,
                    n.to_address.value,
                    # Stored as text: a tokenId is a uint256 identifier, and a
                    # truncated one points at a different NFT rather than at a
                    # wrong amount.
                    str(n.token_id),
                    1 if n.is_mint else 0,
                    1 if n.is_burn else 0,
                    n.source_record_id,
                )
                for n in nfts
            ],
        )
        return len(nfts)

    # -- reading ----------------------------------------------------------

    def count(self, chain: str | None = None, *, include_withdrawn: bool = False) -> int:
        sql = [
            "SELECT COUNT(*) FROM token_transfers t "
            "JOIN blocks b ON b.key = t.block_key WHERE 1 = 1"
        ]
        params: list[Any] = []
        if chain is not None:
            sql.append(" AND t.chain = ?")
            params.append(chain)
        if not include_withdrawn:
            sql.append(" AND b.canonical = 1")
        row = self._db.connection.execute("".join(sql), params).fetchone()
        return int(row[0]) if row else 0

    def tokens_seen(self, chain: str, *, limit: int = 25) -> tuple[tuple[str, int], ...]:
        """
        Token contracts by transfer count, busiest first.

        The entry point for a caller with no address in mind: it answers "what
        is actually moving on this chain" without needing a label source.
        """
        rows = self._db.connection.execute(
            """
            SELECT t.token AS token, COUNT(*) AS n
              FROM token_transfers t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
             GROUP BY t.token
             ORDER BY n DESC
             LIMIT ?
            """,
            (chain, limit),
        )
        return tuple((row["token"], int(row["n"])) for row in rows)

    def largest_transfers(
        self,
        chain: str,
        token: str,
        *,
        limit: int = 10,
        include_withdrawn: bool = False,
    ) -> tuple[CanonicalTokenTransfer, ...]:
        """
        Largest transfers **of one token**.

        ``token`` is required rather than optional. Raw amounts carry no
        exponent, so a chain-wide ordering compares USDC's six-decimal units
        against an eighteen-decimal token's and ranks by which contract happens
        to use more digits. Scoping to one token is what makes the comparison
        mean anything.
        """
        if limit <= 0:
            raise ValueError("limit must be > 0")

        sql = [
            """
            SELECT t.* FROM token_transfers t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND t.token = ?
            """
        ]
        if not include_withdrawn:
            sql.append(" AND b.canonical = 1")
        sql.append(" ORDER BY t.value DESC LIMIT ?")

        rows = self._db.connection.execute(
            "".join(sql), (chain, token.lower(), limit)
        )
        return tuple(self._hydrate(row) for row in rows)

    def activity_of(
        self, address: Address, *, limit: int = 50
    ) -> tuple[CanonicalTokenTransfer, ...]:
        """Token transfers where an address is sender or recipient."""
        if limit <= 0:
            raise ValueError("limit must be > 0")

        rows = self._db.connection.execute(
            """
            SELECT t.* FROM token_transfers t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
               AND (t.from_address = ? OR t.to_address = ?)
             ORDER BY t.block_number DESC, t.log_index DESC
             LIMIT ?
            """,
            (address.chain, address.value, address.value, limit),
        )
        return tuple(self._hydrate(row) for row in rows)

    def nft_activity_of(
        self, address: Address, *, limit: int = 50
    ) -> tuple[CanonicalNftTransfer, ...]:
        rows = self._db.connection.execute(
            """
            SELECT n.* FROM nft_transfers n
              JOIN blocks b ON b.key = n.block_key
             WHERE n.chain = ? AND b.canonical = 1
               AND (n.from_address = ? OR n.to_address = ?)
             ORDER BY n.block_number DESC, n.log_index DESC
             LIMIT ?
            """,
            (address.chain, address.value, address.value, limit),
        )
        return tuple(self._hydrate_nft(row) for row in rows)

    def nft_count(self, chain: str | None = None) -> int:
        sql = [
            "SELECT COUNT(*) FROM nft_transfers n "
            "JOIN blocks b ON b.key = n.block_key WHERE b.canonical = 1"
        ]
        params: list[Any] = []
        if chain is not None:
            sql.append(" AND n.chain = ?")
            params.append(chain)
        row = self._db.connection.execute("".join(sql), params).fetchone()
        return int(row[0]) if row else 0

    # -- hydration --------------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> CanonicalTokenTransfer:
        chain = row["chain"]
        return CanonicalTokenTransfer(
            chain=chain,
            tx_hash=row["tx_hash"],
            log_index=int(row["log_index"]),
            block_number=int(row["block_number"]),
            block_hash=str(row["block_key"]).split(":", 1)[-1],
            token=Address.parse(row["token"], chain),
            from_address=Address.parse(row["from_address"], chain),
            to_address=Address.parse(row["to_address"], chain),
            # decimals 0 because the exponent is still unresolved; the flag
            # beside it is what says so rather than the value pretending.
            value=Amount.from_stored(row["value"], 0),
            decimals_known=bool(row["decimals_known"]),
            is_mint=bool(row["is_mint"]),
            is_burn=bool(row["is_burn"]),
            source_record_id=row["source_record_id"],
        )

    def _hydrate_nft(self, row: sqlite3.Row) -> CanonicalNftTransfer:
        chain = row["chain"]
        return CanonicalNftTransfer(
            chain=chain,
            tx_hash=row["tx_hash"],
            log_index=int(row["log_index"]),
            block_number=int(row["block_number"]),
            block_hash=str(row["block_key"]).split(":", 1)[-1],
            collection=Address.parse(row["collection"], chain),
            from_address=Address.parse(row["from_address"], chain),
            to_address=Address.parse(row["to_address"], chain),
            token_id=int(row["token_id"]),
            is_mint=bool(row["is_mint"]),
            is_burn=bool(row["is_burn"]),
            source_record_id=row["source_record_id"],
        )


__all__ = ["SqliteTokenRepository", "TokenWriteOutcome"]
