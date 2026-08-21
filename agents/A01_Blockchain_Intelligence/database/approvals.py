"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.approvals

Purpose:
    Store decoded approval events and read them back for one owner, so the
    approval-risk screen in :mod:`blockchain.security.approval_risk` can run
    against stored data rather than only against a log batch held in memory.

Design goals:
    - Repository pattern; no SQL escapes this module (DR-09)
    - Writes idempotent on the log's own position
    - Reads canonical-only, so a withdrawn block's grants do not surface
    - Grants round-tripped to :class:`DecodedApproval`, the type the replay reads
    - Amounts round-tripped through the padded text form

Notes:
    This is the sibling of :mod:`database.tokens`, and it inherits the same
    two disciplines. Writes are idempotent on ``chain:tx_hash:log_index``: a
    replayed block re-emits identical logs, and ``ON CONFLICT DO NOTHING`` makes
    that a no-op rather than a duplicate row. Records whose block is not stored
    are skipped rather than inserted -- the foreign key would reject them, and
    catching it here lets the rest of the batch land and turns a hard failure
    into a counted gap.

    Reads are canonical-only and deliberately not configurable to include
    withdrawn blocks. An approval on an abandoned branch is a grant that was
    never made on the chain A01 believes in, and surfacing it would tell an
    owner to revoke something that does not exist. Everything the screen needs
    to reason about staleness and breadth is reconstructed here; nothing about
    whether a spender is dangerous is, because that is not a fact this table
    holds.
"""

from __future__ import annotations

import logging
import sqlite3

from dataclasses import dataclass
from typing import Any, Sequence

from blockchain.security.approval_risk import ApprovalKind, DecodedApproval
from normalization.approvals import ApprovalActivity, StoredApproval
from schemas.address import Address
from schemas.amount import Amount

from .connection import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApprovalWriteOutcome:
    """What an approval write actually did."""

    written: int = 0
    #: Records skipped because their block is not stored. Not an error: logs can
    #: arrive for a block that was withdrawn, or that ingestion has not reached.
    #: Counted so a persistent gap between block and approval capture is visible.
    orphaned: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"written": self.written, "orphaned": self.orphaned}


class SqliteApprovalRepository:
    """SQLite-backed storage for decoded approval events."""

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- writing ----------------------------------------------------------

    def save(self, activity: ApprovalActivity) -> ApprovalWriteOutcome:
        """
        Write one batch's approvals atomically.

        Records whose block is not stored are skipped rather than inserted, for
        the reason :meth:`database.tokens.SqliteTokenRepository.save` skips them:
        the foreign key would reject the row, and letting the rest of the batch
        land turns a hard failure into a counted gap.
        """
        if activity.empty:
            return ApprovalWriteOutcome()

        known = self._known_blocks(
            activity.chain, {record.block_hash for record in activity.approvals}
        )
        rows = [record for record in activity.approvals if record.block_hash in known]
        orphaned = len(activity.approvals) - len(rows)

        if orphaned:
            logger.warning(
                "%s: %d approval(s) reference a block that is not stored",
                activity.chain,
                orphaned,
            )

        with self._db.transaction() as connection:
            written = self._insert(connection, activity.source_record_id, rows)

        return ApprovalWriteOutcome(written=written, orphaned=orphaned)

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

    def _insert(
        self,
        connection: sqlite3.Connection,
        source_record_id: str,
        records: Sequence[StoredApproval],
    ) -> int:
        if not records:
            return 0
        connection.executemany(
            """
            INSERT INTO approvals (
                key, chain, tx_hash, log_index, block_key, block_number,
                kind, token, owner, spender, allowance, token_id, approved,
                is_revocation, block_timestamp, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO NOTHING
            """,
            [self._row(source_record_id, record) for record in records],
        )
        return len(records)

    @staticmethod
    def _row(source_record_id: str, record: StoredApproval) -> tuple[Any, ...]:
        approval = record.approval
        log_index = approval.log_index if approval.log_index is not None else 0
        return (
            f"{approval.chain}:{approval.tx_hash}:{log_index}",
            approval.chain,
            approval.tx_hash,
            log_index,
            f"{approval.chain}:{record.block_hash}",
            approval.block_number if approval.block_number is not None else 0,
            str(approval.kind),
            approval.token.value,
            approval.owner.value,
            approval.spender.value,
            # Zero-padded decimal, ERC-20 only; NULL for the two ERC-721 forms,
            # where a stored zero would read back as a revocation.
            approval.allowance.stored() if approval.allowance is not None else None,
            str(approval.token_id) if approval.token_id is not None else None,
            (1 if approval.approved else 0) if approval.approved is not None else None,
            1 if approval.is_revocation else 0,
            approval.block_timestamp,
            source_record_id,
        )

    # -- reading ----------------------------------------------------------

    def approvals_for_owner(self, owner: Address) -> tuple[DecodedApproval, ...]:
        """
        Every stored approval an owner emitted, in chain order.

        Returned as :class:`DecodedApproval` so the caller can hand them
        straight to :func:`blockchain.security.approval_risk.exposure_for_owner`,
        which replays them into the live set. Canonical blocks only: a grant on
        a withdrawn block was never made on the chain A01 believes in.
        """
        rows = self._db.connection.execute(
            """
            SELECT a.* FROM approvals a
              JOIN blocks b ON b.key = a.block_key
             WHERE a.chain = ? AND a.owner = ? AND b.canonical = 1
             ORDER BY a.block_number ASC, a.log_index ASC
            """,
            (owner.chain, owner.value),
        )
        return tuple(self._hydrate(row) for row in rows)

    def count(self, chain: str | None = None, *, include_withdrawn: bool = False) -> int:
        sql = [
            "SELECT COUNT(*) FROM approvals a "
            "JOIN blocks b ON b.key = a.block_key WHERE 1 = 1"
        ]
        params: list[Any] = []
        if chain is not None:
            sql.append(" AND a.chain = ?")
            params.append(chain)
        if not include_withdrawn:
            sql.append(" AND b.canonical = 1")
        row = self._db.connection.execute("".join(sql), params).fetchone()
        return int(row[0]) if row else 0

    # -- hydration --------------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> DecodedApproval:
        chain = row["chain"]
        allowance = (
            Amount.from_stored(row["allowance"], 0)
            if row["allowance"] is not None
            else None
        )
        return DecodedApproval(
            kind=ApprovalKind(row["kind"]),
            chain=chain,
            token=Address.parse(row["token"], chain),
            owner=Address.parse(row["owner"], chain),
            spender=Address.parse(row["spender"], chain),
            allowance=allowance,
            token_id=int(row["token_id"]) if row["token_id"] is not None else None,
            approved=bool(row["approved"]) if row["approved"] is not None else None,
            block_number=int(row["block_number"]),
            log_index=int(row["log_index"]),
            tx_hash=row["tx_hash"],
            block_timestamp=row["block_timestamp"],
        )


__all__ = ["ApprovalWriteOutcome", "SqliteApprovalRepository"]
