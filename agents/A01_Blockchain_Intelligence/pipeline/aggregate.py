"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.aggregate

Purpose:
    Accumulate what a block contained while its transactions stream past, so
    the transactions themselves do not have to be kept.

Design goals:
    - Single pass, constant memory per block except for the address sets
    - Counts cover the whole block, including everything dropped
    - Exact arithmetic on values; no floats anywhere near an amount
    - Pure: no storage, no network

Notes:
    This is the half of the trade that makes dropping transactions honest. The
    old design kept 334 rows per ethereum block so that a handful of figures
    could be derived from them later; this derives the figures as the rows go
    past and lets them go.

    ``unique_senders`` and ``unique_receivers`` hold real sets, which is the one
    place per-block memory is not constant. That is deliberate: an approximate
    distinct count (HyperLogLog and friends) would save a few kilobytes of
    transient memory and put an error bar on "active addresses", which is a
    Tier-1 trader signal. The sets live for one block and are discarded with it.

    Values are Python integers throughout. A float would lose precision above
    2^53, which in wei is about 0.009 ether -- so a float total would be wrong
    for essentially every block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from schemas.amount import Amount
from tiers.hot import BlockAggregate

from .materiality import Decision, MaterialityGate


@dataclass(slots=True)
class BlockAccumulator:
    """
    Running totals for one block.

    Mutable by design -- it is fed once per transaction and then frozen into a
    :class:`~tiers.hot.BlockAggregate`. Everything it holds is discarded with
    the block.
    """

    chain: str
    number: int
    block_hash: str
    timestamp: datetime
    materiality_floor: Amount

    tx_count: int = 0
    value_total: int = 0
    value_max: int = 0
    material_count: int = 0
    material_value_total: int = 0
    gas_used: int | None = None
    complete: bool = True
    source_provider: str = ""
    source_record_id: str = ""

    _senders: set[str] = field(default_factory=set, repr=False)
    _receivers: set[str] = field(default_factory=set, repr=False)

    def observe(
        self,
        *,
        value: int,
        decision: Decision,
        from_address: str | None = None,
        to_address: str | None = None,
    ) -> None:
        """
        Record one transaction, material or not.

        Called for **every** transaction in the block, including the ones about
        to be dropped. Calling it only for material ones would make `tx_count`
        the count of what was kept, and every ratio drawn from this block --
        material share, average value, active addresses -- would describe the
        filter rather than the chain.
        """
        self.tx_count += 1
        self.value_total += value
        if value > self.value_max:
            self.value_max = value

        if from_address:
            self._senders.add(from_address)
        if to_address:
            self._receivers.add(to_address)

        if decision.material:
            self.material_count += 1
            self.material_value_total += value

    @property
    def unique_senders(self) -> int:
        return len(self._senders)

    @property
    def unique_receivers(self) -> int:
        return len(self._receivers)

    @property
    def material_share(self) -> float:
        return self.material_count / self.tx_count if self.tx_count else 0.0

    def freeze(self) -> BlockAggregate:
        """The immutable row. After this the accumulator has no further use."""
        return BlockAggregate(
            chain=self.chain,
            number=self.number,
            block_hash=self.block_hash,
            timestamp=self.timestamp,
            tx_count=self.tx_count,
            tx_value_total=Amount(self.value_total),
            tx_value_max=Amount(self.value_max),
            unique_senders=self.unique_senders,
            unique_receivers=self.unique_receivers,
            gas_used=self.gas_used,
            material_tx_count=self.material_count,
            material_value_total=Amount(self.material_value_total),
            materiality_floor=self.materiality_floor,
            complete=self.complete,
            source_provider=self.source_provider,
            source_record_id=self.source_record_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "number": self.number,
            "tx_count": self.tx_count,
            "material_tx_count": self.material_count,
            "material_share": round(self.material_share, 6),
            "unique_senders": self.unique_senders,
            "unique_receivers": self.unique_receivers,
            "complete": self.complete,
        }


@dataclass(slots=True)
class FilterStats:
    """
    What a run kept and what it dropped.

    ``dropped`` is the number this whole package exists to make large. It is
    reported rather than inferred so an operator can see the compression they
    are actually getting, instead of trusting that the gate is doing anything.
    """

    seen: int = 0
    kept: int = 0
    blocks: int = 0

    @property
    def dropped(self) -> int:
        return self.seen - self.kept

    @property
    def kept_share(self) -> float:
        return self.kept / self.seen if self.seen else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "seen": self.seen,
            "kept": self.kept,
            "dropped": self.dropped,
            "kept_share": round(self.kept_share, 6),
            "blocks": self.blocks,
        }


def accumulate(
    *,
    chain: str,
    number: int,
    block_hash: str,
    timestamp: datetime,
    transactions: Any,
    gate: MaterialityGate,
    stats: FilterStats | None = None,
    gas_used: int | None = None,
    complete: bool = True,
    source_provider: str = "",
    source_record_id: str = "",
) -> tuple[BlockAggregate, list[Any]]:
    """
    Stream one block's transactions through the gate.

    Returns the aggregate and **only the material transactions**. The caller
    stores both; everything else has already been discarded by the time this
    returns, which is the single behaviour the whole redesign turns on.

    ``transactions`` is any iterable of objects exposing ``value``,
    ``from_address`` and ``to_address``. Typed loosely on purpose: the canonical
    transaction type differs per chain family, and this function cares about
    three fields that all of them have.
    """
    accumulator = BlockAccumulator(
        chain=chain,
        number=number,
        block_hash=block_hash,
        timestamp=timestamp,
        materiality_floor=gate.floor,
        gas_used=gas_used,
        complete=complete,
        source_provider=source_provider,
        source_record_id=source_record_id,
    )

    material: list[Any] = []

    for transaction in transactions:
        value = _raw_value(getattr(transaction, "value", 0))
        sender = _address(getattr(transaction, "from_address", None))
        receiver = _address(getattr(transaction, "to_address", None))

        decision = gate.assess(
            value=value, from_address=sender, to_address=receiver
        )
        accumulator.observe(
            value=value,
            decision=decision,
            from_address=sender,
            to_address=receiver,
        )

        if decision.material:
            material.append(transaction)

        if stats is not None:
            stats.seen += 1
            if decision.material:
                stats.kept += 1

    if stats is not None:
        stats.blocks += 1

    return accumulator.freeze(), material


def _raw_value(value: Any) -> int:
    """An amount as an integer, whatever shape it arrived in. Never raises."""
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
    return text.lower() if text else None


__all__ = ["BlockAccumulator", "FilterStats", "accumulate"]
