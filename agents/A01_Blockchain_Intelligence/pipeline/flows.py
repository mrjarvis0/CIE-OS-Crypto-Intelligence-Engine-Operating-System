"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.flows

Purpose:
    Turn stored transfers plus a label set into exchange deposits and
    withdrawals, bucketed by the hour they happened in.

Design goals:
    - One transfer is classified once, against labels that state their source
    - Deposits, withdrawals and internal movement kept apart
    - Every transfer accounted for: classified, unrelated, or undated
    - Exact integer arithmetic on values
    - Pure: no storage, no network, no clock

Notes:
    The signal is direction, not size. A large transfer between two wallets is
    ordinary; the same transfer into an exchange deposit address is a different
    fact, because it is the step that precedes a sale. That is why the labelled
    address list is the input that unlocks this and why nothing here works
    without one.

    **The internal case is the one that decides whether this is trustworthy.**
    An exchange moves its own funds constantly -- hot wallet to cold storage,
    one venue to another, address rotation -- and every one of those transfers
    has a labelled address on the receiving end. Counted as deposits they
    produce an inflow spike with no user behind it, which is the most common way
    an exchange-flow figure gets read as sell pressure that is not there. So a
    transfer with a labelled address on *both* sides is classified as internal,
    counted, and excluded from both directions.

    **Attribution is per operator, not per address.** A deposit to "Binance 14"
    is a deposit to Binance, and the label set resolves the operator. Keyed on
    the address label instead, one exchange's 118 addresses would produce 118
    entities and every per-exchange total would be a fragment.

    Nothing here interprets. A row states what moved in which direction; whether
    that is bullish, bearish, or accumulation is a judgement this module does
    not make and the evidence standard forbids it from implying.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from database.analytics import HourQuality
from schemas.amount import Amount
from tiers.ledger import LabelSet
from tiers.warm import ExchangeFlowHour, hour_of


class FlowDirection(StrEnum):
    """What one transfer was, relative to the labelled set."""

    #: Into a labelled address from an unlabelled one.
    DEPOSIT = "deposit"
    #: Out of a labelled address to an unlabelled one.
    WITHDRAWAL = "withdrawal"
    #: Labelled on both sides. Neither a deposit nor a withdrawal.
    INTERNAL = "internal"
    #: Touches no labelled address at all.
    UNRELATED = "unrelated"


@dataclass(frozen=True, slots=True)
class Classification:
    """One transfer's direction and the operators it concerns."""

    direction: FlowDirection
    #: Every operator this transfer is a fact about. Two for an internal
    #: transfer between different exchanges, one otherwise.
    entities: tuple[str, ...] = ()

    @property
    def related(self) -> bool:
        return self.direction is not FlowDirection.UNRELATED


@dataclass(slots=True)
class FlowStats:
    """
    What a roll-up looked at, so nothing disappears between input and output.

    **This is the per-transfer view, and it is not the sum of the hourly rows.**
    A transfer between two different exchanges is recorded on both of their
    hours -- it is a fact about each -- so adding those rows up counts it twice.
    Both views are correct for their own question, and a window total has to
    come from this one: "how much moved" is a question about transfers, not
    about how many parties each concerned.

    ``undated`` is separate from ``unrelated`` on purpose. A transfer whose
    block timestamp was not stored cannot be put in an hour, and dropping it
    into the nearest one would move a deposit into an hour it did not happen
    in. It is excluded and counted, which is the difference between a gap and a
    silent error.
    """

    seen: int = 0
    deposits: int = 0
    withdrawals: int = 0
    internal: int = 0
    unrelated: int = 0
    undated: int = 0

    #: Values in the chain's smallest unit, each transfer counted once.
    deposit_value: int = 0
    withdrawal_value: int = 0
    internal_value: int = 0

    @property
    def attributed(self) -> int:
        return self.deposits + self.withdrawals + self.internal

    @property
    def net_value(self) -> int:
        """
        Deposits minus withdrawals. Signed, so it is a plain integer.

        Internal movement is in neither term. It is the exchange's own money
        changing hands, and folding it in either direction is how a rebalance
        becomes a flow signal.
        """
        return self.deposit_value - self.withdrawal_value

    @property
    def direction(self) -> str:
        """``inflow``, ``outflow`` or ``balanced``. What moved, never why."""
        if self.net_value > 0:
            return "inflow"
        if self.net_value < 0:
            return "outflow"
        return "balanced"

    def as_dict(self) -> dict[str, Any]:
        return {
            "seen": self.seen,
            "deposits": self.deposits,
            "withdrawals": self.withdrawals,
            "internal": self.internal,
            "unrelated": self.unrelated,
            "undated": self.undated,
            "attributed": self.attributed,
        }

    def totals(self) -> dict[str, Any]:
        """The window as one row, for a result body."""
        return {
            "inflow_count": self.deposits,
            "inflow_value": str(self.deposit_value),
            "outflow_count": self.withdrawals,
            "outflow_value": str(self.withdrawal_value),
            "internal_count": self.internal,
            "internal_value": str(self.internal_value),
            "net_value": str(self.net_value),
            "direction": self.direction,
        }


def classify(
    from_address: str | None, to_address: str | None, labels: LabelSet
) -> Classification:
    """
    What one transfer is, relative to the labelled set.

    A transfer between two addresses of the *same* operator resolves to one
    entity rather than two -- it is one fact about Binance, not two.
    """
    sender = labels.entity_of(from_address) if from_address else None
    recipient = labels.entity_of(to_address) if to_address else None

    if sender and recipient:
        entities = (sender,) if sender == recipient else tuple(sorted({sender, recipient}))
        return Classification(FlowDirection.INTERNAL, entities)
    if recipient:
        return Classification(FlowDirection.DEPOSIT, (recipient,))
    if sender:
        return Classification(FlowDirection.WITHDRAWAL, (sender,))
    return Classification(FlowDirection.UNRELATED)


@dataclass(slots=True)
class FlowAccumulator:
    """Running totals for one operator in one hour."""

    chain: str
    hour_start: datetime
    entity: str

    inflow_count: int = 0
    inflow_value: int = 0
    outflow_count: int = 0
    outflow_value: int = 0
    internal_count: int = 0
    internal_value: int = 0
    first_number: int = 0
    last_number: int = 0

    _addresses: set[str] = field(default_factory=set, repr=False)

    def observe(
        self,
        *,
        direction: FlowDirection,
        value: int,
        height: int,
        addresses: Iterable[str],
    ) -> None:
        if direction is FlowDirection.DEPOSIT:
            self.inflow_count += 1
            self.inflow_value += value
        elif direction is FlowDirection.WITHDRAWAL:
            self.outflow_count += 1
            self.outflow_value += value
        elif direction is FlowDirection.INTERNAL:
            self.internal_count += 1
            self.internal_value += value
        else:  # pragma: no cover - an unrelated transfer never reaches an hour
            return

        self._addresses.update(address for address in addresses if address)
        self.first_number = height if not self.first_number else min(self.first_number, height)
        self.last_number = max(self.last_number, height)

    def freeze(
        self, quality: HourQuality, *, label_source: str = "", rolled_at: datetime | None = None
    ) -> ExchangeFlowHour:
        return ExchangeFlowHour(
            chain=self.chain,
            hour_start=self.hour_start,
            entity=self.entity,
            inflow_count=self.inflow_count,
            inflow_value=Amount(self.inflow_value),
            outflow_count=self.outflow_count,
            outflow_value=Amount(self.outflow_value),
            internal_count=self.internal_count,
            internal_value=Amount(self.internal_value),
            addresses=len(self._addresses),
            blocks=quality.blocks,
            complete_blocks=quality.complete_blocks,
            capture_floor=quality.capture_floor,
            first_number=self.first_number,
            last_number=self.last_number,
            label_source=label_source,
            rolled_at=rolled_at or datetime.now(UTC),
        )


def roll_up(
    chain: str,
    transfers: Sequence[Any],
    labels: LabelSet,
    *,
    quality: Mapping[datetime, HourQuality] | None = None,
    label_source: str = "",
    stats: FlowStats | None = None,
    rolled_at: datetime | None = None,
) -> tuple[ExchangeFlowHour, ...]:
    """
    Classify a window of transfers into hourly per-operator rows.

    ``transfers`` is any iterable of objects exposing ``from_address``,
    ``to_address``, ``value``, ``height`` and ``at`` -- the shape
    :class:`~database.analytics.TransferRecord` already has. Typed loosely for
    the same reason ``accumulate`` is: the fields are what matters, not the
    class.

    An internal transfer between two different operators is recorded on **both**
    of their hours. It is a fact about each of them, and attributing it to one
    would make the other's hour look quieter than it was.

    Returns the rows sorted by hour then operator, so two runs over the same
    window produce the same output.
    """
    buckets: dict[tuple[datetime, str], FlowAccumulator] = {}
    counters = stats if stats is not None else FlowStats()
    hour_quality = quality or {}

    for transfer in transfers:
        counters.seen += 1

        sender = _address(getattr(transfer, "from_address", None))
        recipient = _address(getattr(transfer, "to_address", None))
        verdict = classify(sender, recipient, labels)
        value = _raw_value(getattr(transfer, "value", 0))

        # Counted once per transfer here, whatever it is later attributed to.
        # The hourly rows below record an inter-exchange move on both sides, so
        # they cannot be summed into a window total without double-counting it.
        if verdict.direction is FlowDirection.DEPOSIT:
            counters.deposits += 1
            counters.deposit_value += value
        elif verdict.direction is FlowDirection.WITHDRAWAL:
            counters.withdrawals += 1
            counters.withdrawal_value += value
        elif verdict.direction is FlowDirection.INTERNAL:
            counters.internal += 1
            counters.internal_value += value
        else:
            counters.unrelated += 1
            continue

        at = getattr(transfer, "at", None)
        if at is None:
            # Not droppable into the nearest hour: that moves a deposit into an
            # hour it did not happen in, and a baseline built from those hours
            # is wrong in a way nothing downstream can detect.
            counters.undated += 1
            continue

        bucket_hour = hour_of(at)
        height = int(getattr(transfer, "height", 0) or 0)

        for entity in verdict.entities:
            accumulator = buckets.get((bucket_hour, entity))
            if accumulator is None:
                accumulator = FlowAccumulator(
                    chain=chain, hour_start=bucket_hour, entity=entity
                )
                buckets[(bucket_hour, entity)] = accumulator
            accumulator.observe(
                direction=verdict.direction,
                value=value,
                height=height,
                addresses=(sender, recipient),
            )

    return tuple(
        buckets[key].freeze(
            hour_quality.get(key[0], HourQuality()),
            label_source=label_source,
            rolled_at=rolled_at,
        )
        for key in sorted(buckets, key=lambda item: (item[0], item[1]))
    )


def totals_by_entity(hours: Iterable[ExchangeFlowHour]) -> dict[str, dict[str, Any]]:
    """
    Collapse hours to one row per operator, for display.

    Values are summed as Python integers. A float would lose precision above
    2^53, which in wei is about 0.009 ether -- so a float total is wrong for
    essentially every exchange.
    """
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "inflow_count": 0,
            "inflow_value": 0,
            "outflow_count": 0,
            "outflow_value": 0,
            "internal_count": 0,
            "internal_value": 0,
            "hours": 0,
        }
    )
    for hour in hours:
        entry = out[hour.entity]
        entry["inflow_count"] += hour.inflow_count
        entry["inflow_value"] += hour.inflow_value.raw
        entry["outflow_count"] += hour.outflow_count
        entry["outflow_value"] += hour.outflow_value.raw
        entry["internal_count"] += hour.internal_count
        entry["internal_value"] += hour.internal_value.raw
        entry["hours"] += 1

    return {
        entity: {
            **entry,
            "net_value": entry["inflow_value"] - entry["outflow_value"],
        }
        for entity, entry in sorted(
            out.items(),
            key=lambda item: item[1]["inflow_value"] + item[1]["outflow_value"],
            reverse=True,
        )
    }


def _raw_value(value: Any) -> int:
    if isinstance(value, Amount):
        return value.raw
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _address(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "Classification",
    "FlowAccumulator",
    "FlowDirection",
    "FlowStats",
    "HourQuality",
    "classify",
    "roll_up",
    "totals_by_entity",
]
