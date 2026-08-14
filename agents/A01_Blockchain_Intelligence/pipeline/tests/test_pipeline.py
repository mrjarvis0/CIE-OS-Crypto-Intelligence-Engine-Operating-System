"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for selective capture.

The package exists to stop a measured failure: storing every transaction cost
0.70 MB per ethereum block, roughly 5 GB a day for one chain, to keep 334 rows
per block so a handful could later be counted.

What is asserted here is that dropping those rows stays *honest* -- that the
aggregate still answers what the rows answered, that the gate reports what it
cannot see, and that the floor is never a fixed currency amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from database import Database, SqliteBlockRepository
from pipeline import (
    MIN_POPULATION,
    FilterStats,
    MaterialityGate,
    SelectiveWriter,
    Verdict,
    accumulate,
    floor_from,
)
from schemas.amount import Amount
from sensors.envelope import Provenance, RawRecord, RecordKind
from tiers import BlockAggregateRepository

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
ETH = 10**18


@dataclass
class Tx:
    value: int
    from_address: str | None = "0xsender"
    to_address: str | None = "0xreceiver"


def block(gate: MaterialityGate, transactions, **kwargs):
    return accumulate(
        chain="ethereum",
        number=100,
        block_hash="0x" + "aa" * 32,
        timestamp=NOW,
        transactions=transactions,
        gate=gate,
        **kwargs,
    )


# ==============================================================================
# THE FLOOR
# ==============================================================================

def test_the_floor_comes_from_the_distribution_not_a_constant():
    """
    A fixed currency threshold is wrong in both directions at once: noise on
    Ethereum, unreachable on a long-tail token, and stale after any large price
    move.
    """
    small = floor_from([n * ETH for n in range(1, MIN_POPULATION + 1)],
                       cold_start=Amount(ETH))
    large = floor_from([n * 1000 * ETH for n in range(1, MIN_POPULATION + 1)],
                       cold_start=Amount(ETH))

    assert large.raw > small.raw * 100, "the floor must track its own population"


def test_a_thin_population_falls_back_rather_than_inventing_a_threshold():
    """
    A percentile over forty observations looks principled and is not, and it
    would then be applied to every subsequent block.
    """
    floor = floor_from([5 * ETH] * 40, cold_start=Amount(7 * ETH))

    assert floor.raw == 7 * ETH


def test_zero_value_transfers_do_not_drag_the_floor_down():
    """
    Contract calls that move nothing are most of chain traffic. Left in, they
    pull every percentile toward zero until routine transfers clear it.
    """
    real = [n * ETH for n in range(1, MIN_POPULATION + 1)]

    clean = floor_from(real, cold_start=Amount(ETH))
    padded = floor_from([*real, *([0] * 5000)], cold_start=Amount(ETH))

    assert clean.raw == padded.raw


# ==============================================================================
# THE GATE
# ==============================================================================

def test_a_transaction_below_the_floor_is_dropped():
    gate = MaterialityGate(floor=Amount(10 * ETH))

    assert not gate.assess(value=ETH).material


def test_a_transaction_at_the_floor_is_kept():
    """At, not above: the floor is a value the chain actually produced."""
    gate = MaterialityGate(floor=Amount(10 * ETH))
    decision = gate.assess(value=10 * ETH)

    assert decision.material
    assert decision.verdict is Verdict.VALUE


def test_a_labelled_counterparty_qualifies_a_small_transfer():
    """
    A modest transfer into a known exchange deposit address is a stronger
    signal than a large transfer between two wallets of one owner.
    """
    gate = MaterialityGate(
        floor=Amount(1000 * ETH),
        is_labelled=lambda address: address == "0xexchange",
    )
    decision = gate.assess(value=ETH, to_address="0xexchange")

    assert decision.material
    assert decision.verdict is Verdict.LABELLED


def test_a_gate_without_labels_says_what_it_cannot_see():
    """
    Exchange and bridge flows below the value floor are invisible without
    labels. That is a coverage limitation, and it must not be a quiet one.
    """
    gate = MaterialityGate(floor=Amount(ETH))

    assert not gate.labels_available
    assert "exchange" in gate.limitation()


def test_a_gate_with_labels_reports_no_limitation():
    gate = MaterialityGate(floor=Amount(ETH), is_labelled=lambda _: False)

    assert gate.labels_available
    assert gate.limitation() == ""


# ==============================================================================
# THE AGGREGATE — the half that makes dropping honest
# ==============================================================================

def test_dropped_transactions_are_still_counted():
    """
    The bargain. If the count did not survive the rows, this would be data loss
    rather than compression.
    """
    gate = MaterialityGate(floor=Amount(100 * ETH))
    aggregate, material = block(gate, [Tx(ETH) for _ in range(300)])

    assert aggregate.tx_count == 300, "every transaction must be counted"
    assert aggregate.material_tx_count == 0
    assert material == []


def test_the_value_total_covers_everything_including_the_dropped():
    gate = MaterialityGate(floor=Amount(100 * ETH))
    aggregate, _ = block(gate, [Tx(2 * ETH) for _ in range(50)])

    assert aggregate.tx_value_total.raw == 100 * ETH


def test_only_material_transactions_are_returned_for_storage():
    """The one behaviour the whole redesign turns on."""
    gate = MaterialityGate(floor=Amount(10 * ETH))
    transactions = [Tx(ETH)] * 99 + [Tx(50 * ETH)]

    aggregate, material = block(gate, transactions)

    assert aggregate.tx_count == 100
    assert len(material) == 1, "99 rows must never reach storage"
    assert material[0].value == 50 * ETH


def test_active_addresses_count_the_whole_block():
    """
    Active addresses is a Tier-1 trader signal. Counting only material senders
    would report the filter's activity rather than the chain's.
    """
    gate = MaterialityGate(floor=Amount(1000 * ETH))
    transactions = [Tx(ETH, from_address=f"0x{i}", to_address="0xpool") for i in range(40)]

    aggregate, _ = block(gate, transactions)

    assert aggregate.unique_senders == 40
    assert aggregate.unique_receivers == 1


def test_the_floor_in_force_travels_with_the_block():
    """
    Without it, a block with two material transfers because the chain was quiet
    is indistinguishable from one with two because the gate was raised to
    protect a rate budget.
    """
    gate = MaterialityGate(floor=Amount(42 * ETH))
    aggregate, _ = block(gate, [Tx(ETH)])

    assert aggregate.materiality_floor.raw == 42 * ETH


def test_values_stay_exact_above_the_float_boundary():
    """
    A float loses precision above 2^53, which in wei is about 0.009 ether — so
    a float total would be wrong for essentially every block.
    """
    gate = MaterialityGate(floor=Amount(ETH))
    aggregate, _ = block(gate, [Tx(123_456_789_012_345_678_901) for _ in range(7)])

    assert aggregate.tx_value_total.raw == 7 * 123_456_789_012_345_678_901


def test_filter_stats_report_the_compression():
    gate = MaterialityGate(floor=Amount(10 * ETH))
    stats = FilterStats()

    block(gate, [Tx(ETH)] * 90 + [Tx(50 * ETH)] * 10, stats=stats)

    assert stats.seen == 100
    assert stats.kept == 10
    assert stats.dropped == 90
    assert stats.kept_share == pytest.approx(0.10)


def test_an_incomplete_capture_is_carried_into_the_aggregate():
    gate = MaterialityGate(floor=Amount(ETH))
    aggregate, _ = block(gate, [Tx(2 * ETH)], complete=False)

    assert not aggregate.complete


def test_a_malformed_value_does_not_crash_the_stream():
    """
    One bad field must not cost the whole block. It is not material, which is
    the safe reading: a value that cannot be parsed cannot be shown to be large.
    """
    gate = MaterialityGate(floor=Amount(ETH))
    aggregate, material = block(gate, [Tx("not-a-number"), Tx(5 * ETH)])

    assert aggregate.tx_count == 2
    assert len(material) == 1


# ==============================================================================
# THE WRITER — what reaches storage, and what storage is told about it
# ==============================================================================

def raw_block(number: int, transfers: list[int]) -> RawRecord:
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", "ethereum", "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": f"0xa{number:06d}",
            "parentHash": f"0xa{number - 1:06d}",
            "timestamp": hex(1_700_000_000 + number * 12),
            "transactions": [
                {
                    "hash": f"0xtx{number:05d}{i:03d}",
                    "from": "0x" + "a1" * 20,
                    "to": "0x" + "b2" * 20,
                    "value": hex(value),
                    "transactionIndex": hex(i),
                    "input": "0x",
                }
                for i, value in enumerate(transfers)
            ],
        },
    )


@pytest.fixture
def selective():
    """A live selective writer over an in-memory database, floor at 10 ETH."""
    with Database() as db:
        repo = SqliteBlockRepository(db)
        yield db, SelectiveWriter(
            repo,
            BlockAggregateRepository(db),
            gate=MaterialityGate(floor=Amount(10 * ETH)),
        )


def stored_row(db):
    return db.connection.execute(
        "SELECT complete, incomplete_reason, capture_floor FROM blocks"
    ).fetchone()


def test_a_filtered_block_tells_storage_it_was_filtered(selective):
    """
    The end of the chain the reason has to survive.

    Marking the block incomplete was never the problem -- it is incomplete. The
    problem was that `complete = 0` was the *whole* record, so a window of
    deliberately filtered blocks was indistinguishable from a window of failed
    fetches, and the absence gate shut on both.
    """
    db, writer = selective
    writer.write(raw_block(100, [ETH, 50 * ETH]))

    row = stored_row(db)
    assert row["complete"] == 0
    assert row["incomplete_reason"] == "selective_capture"
    assert Amount.from_stored(row["capture_floor"]).raw == 10 * ETH


def test_an_empty_block_is_not_stamped_with_a_floor(selective):
    """
    Nothing was filtered, so nothing was dropped, so the block is whole.

    Stamping the floor here would be worse than untidy: the window reports the
    highest floor any of its blocks carried, so an empty block could raise the
    floor of a whole window and narrow every absence claim drawn from it.
    """
    db, writer = selective
    writer.write(raw_block(100, []))

    row = stored_row(db)
    assert row["complete"] == 1
    assert row["incomplete_reason"] == ""
    assert row["capture_floor"] == ""


def test_the_floor_stored_is_the_one_that_was_in_force(selective):
    """
    `retune` exists because a tightening budget should cost resolution rather
    than the capture. What it must not cost is the record of which floor applied
    to which block.
    """
    db, writer = selective
    writer.write(raw_block(100, [ETH]))
    writer.retune(Amount(500 * ETH))
    writer.write(raw_block(101, [ETH]))

    floors = [
        Amount.from_stored(row["capture_floor"]).raw
        for row in db.connection.execute(
            "SELECT capture_floor FROM blocks ORDER BY number"
        )
    ]
    assert floors == [10 * ETH, 500 * ETH]
