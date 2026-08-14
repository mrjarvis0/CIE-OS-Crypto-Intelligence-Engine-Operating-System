"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.analytics

Purpose:
    Aggregate reads over stored history, for the skills layer.

Design goals:
    - SQL stays inside a repository, per DR-09
    - Every result states the window it was computed over
    - Canonical-only by default, like every other read path
    - No interpretation: counts and sums, never judgements
    - Read-only; nothing here writes

Notes:
    Separate from :mod:`database.repositories` because the two answer different
    questions. That module stores and retrieves individual records; this one
    aggregates across them. Keeping them apart also keeps the write path small
    enough to audit, which matters more than co-locating everything that
    touches the same tables.

    Every method returns the height window it used. This is not decoration. The
    database holds only what was ingested, so an aggregate computed over it is a
    statement about *storage*, not about the chain -- and the difference is
    invisible in the number itself. "This address has two transactions" read
    from a database containing four blocks is true of the database and almost
    certainly false of Ethereum. The window travels with the figure so the layer
    above can refuse to draw a conclusion the window cannot support.

    Nothing here interprets. A summary reports that an address sent three
    transactions totalling some amount; whether that makes it a whale, dormant,
    or anything else is decided in ``skills/`` against thresholds this module
    knows nothing about.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from normalization.quality import BOUNDED_CHECKS
from schemas.address import Address
from schemas.amount import Amount

from .connection import Database
from .repositories import parse_stored_time

logger = logging.getLogger(__name__)


def _bounded(reason: Any) -> bool:
    """
    Whether an incomplete block's stored reason states its own boundary.

    An empty reason on an incomplete block is not treated as bounded. That is
    every block written before the reason column existed, and the truthful
    reading of one is "this was incomplete and nobody recorded why" -- which is
    exactly the case a negative claim must not be built on.
    """
    checks = [check for check in str(reason or "").split(",") if check]
    return bool(checks) and all(check in BOUNDED_CHECKS for check in checks)

#: Cap on rows pulled for a value population. Percentile estimation converges
#: long before this, and an unbounded scan would grow with chain history.
DEFAULT_POPULATION_LIMIT = 5_000

#: Cap on rows summed for one address's totals.
#:
#: Measured at ~4-5 microseconds per row, so this bounds a summary at roughly a
#: quarter second however much history is stored. Without it the cost is linear
#: in an address's lifetime activity: 100,000 transfers measured at 428ms, and
#: an exchange hot wallet has orders of magnitude more.
#:
#: The alternative was a denormalised running total maintained at write time,
#: which would make this O(1). It was rejected for now: the total would have to
#: be decremented on reorg withdrawal, putting a new consistency invariant in
#: the exact place where getting it wrong corrupts history silently. A bounded
#: exact sum that says it is bounded is worth more than an unbounded one that
#: is occasionally wrong.
MAX_SUM_ROWS = 50_000


@dataclass(frozen=True, slots=True)
class HeightWindow:
    """
    The span of canonical history an aggregate was computed over.

    ``blocks`` is counted rather than derived from the bounds, because stored
    history is frequently not contiguous -- a backfill in progress, or a range
    that was never fetched, leaves holes. Reporting ``to - from + 1`` would
    claim coverage that is not there.
    """

    chain: str
    from_height: int | None = None
    to_height: int | None = None
    blocks: int = 0
    #: Of ``blocks``, how many were stored whole. A block whose logs were
    #: requested and refused is stored and canonical but not complete, and the
    #: difference is what separates "the chain did nothing here" from "A01
    #: never found out".
    complete_blocks: int = 0
    #: Of the rest, how many are incomplete only because a stated floor dropped
    #: their small transactions. Counted apart from :attr:`unfetched_blocks`
    #: because the two license different claims: this one is whole above its
    #: floor, that one is silent about everything it is missing.
    selective_blocks: int = 0
    #: The highest floor in force anywhere in the window, or None if no block
    #: was filtered. The highest, not the mean or the latest: a claim about the
    #: window is only as strong as its weakest block, and a floor that was
    #: raised for one hour under budget pressure bounds the whole window.
    capture_floor: Amount | None = None

    @property
    def empty(self) -> bool:
        return self.blocks == 0

    @property
    def incomplete_blocks(self) -> int:
        return self.blocks - self.complete_blocks

    @property
    def unfetched_blocks(self) -> int:
        """
        Blocks incomplete for a reason that states no boundary.

        The ones that cannot be reasoned around: their transfers were requested
        and not obtained, so nothing is known about what is missing from them.
        """
        return self.blocks - self.complete_blocks - self.selective_blocks

    @property
    def all_complete(self) -> bool:
        """
        Whether every block in the window was stored whole.

        Separate from :attr:`contiguous`, which asks a different question. A
        window can hold every height in its span and still be unable to support
        a negative claim, because a height being *present* says nothing about
        the height being *whole*.
        """
        return self.blocks > 0 and self.complete_blocks == self.blocks

    @property
    def all_captured(self) -> bool:
        """
        Whether nothing was lost that was not dropped on purpose.

        The weaker sibling of :attr:`all_complete`, and the one selective
        capture needs. Every block here is whole at or above
        :attr:`capture_floor`; what is missing below it is missing by decision,
        and the decision is recorded. So a negative claim *bounded by the floor*
        survives, while an unqualified one still does not.

        Both are true for a window captured whole -- there the floor is nothing
        and the bounded claim is the unbounded one.
        """
        return self.blocks > 0 and self.unfetched_blocks == 0

    @property
    def span(self) -> int:
        """Heights between the bounds, holes included."""
        if self.from_height is None or self.to_height is None:
            return 0
        return self.to_height - self.from_height + 1

    @property
    def contiguous(self) -> bool:
        """
        Whether every height in the span is present.

        False means the window has gaps, so an aggregate over it has omitted
        blocks that were never stored -- and a count from it is a floor, not a
        total.
        """
        return self.blocks > 0 and self.blocks == self.span

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "from_height": self.from_height,
            "to_height": self.to_height,
            "blocks": self.blocks,
            "complete_blocks": self.complete_blocks,
            "incomplete_blocks": self.incomplete_blocks,
            "selective_blocks": self.selective_blocks,
            "unfetched_blocks": self.unfetched_blocks,
            "capture_floor": str(self.capture_floor.raw) if self.capture_floor else None,
            "span": self.span,
            "contiguous": self.contiguous,
            "all_complete": self.all_complete,
            "all_captured": self.all_captured,
        }


@dataclass(frozen=True, slots=True)
class AddressSummary:
    """
    Everything storage knows about one address's activity.

    Counts and sums only. ``window`` is what stops the numbers being read as
    the address's whole history.
    """

    address: Address
    window: HeightWindow
    sent_count: int = 0
    received_count: int = 0
    sent_total: Amount = Amount(0)
    received_total: Amount = Amount(0)
    first_height: int | None = None
    last_height: int | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_outbound_at: datetime | None = None
    counterparties: int = 0
    #: True when a total was computed over a capped set of rows, making it a
    #: floor rather than the whole figure. Carried rather than hidden: a
    #: partial sum presented as a balance is the error this package exists to
    #: avoid elsewhere, and capping it here would reintroduce it.
    totals_capped: bool = False

    @property
    def transaction_count(self) -> int:
        return self.sent_count + self.received_count

    @property
    def seen(self) -> bool:
        return self.transaction_count > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address.value,
            "chain": self.address.chain,
            "window": self.window.as_dict(),
            "sent_count": self.sent_count,
            "received_count": self.received_count,
            "transaction_count": self.transaction_count,
            "sent_total": self.sent_total.as_dict(),
            "received_total": self.received_total.as_dict(),
            "first_height": self.first_height,
            "last_height": self.last_height,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "last_outbound_at": (
                self.last_outbound_at.isoformat() if self.last_outbound_at else None
            ),
            "counterparties": self.counterparties,
            "totals_capped": self.totals_capped,
        }


@dataclass(frozen=True, slots=True)
class HourQuality:
    """
    How much of one hour was actually captured.

    Travels beside any figure computed over that hour. A total drawn from
    selectively captured blocks is bounded by the floor those blocks were
    filtered at, and a total drawn from an hour with an unfetched block is a
    floor of unknown depth -- neither is visible in the figure itself.
    """

    blocks: int = 0
    complete_blocks: int = 0
    capture_floor: Amount | None = None

    @property
    def all_complete(self) -> bool:
        return self.blocks > 0 and self.complete_blocks == self.blocks

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks,
            "complete_blocks": self.complete_blocks,
            "all_complete": self.all_complete,
            "capture_floor": (
                str(self.capture_floor.raw) if self.capture_floor is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class TransferRecord:
    """One stored transfer, flattened for analysis."""

    tx_hash: str
    height: int
    from_address: str
    to_address: str | None
    value: Amount
    at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "height": self.height,
            "from": self.from_address,
            "to": self.to_address,
            "value": self.value.as_dict(),
            "at": self.at.isoformat() if self.at else None,
        }


class SqliteAnalyticsRepository:
    """
    Read-only aggregate queries over stored chain history.

    Every method is canonical-only. Abandoned blocks are still in the table by
    design, and an aggregate that included them would double-count the reorged
    range -- silently, and in whichever direction the fork happened to go.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- window -----------------------------------------------------------

    def window(self, chain: str) -> HeightWindow:
        """
        The canonical height range stored for a chain, and how many blocks.

        Grouped by incompleteness reason rather than summed with a ``CASE``
        over one, because deciding which reasons still permit a negative claim
        is policy, and policy written into SQL is policy nobody can find. The
        grouping returns one row per distinct combination of reasons -- a
        handful, whatever the chain's height -- and the classification happens
        against :data:`~normalization.quality.BOUNDED_CHECKS` in Python, where
        it is one import away from the rules it enforces.
        """
        rows = self._db.connection.execute(
            """
            SELECT complete,
                   incomplete_reason,
                   COUNT(*)          AS n,
                   MIN(number)       AS lo,
                   MAX(number)       AS hi,
                   MAX(capture_floor) AS floor
              FROM blocks
             WHERE chain = ? AND canonical = 1
             GROUP BY complete, incomplete_reason
            """,
            (chain,),
        ).fetchall()

        blocks = complete = selective = 0
        lows: list[int] = []
        highs: list[int] = []
        floors: list[str] = []

        for row in rows:
            count = int(row["n"])
            blocks += count
            lows.append(int(row["lo"]))
            highs.append(int(row["hi"]))
            if row["floor"]:
                floors.append(row["floor"])

            if row["complete"]:
                complete += count
            elif _bounded(row["incomplete_reason"]):
                selective += count

        if blocks == 0:
            return HeightWindow(chain=chain)

        return HeightWindow(
            chain=chain,
            from_height=min(lows),
            to_height=max(highs),
            blocks=blocks,
            complete_blocks=complete,
            selective_blocks=selective,
            # Padded text, so the string maximum is the numeric maximum.
            capture_floor=Amount.from_stored(max(floors)) if floors else None,
        )

    def chains(self) -> tuple[str, ...]:
        """Chains with at least one canonical block stored."""
        rows = self._db.connection.execute(
            "SELECT DISTINCT chain FROM blocks WHERE canonical = 1 ORDER BY chain"
        )
        return tuple(row["chain"] for row in rows)

    # -- populations ------------------------------------------------------

    def transfer_values(
        self, chain: str, *, limit: int = DEFAULT_POPULATION_LIMIT
    ) -> tuple[int, ...]:
        """
        Transfer values for the chain, largest first, as raw integers.

        The population a percentile threshold is computed against. Zero-value
        transactions are excluded: contract calls that move nothing are the
        bulk of chain traffic, and leaving them in drags every percentile down
        until a routine transfer clears the 99.9th.
        """
        if limit <= 0:
            raise ValueError("limit must be > 0")

        rows = self._db.connection.execute(
            """
            SELECT t.value FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
               AND t.value != ?
             ORDER BY t.value DESC
             LIMIT ?
            """,
            (chain, Amount(0).stored(), limit),
        )
        return tuple(int(row["value"], 10) for row in rows)

    def transfers_in_window(
        self,
        chain: str,
        *,
        from_height: int | None = None,
        to_height: int | None = None,
        min_value: Amount | None = None,
        limit: int = 500,
    ) -> tuple[TransferRecord, ...]:
        """Transfers within a height range, largest first."""
        if limit <= 0:
            raise ValueError("limit must be > 0")

        sql = [
            """
            SELECT t.tx_hash, t.block_number, t.from_address, t.to_address,
                   t.value, t.value_decimals, b.timestamp
              FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
            """
        ]
        params: list[Any] = [chain]

        if from_height is not None:
            sql.append(" AND t.block_number >= ?")
            params.append(from_height)
        if to_height is not None:
            sql.append(" AND t.block_number <= ?")
            params.append(to_height)
        if min_value is not None:
            sql.append(" AND t.value >= ?")
            params.append(min_value.stored())

        sql.append(" ORDER BY t.value DESC LIMIT ?")
        params.append(limit)

        rows = self._db.connection.execute("".join(sql), params)
        return tuple(self._hydrate_transfer(row) for row in rows)

    def transfers_by_height(
        self,
        chain: str,
        *,
        from_height: int | None = None,
        to_height: int | None = None,
        limit: int = MAX_SUM_ROWS,
    ) -> tuple[tuple[TransferRecord, ...], bool]:
        """
        Every stored transfer in a height range, in chain order.

        Distinct from :meth:`transfers_in_window`, which returns the largest and
        is the right read for a whale threshold. Flow direction is not a
        question about the largest transfers: an exchange's deposits are mostly
        ordinary-sized, and ranking by value would compute a total from the tail
        and report it as the whole.

        Ordered by height and index because it is fed to an hourly rollup, and
        capped like every other unbounded scan here. Returns
        ``(transfers, capped)``; a capped read makes every total drawn from it a
        floor, and the caller has to be able to say so.
        """
        if limit <= 0:
            raise ValueError("limit must be > 0")

        sql = [
            """
            SELECT t.tx_hash, t.block_number, t.from_address, t.to_address,
                   t.value, t.value_decimals, b.timestamp
              FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
            """
        ]
        params: list[Any] = [chain]

        if from_height is not None:
            sql.append(" AND t.block_number >= ?")
            params.append(from_height)
        if to_height is not None:
            sql.append(" AND t.block_number <= ?")
            params.append(to_height)

        sql.append(" ORDER BY t.block_number ASC, t.tx_index ASC LIMIT ?")
        params.append(limit + 1)

        rows = self._db.connection.execute("".join(sql), params).fetchall()
        capped = len(rows) > limit
        if capped:
            rows = rows[:limit]
            logger.warning(
                "%s: transfer scan capped at %d rows; totals from it are floors",
                chain,
                limit,
            )

        return tuple(self._hydrate_transfer(row) for row in rows), capped

    def hourly_block_quality(
        self,
        chain: str,
        *,
        from_height: int | None = None,
        to_height: int | None = None,
    ) -> dict[datetime, HourQuality]:
        """
        Per hour: how many blocks were stored, how many whole, and the floor.

        Read from ``blocks`` rather than derived from the transfers themselves,
        because the transfers cannot report what is missing. An hour whose
        blocks were captured selectively holds only the transfers at or above a
        floor, and an hour with an unfetched block holds an unknown share of
        them -- neither is visible in a list of what *is* stored, which is
        exactly why a flow total needs this beside it.
        """
        sql = [
            """
            SELECT timestamp, complete, capture_floor
              FROM blocks
             WHERE chain = ? AND canonical = 1
            """
        ]
        params: list[Any] = [chain]
        if from_height is not None:
            sql.append(" AND number >= ?")
            params.append(from_height)
        if to_height is not None:
            sql.append(" AND number <= ?")
            params.append(to_height)

        counts: dict[datetime, list[Any]] = {}
        for row in self._db.connection.execute("".join(sql), params):
            at = parse_stored_time(row["timestamp"])
            if at is None:  # pragma: no cover - timestamp is NOT NULL
                continue
            hour = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
            entry = counts.setdefault(hour, [0, 0, None])
            entry[0] += 1
            entry[1] += 1 if row["complete"] else 0
            floor = row["capture_floor"]
            if floor:
                # Highest floor in the hour bounds every claim drawn from it.
                current = entry[2]
                entry[2] = floor if current is None or floor > current else current

        return {
            hour: HourQuality(
                blocks=entry[0],
                complete_blocks=entry[1],
                capture_floor=Amount.from_stored(entry[2]) if entry[2] else None,
            )
            for hour, entry in counts.items()
        }

    def token_flow(
        self, address: Address, *, limit: int = MAX_SUM_ROWS
    ) -> dict[str, tuple[int, int, int]]:
        """
        Per-token inflow and outflow for one address, in raw base units.

        Keyed by token contract and never aggregated across tokens: raw amounts
        carry no exponent, so a total spanning a 6-decimal and an 18-decimal
        token is arithmetic on incompatible units. Returns
        ``{token: (gross_in, gross_out, transfer_count)}``.

        Summed in Python for the same reason native totals are -- the values
        are padded text precisely because they exceed 64 bits, and SQL ``SUM()``
        would coerce them to a float.
        """
        rows = self._db.connection.execute(
            """
            SELECT t.token AS token, t.from_address AS sender,
                   t.to_address AS recipient, t.value AS value
              FROM token_transfers t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
               AND (t.from_address = ? OR t.to_address = ?)
             ORDER BY t.value DESC
             LIMIT ?
            """,
            (address.chain, address.value, address.value, limit),
        )

        flows: dict[str, tuple[int, int, int]] = {}
        for row in rows:
            token = row["token"]
            raw = int(row["value"], 10)
            gross_in, gross_out, count = flows.get(token, (0, 0, 0))
            if row["sender"] == address.value:
                gross_out += raw
            if row["recipient"] == address.value:
                gross_in += raw
            flows[token] = (gross_in, gross_out, count + 1)

        return flows

    def token_totals(self, chain: str, *, limit: int = 25) -> tuple[dict[str, Any], ...]:
        """
        Busiest token contracts and their movement counts.

        The entry point for a caller with no address in mind. Counts only --
        summing value across contracts would be the cross-token error again.
        """
        rows = self._db.connection.execute(
            """
            SELECT t.token AS token, COUNT(*) AS transfers,
                   SUM(t.is_mint) AS mints, SUM(t.is_burn) AS burns
              FROM token_transfers t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
             GROUP BY t.token
             ORDER BY transfers DESC
             LIMIT ?
            """,
            (chain, limit),
        )
        return tuple(
            {
                "token": row["token"],
                "transfers": int(row["transfers"]),
                "mints": int(row["mints"] or 0),
                "burns": int(row["burns"] or 0),
            }
            for row in rows
        )

    # -- address ----------------------------------------------------------

    def address_summary(self, address: Address) -> AddressSummary:
        """
        Counts, sums and timestamps for one address over stored history.

        Two queries rather than one: the sent and received sides need different
        groupings, and a single query with conditional aggregates over an OR
        predicate cannot use either directional index -- it degrades to a scan
        of the whole table.
        """
        chain = address.chain
        window = self.window(chain)

        sent = self._db.connection.execute(
            """
            SELECT COUNT(*) AS n,
                   MIN(t.block_number) AS lo, MAX(t.block_number) AS hi,
                   MAX(b.timestamp) AS last_at
              FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1 AND t.from_address = ?
            """,
            (chain, address.value),
        ).fetchone()

        received = self._db.connection.execute(
            """
            SELECT COUNT(*) AS n,
                   MIN(t.block_number) AS lo, MAX(t.block_number) AS hi,
                   MAX(b.timestamp) AS last_at
              FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1 AND t.to_address = ?
            """,
            (chain, address.value),
        ).fetchone()

        # Sums are accumulated in Python, not SQL. The values are padded text
        # precisely because they exceed a 64-bit integer, so SUM() would either
        # coerce them to a float -- losing exactness in the digits that matter --
        # or add them as strings.
        sent_total, sent_capped = self._sum_values(chain, address.value, outgoing=True)
        received_total, received_capped = self._sum_values(
            chain, address.value, outgoing=False
        )

        counterparties = self._db.connection.execute(
            """
            SELECT COUNT(DISTINCT party) AS n FROM (
                SELECT t.to_address AS party FROM transactions t
                  JOIN blocks b ON b.key = t.block_key
                 WHERE t.chain = ? AND b.canonical = 1
                   AND t.from_address = ? AND t.to_address IS NOT NULL
                UNION
                SELECT t.from_address AS party FROM transactions t
                  JOIN blocks b ON b.key = t.block_key
                 WHERE t.chain = ? AND b.canonical = 1 AND t.to_address = ?
            )
            """,
            (chain, address.value, chain, address.value),
        ).fetchone()

        heights = [
            value
            for value in (sent["lo"], sent["hi"], received["lo"], received["hi"])
            if value is not None
        ]
        timestamps = [
            parse_stored_time(value)
            for value in (sent["last_at"], received["last_at"])
            if value
        ]
        first_at = self._first_seen(chain, address.value)

        return AddressSummary(
            address=address,
            window=window,
            sent_count=int(sent["n"] or 0),
            received_count=int(received["n"] or 0),
            sent_total=sent_total,
            received_total=received_total,
            first_height=min(heights) if heights else None,
            last_height=max(heights) if heights else None,
            first_seen_at=first_at,
            last_seen_at=max(timestamps) if timestamps else None,
            last_outbound_at=parse_stored_time(sent["last_at"]) if sent["last_at"] else None,
            counterparties=int(counterparties["n"] or 0),
            totals_capped=sent_capped or received_capped,
        )

    def _sum_values(
        self, chain: str, address: str, *, outgoing: bool
    ) -> tuple[Amount, bool]:
        """
        Total value on one side of an address, summed exactly and bounded.

        Summed in Python rather than with SQL ``SUM()`` because the values are
        padded text precisely so they can exceed a 64-bit integer; ``SUM()``
        would coerce them to a float and lose the digits that distinguish a
        large transfer from an enormous one.

        That makes the cost linear in the address's activity, so it is capped
        at :data:`MAX_SUM_ROWS` and the caller is told when the cap bound the
        answer. Ordered largest-first so a capped total captures the transfers
        that matter rather than an arbitrary slice.

        Returns ``(total, capped)``.
        """
        column = "from_address" if outgoing else "to_address"
        rows = self._db.connection.execute(
            f"""
            SELECT t.value FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1 AND t.{column} = ?
             ORDER BY t.value DESC
             LIMIT ?
            """,
            (chain, address, MAX_SUM_ROWS + 1),
        ).fetchall()

        capped = len(rows) > MAX_SUM_ROWS
        if capped:
            rows = rows[:MAX_SUM_ROWS]
            logger.warning(
                "%s: totals for %s capped at %d rows; the figure is a floor",
                chain,
                address,
                MAX_SUM_ROWS,
            )

        return Amount(sum(int(row["value"], 10) for row in rows)), capped

    def _first_seen(self, chain: str, address: str) -> datetime | None:
        row = self._db.connection.execute(
            """
            SELECT MIN(b.timestamp) AS at FROM transactions t
              JOIN blocks b ON b.key = t.block_key
             WHERE t.chain = ? AND b.canonical = 1
               AND (t.from_address = ? OR t.to_address = ?)
            """,
            (chain, address, address),
        ).fetchone()
        return parse_stored_time(row["at"]) if row and row["at"] else None

    # -- hydration --------------------------------------------------------

    @staticmethod
    def _hydrate_transfer(row: Any) -> TransferRecord:
        return TransferRecord(
            tx_hash=row["tx_hash"],
            height=int(row["block_number"]),
            from_address=row["from_address"],
            to_address=row["to_address"],
            value=Amount.from_stored(row["value"], int(row["value_decimals"])),
            at=parse_stored_time(row["timestamp"]) if row["timestamp"] else None,
        )


__all__ = [
    "DEFAULT_POPULATION_LIMIT",
    "MAX_SUM_ROWS",
    "AddressSummary",
    "HeightWindow",
    "HourQuality",
    "SqliteAnalyticsRepository",
    "TransferRecord",
]
