"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    tiers.warm

Purpose:
    Tier W. Exchange flow rolled up to the hour: what went into a labelled
    exchange address, what came out, and what merely moved between them.

Design goals:
    - One row per chain-hour per operator, whatever the traffic
    - Deposits, withdrawals and internal movement kept apart, never netted
    - Completeness and capture floor travel with the row
    - Idempotent re-rolls: an hour recomputed replaces itself
    - Exact arithmetic; values summed in Python, never by SQL

Notes:
    This is the tier a baseline is made of. "Binance took in 4,800 ETH this
    hour" is not a signal on its own -- the signal is that it normally takes in
    1,200 -- and the comparison needs history no live call can return. Ninety
    days of hourly rows is a few megabytes per chain, which is what makes
    keeping them affordable.

    **Netting is refused.** A row holds inflow and outflow separately and a net
    figure is derived on the way out, because the two are different events with
    different meanings and an hour of 4,000 in / 4,000 out is not a quiet hour.
    Storing only the difference would destroy exactly the fact that makes the
    hour interesting.

    **Internal movement is neither.** A transfer between two labelled addresses
    -- one exchange's hot wallet to its own cold storage, or one exchange to
    another -- is not a user depositing or withdrawing. Counted as inflow it
    makes a rebalance look like incoming sell pressure, which is the single most
    common way an exchange-flow figure misleads. It is counted, kept, and
    excluded from both directions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from database.connection import Database
from schemas.amount import Amount

from .retention import Tier


def _iso(value: datetime) -> str:
    return value.isoformat()


def hour_of(moment: datetime) -> datetime:
    """
    The UTC hour a timestamp belongs to.

    UTC always, for the reason the call ledger uses it: an hour bucket on local
    time is duplicated or skipped twice a year, and a baseline with two 02:00
    buckets one day a year is a baseline with a hole in it.
    """
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class ExchangeFlowHour:
    """
    One operator's hour on one chain.

    ``addresses`` is how many of that operator's labelled addresses actually
    moved value in the hour, not how many are labelled. A figure drawn from
    three of Binance's 118 addresses is a different claim from one drawn from
    all of them, and only the first number says which.
    """

    chain: str
    hour_start: datetime
    entity: str
    inflow_count: int = 0
    inflow_value: Amount = Amount(0)
    outflow_count: int = 0
    outflow_value: Amount = Amount(0)
    internal_count: int = 0
    internal_value: Amount = Amount(0)
    addresses: int = 0
    blocks: int = 0
    complete_blocks: int = 0
    capture_floor: Amount | None = None
    first_number: int = 0
    last_number: int = 0
    label_source: str = ""
    rolled_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("a flow hour must name its chain")
        if not self.entity.strip():
            raise ValueError("a flow hour must name the operator it describes")
        if self.complete_blocks > self.blocks:
            raise ValueError(
                f"complete_blocks {self.complete_blocks} exceeds blocks {self.blocks}"
            )

    @property
    def key(self) -> str:
        return f"{self.chain}:{_iso(self.hour_start)}:{self.entity}"

    @property
    def transfers(self) -> int:
        """Every transfer this row saw, internal ones included."""
        return self.inflow_count + self.outflow_count + self.internal_count

    @property
    def net_value(self) -> int:
        """
        Deposits minus withdrawals, in the chain's smallest unit.

        A plain integer rather than an :class:`Amount`, because it is signed and
        an on-chain quantity is not. Negative means more left than arrived.
        """
        return self.inflow_value.raw - self.outflow_value.raw

    @property
    def all_complete(self) -> bool:
        return self.blocks > 0 and self.complete_blocks == self.blocks

    @property
    def bounded(self) -> bool:
        """True when a floor was in force, so the totals are floors themselves."""
        return self.capture_floor is not None and self.capture_floor.raw > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "hour_start": _iso(self.hour_start),
            "entity": self.entity,
            "inflow_count": self.inflow_count,
            "inflow_value": str(self.inflow_value.raw),
            "outflow_count": self.outflow_count,
            "outflow_value": str(self.outflow_value.raw),
            "internal_count": self.internal_count,
            "internal_value": str(self.internal_value.raw),
            "net_value": str(self.net_value),
            "addresses": self.addresses,
            "blocks": self.blocks,
            "complete_blocks": self.complete_blocks,
            "all_complete": self.all_complete,
            "capture_floor": (
                str(self.capture_floor.raw) if self.capture_floor is not None else None
            ),
            "range": [self.first_number, self.last_number],
            "label_source": self.label_source,
        }


@dataclass(frozen=True, slots=True)
class FlowTotals:
    """
    Several hours summed, for one chain or one operator.

    Carries the same completeness fields as the rows it came from. A total over
    a window where one hour was captured selectively is bounded by that hour's
    floor, and the reader has to be able to see it.
    """

    chain: str
    entity: str = ""
    hours: int = 0
    inflow_count: int = 0
    inflow_value: Amount = Amount(0)
    outflow_count: int = 0
    outflow_value: Amount = Amount(0)
    internal_count: int = 0
    internal_value: Amount = Amount(0)
    blocks: int = 0
    complete_blocks: int = 0
    capture_floor: Amount | None = None
    first_hour: datetime | None = None
    last_hour: datetime | None = None

    @property
    def net_value(self) -> int:
        return self.inflow_value.raw - self.outflow_value.raw

    @property
    def all_complete(self) -> bool:
        return self.blocks > 0 and self.complete_blocks == self.blocks

    @property
    def direction(self) -> str:
        """
        ``inflow``, ``outflow`` or ``balanced``. A description, not a forecast.

        Deliberately not called bullish or bearish. Deposits into an exchange
        are consistent with an intent to sell and with a dozen other things --
        collateral, market making, a custody move -- and naming the intent is
        the line ``docs/intelligence/evidence-standard.md`` draws.
        """
        if self.net_value > 0:
            return "inflow"
        if self.net_value < 0:
            return "outflow"
        return "balanced"

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "entity": self.entity or "all",
            "hours": self.hours,
            "inflow_count": self.inflow_count,
            "inflow_value": str(self.inflow_value.raw),
            "outflow_count": self.outflow_count,
            "outflow_value": str(self.outflow_value.raw),
            "internal_count": self.internal_count,
            "internal_value": str(self.internal_value.raw),
            "net_value": str(self.net_value),
            "direction": self.direction,
            "blocks": self.blocks,
            "complete_blocks": self.complete_blocks,
            "all_complete": self.all_complete,
            "capture_floor": (
                str(self.capture_floor.raw) if self.capture_floor is not None else None
            ),
            "first_hour": _iso(self.first_hour) if self.first_hour else None,
            "last_hour": _iso(self.last_hour) if self.last_hour else None,
        }


class ExchangeFlowRepository:
    """
    Reads and writes Tier W exchange-flow rows.

    Writes replace rather than ignore, which is the opposite of every other
    aggregate here and is deliberate. A block aggregate summarises a block that
    cannot change; an hour of flow summarises whatever transfers were stored
    when the roll ran, and a later roll over a fuller window is a better answer
    to the same question. Ignoring it would freeze the first partial roll of
    every hour permanently.
    """

    tier = Tier.WARM

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- writing ----------------------------------------------------------

    def save(self, hour: ExchangeFlowHour) -> bool:
        """Store one hour. Returns True when the row is new."""
        with self._db.transaction() as connection:
            return self._save(connection, hour)

    def save_many(self, hours: Sequence[ExchangeFlowHour]) -> tuple[int, int]:
        """Store a batch in one transaction. Returns ``(inserted, replaced)``."""
        inserted = 0
        with self._db.transaction() as connection:
            for hour in hours:
                if self._save(connection, hour):
                    inserted += 1
        return inserted, len(hours) - inserted

    @staticmethod
    def _save(connection: Any, hour: ExchangeFlowHour) -> bool:
        existed = connection.execute(
            "SELECT 1 FROM exchange_flow_hourly WHERE key = ?", (hour.key,)
        ).fetchone() is not None

        connection.execute(
            """
            INSERT INTO exchange_flow_hourly (
                key, chain, hour_start, entity,
                inflow_count, inflow_value, outflow_count, outflow_value,
                internal_count, internal_value,
                addresses, blocks, complete_blocks, capture_floor,
                first_number, last_number, label_source, rolled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                inflow_count    = excluded.inflow_count,
                inflow_value    = excluded.inflow_value,
                outflow_count   = excluded.outflow_count,
                outflow_value   = excluded.outflow_value,
                internal_count  = excluded.internal_count,
                internal_value  = excluded.internal_value,
                addresses       = excluded.addresses,
                blocks          = excluded.blocks,
                complete_blocks = excluded.complete_blocks,
                capture_floor   = excluded.capture_floor,
                first_number    = excluded.first_number,
                last_number     = excluded.last_number,
                label_source    = excluded.label_source,
                rolled_at       = excluded.rolled_at
            """,
            (
                hour.key,
                hour.chain,
                _iso(hour.hour_start),
                hour.entity,
                hour.inflow_count,
                hour.inflow_value.stored(),
                hour.outflow_count,
                hour.outflow_value.stored(),
                hour.internal_count,
                hour.internal_value.stored(),
                hour.addresses,
                hour.blocks,
                hour.complete_blocks,
                # Padded, so MAX() over a window is the highest floor rather
                # than the longest string -- the same trap `blocks` fell into.
                hour.capture_floor.stored() if hour.capture_floor is not None else "",
                hour.first_number,
                hour.last_number,
                hour.label_source,
                _iso(hour.rolled_at or datetime.now(UTC)),
            ),
        )
        return not existed

    # -- reading ----------------------------------------------------------

    def hours(
        self,
        chain: str,
        *,
        entity: str = "",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> tuple[ExchangeFlowHour, ...]:
        """Stored hours, most recent first."""
        sql = ["SELECT * FROM exchange_flow_hourly WHERE chain = ?"]
        params: list[Any] = [chain]
        if entity:
            sql.append(" AND entity = ?")
            params.append(entity)
        if start is not None:
            sql.append(" AND hour_start >= ?")
            params.append(_iso(hour_of(start)))
        if end is not None:
            sql.append(" AND hour_start <= ?")
            params.append(_iso(hour_of(end)))
        sql.append(" ORDER BY hour_start DESC, entity ASC LIMIT ?")
        params.append(limit)

        rows = self._db.connection.execute("".join(sql), params)
        return tuple(self._hydrate(row) for row in rows)

    def totals(
        self,
        chain: str,
        *,
        entity: str = "",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> FlowTotals:
        """
        A window summed.

        Values are summed in Python. They are padded text precisely because they
        exceed a 64-bit integer, and SQL ``SUM()`` over that column raises
        rather than truncating -- which any window holding more than about nine
        ether would trigger.
        """
        rows = self.hours(chain, entity=entity, start=start, end=end, limit=100_000)
        if not rows:
            return FlowTotals(chain=chain, entity=entity)

        floors = [row.capture_floor for row in rows if row.capture_floor is not None]
        starts = [row.hour_start for row in rows]

        return FlowTotals(
            chain=chain,
            entity=entity,
            hours=len(rows),
            inflow_count=sum(row.inflow_count for row in rows),
            inflow_value=Amount(sum(row.inflow_value.raw for row in rows)),
            outflow_count=sum(row.outflow_count for row in rows),
            outflow_value=Amount(sum(row.outflow_value.raw for row in rows)),
            internal_count=sum(row.internal_count for row in rows),
            internal_value=Amount(sum(row.internal_value.raw for row in rows)),
            blocks=sum(row.blocks for row in rows),
            complete_blocks=sum(row.complete_blocks for row in rows),
            # The highest floor in the window bounds every claim from it: one
            # hour captured at a raised floor narrows the whole total.
            capture_floor=max(floors, key=lambda f: f.raw) if floors else None,
            first_hour=min(starts),
            last_hour=max(starts),
        )

    def entities(self, chain: str, *, limit: int = 25) -> tuple[str, ...]:
        rows = self._db.connection.execute(
            """
            SELECT entity, COUNT(*) AS n FROM exchange_flow_hourly
             WHERE chain = ? GROUP BY entity ORDER BY n DESC LIMIT ?
            """,
            (chain, limit),
        )
        return tuple(row["entity"] for row in rows)

    def latest_hour(self, chain: str) -> datetime | None:
        row = self._db.connection.execute(
            "SELECT MAX(hour_start) AS hi FROM exchange_flow_hourly WHERE chain = ?",
            (chain,),
        ).fetchone()
        return datetime.fromisoformat(row["hi"]) if row and row["hi"] else None

    def count(self, chain: str = "") -> int:
        if chain:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS n FROM exchange_flow_hourly WHERE chain = ?",
                (chain,),
            ).fetchone()
        else:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS n FROM exchange_flow_hourly"
            ).fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def _hydrate(row: Any) -> ExchangeFlowHour:
        floor = row["capture_floor"]
        return ExchangeFlowHour(
            chain=row["chain"],
            hour_start=datetime.fromisoformat(row["hour_start"]),
            entity=row["entity"],
            inflow_count=int(row["inflow_count"]),
            inflow_value=Amount.from_stored(row["inflow_value"]),
            outflow_count=int(row["outflow_count"]),
            outflow_value=Amount.from_stored(row["outflow_value"]),
            internal_count=int(row["internal_count"]),
            internal_value=Amount.from_stored(row["internal_value"]),
            addresses=int(row["addresses"]),
            blocks=int(row["blocks"]),
            complete_blocks=int(row["complete_blocks"]),
            capture_floor=Amount.from_stored(floor) if floor else None,
            first_number=int(row["first_number"]),
            last_number=int(row["last_number"]),
            label_source=row["label_source"],
            rolled_at=datetime.fromisoformat(row["rolled_at"]),
        )

    def __repr__(self) -> str:
        return f"ExchangeFlowRepository(hours={self.count()})"


__all__ = [
    "ExchangeFlowHour",
    "ExchangeFlowRepository",
    "FlowTotals",
    "hour_of",
]
