"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the storage tiers.

The point of this package is a number: storing every transaction cost 0.70 MB
per ethereum block, and an aggregate should cost kilobytes. Most of what is
asserted here protects the correctness of that trade -- that the aggregate
still answers the questions the discarded rows used to answer, and that it
cannot quietly answer them wrongly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from database import Database
from schemas.amount import Amount
from tiers import BlockAggregate, BlockAggregateRepository, Tier, rule_for

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

#: Above SQLite's signed 64-bit ceiling (~9.22e18, about nine ether in wei).
#: Every value here is deliberately past it.
FIFTY_ETH = 50 * 10**18


@pytest.fixture
def repo():
    with Database() as db:
        yield BlockAggregateRepository(db)


def aggregate(number: int, **overrides) -> BlockAggregate:
    fields = {
        "chain": "ethereum",
        "number": number,
        "block_hash": f"0x{number:064x}",
        "timestamp": NOW - timedelta(minutes=number),
        "tx_count": 334,
        "tx_value_total": Amount(FIFTY_ETH),
        "tx_value_max": Amount(FIFTY_ETH),
        "material_tx_count": 2,
        "material_value_total": Amount(FIFTY_ETH),
        "materiality_floor": Amount(10**18),
    }
    fields.update(overrides)
    return BlockAggregate(**fields)


# ==============================================================================
# THE TRADE
# ==============================================================================

def test_an_aggregate_still_counts_the_transactions_it_discarded(repo):
    """
    The whole bargain. 334 transactions are dropped, and the count survives
    them -- otherwise the saving is just data loss.
    """
    repo.save(aggregate(100))

    totals = repo.totals_between("ethereum", NOW - timedelta(days=1), NOW)

    assert totals.blocks == 1
    assert totals.tx_count == 334, "the discarded rows must still be counted"
    assert totals.material_tx_count == 2


def test_large_totals_are_exact(repo):
    """
    The regression for a bug caught before it shipped.

    Value columns are zero-padded TEXT because SQLite's INTEGER is signed
    64-bit, with a ceiling around nine ether in wei. Summing them with
    `SUM(CAST(value AS INTEGER))` does not merely truncate -- SQLite raises
    `integer overflow` -- so a window holding more than nine ether, which is
    almost every window, would have failed outright.
    """
    for number in (100, 101, 102):
        repo.save(aggregate(number))

    totals = repo.totals_between("ethereum", NOW - timedelta(days=1), NOW)

    assert totals.tx_value_total.raw == 3 * FIFTY_ETH
    assert totals.tx_value_total.raw > 9 * 10**18, "the test must exceed the ceiling"


def test_a_replayed_block_is_not_counted_twice(repo):
    """Replaying a range must be free, as it is for blocks."""
    assert repo.save(aggregate(100)) is True
    assert repo.save(aggregate(100)) is False

    assert repo.totals_between("ethereum", NOW - timedelta(days=1), NOW).blocks == 1


# ==============================================================================
# HONESTY OF THE AGGREGATE
# ==============================================================================

def test_an_incomplete_capture_is_visible_in_the_totals(repo):
    """
    A total drawn partly from incomplete captures is a floor, not a total, and
    the caller has to be able to tell.
    """
    repo.save(aggregate(100))
    repo.save(aggregate(101, complete=False))

    totals = repo.totals_between("ethereum", NOW - timedelta(days=1), NOW)

    assert totals.blocks == 2
    assert totals.complete_blocks == 1
    assert totals.incomplete_blocks == 1
    assert not totals.all_complete


def test_the_materiality_floor_is_recorded_per_block(repo):
    """
    Without it, a block with two material transfers because the chain was quiet
    is indistinguishable from one with two because the gate was raised to
    protect a rate budget. Those license very different conclusions.
    """
    repo.save(aggregate(100, materiality_floor=Amount(10**18)))
    repo.save(aggregate(101, materiality_floor=Amount(500 * 10**18)))

    rows = list(repo.database.connection.execute(
        "SELECT number, materiality_floor FROM block_aggregates ORDER BY number"
    ))

    assert int(rows[0]["materiality_floor"]) != int(rows[1]["materiality_floor"])


def test_more_material_than_total_is_refused():
    """
    A material count above the block's own transaction count means the gate and
    the counter disagreed about what they were looking at, and every ratio drawn
    from that row would be wrong.
    """
    with pytest.raises(ValueError, match="exceeds"):
        aggregate(100, tx_count=3, material_tx_count=9)


def test_material_share_reports_the_compression(repo):
    agg = aggregate(100, tx_count=1000, material_tx_count=4)

    assert agg.material_share == pytest.approx(0.004)


def test_an_empty_window_reports_nothing_rather_than_zeroes_of_substance(repo):
    totals = repo.totals_between("ethereum", NOW - timedelta(days=1), NOW)

    assert totals.blocks == 0
    assert not totals.all_complete, "an empty window cannot be complete"


# ==============================================================================
# RETENTION POLICY
# ==============================================================================

def test_the_ledger_never_expires():
    """
    Smart money is a claim about a track record. If the record is swept, the
    claim can never be made again.
    """
    assert rule_for(Tier.LEDGER).permanent


def test_every_other_tier_does_expire():
    for tier in (Tier.CACHE, Tier.HOT, Tier.WARM):
        assert not rule_for(tier).permanent, f"{tier} must have a window"


def test_the_windows_increase_with_tier_age():
    """
    Cache < hot < warm. A tier that outlived the one above it would make the
    compaction order meaningless.
    """
    cache = rule_for(Tier.CACHE).window
    hot = rule_for(Tier.HOT).window
    warm = rule_for(Tier.WARM).window

    assert cache < hot < warm
