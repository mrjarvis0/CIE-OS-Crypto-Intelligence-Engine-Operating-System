"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for Tier W: hourly exchange flow.

This is the tier a baseline is made of, so what is asserted here is mostly
about a number staying meaningful over time: an hour recomputed replaces
itself, a window's totals stay exact past 64 bits, and a total drawn from a
selectively captured hour reports the floor that bounds it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from database import Database
from schemas.amount import Amount
from tiers.warm import ExchangeFlowHour, ExchangeFlowRepository, hour_of

HOUR = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
ETH = 10**18
#: Past SQLite's signed 64-bit ceiling (~9.22e18, about nine ether in wei).
FIFTY_ETH = 50 * ETH


@pytest.fixture
def repo():
    with Database() as db:
        yield ExchangeFlowRepository(db)


def flow_hour(hour: datetime = HOUR, entity: str = "Binance", **overrides) -> ExchangeFlowHour:
    fields = {
        "chain": "ethereum",
        "hour_start": hour,
        "entity": entity,
        "inflow_count": 3,
        "inflow_value": Amount(FIFTY_ETH),
        "outflow_count": 1,
        "outflow_value": Amount(ETH),
        "internal_count": 2,
        "internal_value": Amount(ETH),
        "addresses": 4,
        "blocks": 300,
        "complete_blocks": 300,
        "first_number": 100,
        "last_number": 400,
        "label_source": "gist:xfwil/07dadf39",
    }
    fields.update(overrides)
    return ExchangeFlowHour(**fields)


# ==============================================================================
# THE ROW
# ==============================================================================

def test_an_hour_must_name_the_operator_it_describes():
    """A flow row with no entity is a total nobody can attribute or compare."""
    with pytest.raises(ValueError, match="operator"):
        flow_hour(entity="")


def test_more_complete_blocks_than_blocks_is_refused():
    with pytest.raises(ValueError, match="exceeds"):
        flow_hour(blocks=2, complete_blocks=9)


def test_net_value_is_signed_where_an_amount_cannot_be():
    """
    More left than arrived is a real and common state. `Amount` refuses
    negatives because an on-chain quantity cannot be one; a difference can.
    """
    hour = flow_hour(inflow_value=Amount(ETH), outflow_value=Amount(4 * ETH))

    assert hour.net_value == -3 * ETH


def test_a_row_survives_a_round_trip(repo):
    repo.save(flow_hour())

    stored = repo.hours("ethereum")[0]

    assert stored.entity == "Binance"
    assert stored.inflow_value.raw == FIFTY_ETH
    assert stored.label_source == "gist:xfwil/07dadf39"


# ==============================================================================
# RE-ROLLING
# ==============================================================================

def test_re_rolling_an_hour_replaces_it(repo):
    """
    The opposite of the block aggregate, and deliberately so. A block cannot
    change; an hour of flow summarises whatever was stored when the roll ran,
    and a later roll over a fuller window is a better answer to one question.
    """
    assert repo.save(flow_hour(inflow_count=1)) is True
    assert repo.save(flow_hour(inflow_count=9)) is False

    rows = repo.hours("ethereum")

    assert len(rows) == 1
    assert rows[0].inflow_count == 9


def test_two_operators_in_one_hour_are_two_rows(repo):
    repo.save(flow_hour(entity="Binance"))
    repo.save(flow_hour(entity="Coinbase"))

    assert len(repo.hours("ethereum")) == 2


# ==============================================================================
# WINDOW TOTALS
# ==============================================================================

def test_totals_stay_exact_above_the_sqlite_integer_ceiling(repo):
    """
    Value columns are padded text because SQLite's INTEGER tops out near nine
    ether in wei. Summed in SQL this raises rather than truncating, so any real
    exchange window would fail outright.
    """
    for offset in range(3):
        repo.save(flow_hour(HOUR + timedelta(hours=offset)))

    totals = repo.totals("ethereum")

    assert totals.inflow_value.raw == 3 * FIFTY_ETH
    assert totals.inflow_value.raw > 9 * 10**18, "the test must exceed the ceiling"


def test_totals_report_direction_without_naming_intent(repo):
    """
    Deposits are consistent with an intent to sell and with collateral, market
    making and custody moves. Naming the intent is the line the evidence
    standard draws.
    """
    repo.save(flow_hour(inflow_value=Amount(9 * ETH), outflow_value=Amount(ETH)))

    totals = repo.totals("ethereum")

    assert totals.direction == "inflow"
    assert "bullish" not in totals.as_dict()["direction"]


def test_the_highest_floor_in_a_window_bounds_the_whole_total(repo):
    """
    One hour captured under a raised floor narrows every claim drawn from the
    window, so the maximum binds rather than the mean or the latest.
    """
    repo.save(flow_hour(HOUR, capture_floor=Amount(ETH)))
    repo.save(flow_hour(HOUR + timedelta(hours=1), capture_floor=Amount(500 * ETH)))

    assert repo.totals("ethereum").capture_floor == Amount(500 * ETH)


def test_a_padded_floor_orders_numerically_not_lexically(repo):
    """
    Unpadded, a floor of 9 wei outranks one of 10 ether as a string, and the
    window would claim a stronger absence than it holds.
    """
    repo.save(flow_hour(HOUR, capture_floor=Amount(9)))
    repo.save(flow_hour(HOUR + timedelta(hours=1), capture_floor=Amount(10 * ETH)))

    assert repo.totals("ethereum").capture_floor == Amount(10 * ETH)


def test_an_incomplete_hour_is_visible_in_the_totals(repo):
    repo.save(flow_hour(HOUR, blocks=300, complete_blocks=300))
    repo.save(flow_hour(HOUR + timedelta(hours=1), blocks=300, complete_blocks=12))

    totals = repo.totals("ethereum")

    assert not totals.all_complete


def test_totals_can_be_scoped_to_one_operator(repo):
    repo.save(flow_hour(entity="Binance", inflow_count=5))
    repo.save(flow_hour(entity="Coinbase", inflow_count=1))

    assert repo.totals("ethereum", entity="Binance").inflow_count == 5


def test_an_empty_window_totals_to_nothing_rather_than_zeroes_of_substance(repo):
    totals = repo.totals("ethereum")

    assert totals.hours == 0
    assert not totals.all_complete, "an empty window cannot be complete"


def test_hour_bucketing_is_utc():
    assert hour_of(datetime(2026, 8, 12, 9, 59, 59, tzinfo=UTC)) == HOUR
