"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for exchange flow classification and the hourly rollup.

One assertion here matters more than the rest: a transfer between two labelled
addresses is not a deposit. An exchange moves its own money constantly, and
counting those movements as user inflow is the standard way an exchange-flow
figure produces a sell-pressure signal with nobody behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from database.analytics import HourQuality
from pipeline.flows import (
    FlowDirection,
    FlowStats,
    classify,
    roll_up,
    totals_by_entity,
)
from schemas.amount import Amount
from tiers.ledger import Label, label_set_from
from tiers.warm import hour_of

HOUR = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
ETH = 10**18

BINANCE_1 = "0x28c6c06298d514db089934071355e5743bf21d60"
BINANCE_2 = "0x21a31ee1afc51d94c2efccaa2092ad1028285549"
COINBASE = "0x71660c4005ba85c37ccec55d0c4493e66fe775d3"
WALLET = "0x5fa36dfe10ce3ee46479790076afe328bef7e2e2"
OTHER = "0x4838b106fce9647bdf1e7877bf73ce8b0bad5f97"


def label(address: str, entity: str) -> Label:
    return Label(
        chain="ethereum",
        address=address,
        label=f"{entity} hot",
        entity=entity,
        category="exchange",
        source="gist:xfwil/07dadf39",
        confidence=0.5,
    )


LABELS = label_set_from(
    [
        label(BINANCE_1, "Binance"),
        label(BINANCE_2, "Binance"),
        label(COINBASE, "Coinbase"),
    ],
    chain="ethereum",
)


@dataclass(frozen=True)
class Transfer:
    """The three fields the rollup reads, plus the hour and height."""

    from_address: str | None
    to_address: str | None
    value: Amount = Amount(ETH)
    height: int = 100
    at: datetime | None = HOUR


# ==============================================================================
# CLASSIFICATION
# ==============================================================================

def test_a_transfer_into_a_labelled_address_is_a_deposit():
    verdict = classify(WALLET, BINANCE_1, LABELS)

    assert verdict.direction is FlowDirection.DEPOSIT
    assert verdict.entities == ("Binance",)


def test_a_transfer_out_of_a_labelled_address_is_a_withdrawal():
    verdict = classify(BINANCE_1, WALLET, LABELS)

    assert verdict.direction is FlowDirection.WITHDRAWAL
    assert verdict.entities == ("Binance",)


def test_a_transfer_between_two_exchanges_is_internal_not_a_deposit():
    """
    The one that decides whether this signal is trustworthy.

    Binance moving funds to Coinbase has a labelled address on the receiving
    end, and counted as a deposit it produces an inflow spike with no user
    behind it -- read downstream as sell pressure that does not exist.
    """
    verdict = classify(BINANCE_1, COINBASE, LABELS)

    assert verdict.direction is FlowDirection.INTERNAL
    assert verdict.entities == ("Binance", "Coinbase")


def test_one_exchange_moving_between_its_own_addresses_is_one_fact():
    """
    Hot wallet to cold storage is internal, and it concerns one operator. Two
    entries would double-count a single rebalance.
    """
    verdict = classify(BINANCE_1, BINANCE_2, LABELS)

    assert verdict.direction is FlowDirection.INTERNAL
    assert verdict.entities == ("Binance",)


def test_a_transfer_touching_no_label_is_unrelated():
    verdict = classify(WALLET, OTHER, LABELS)

    assert verdict.direction is FlowDirection.UNRELATED
    assert not verdict.related


def test_a_contract_creation_has_no_recipient_and_does_not_crash():
    assert classify(WALLET, None, LABELS).direction is FlowDirection.UNRELATED


def test_attribution_is_by_operator_not_by_address_label():
    """
    Keyed on the address's own label, Binance's 118 addresses would be 118
    exchanges and every per-exchange total would be a fragment.
    """
    first = classify(WALLET, BINANCE_1, LABELS)
    second = classify(WALLET, BINANCE_2, LABELS)

    assert first.entities == second.entities == ("Binance",)


# ==============================================================================
# THE ROLLUP
# ==============================================================================

def test_deposits_and_withdrawals_are_kept_apart():
    """
    An hour of 4,000 in and 4,000 out is not a quiet hour. Storing only the
    difference would destroy the fact that makes it interesting.
    """
    hours = roll_up(
        "ethereum",
        [
            Transfer(WALLET, BINANCE_1, Amount(4 * ETH)),
            Transfer(BINANCE_1, WALLET, Amount(4 * ETH)),
        ],
        LABELS,
    )

    assert len(hours) == 1
    assert hours[0].inflow_count == 1
    assert hours[0].outflow_count == 1
    assert hours[0].net_value == 0
    assert hours[0].transfers == 2, "the row still knows two transfers happened"


def test_internal_movement_is_excluded_from_both_directions():
    hours = roll_up("ethereum", [Transfer(BINANCE_1, BINANCE_2)], LABELS)

    assert hours[0].internal_count == 1
    assert hours[0].inflow_count == 0
    assert hours[0].outflow_count == 0


def test_an_internal_transfer_between_exchanges_lands_on_both(  ):
    """
    It is a fact about each of them. Attributing it to one would make the
    other's hour look quieter than it was.
    """
    hours = roll_up("ethereum", [Transfer(BINANCE_1, COINBASE)], LABELS)

    assert {hour.entity for hour in hours} == {"Binance", "Coinbase"}
    assert all(hour.internal_count == 1 for hour in hours)


def test_transfers_are_bucketed_by_the_hour_they_happened_in():
    hours = roll_up(
        "ethereum",
        [
            Transfer(WALLET, BINANCE_1, at=HOUR),
            Transfer(WALLET, BINANCE_1, at=HOUR + timedelta(minutes=59)),
            Transfer(WALLET, BINANCE_1, at=HOUR + timedelta(hours=1)),
        ],
        LABELS,
    )

    assert len(hours) == 2
    assert hours[0].inflow_count == 2
    assert hours[1].inflow_count == 1


def test_hours_are_utc_whatever_the_timestamp_carried():
    """
    A bucket on local time is duplicated or skipped twice a year, and a
    baseline with two 02:00 buckets one day a year has a hole in it.
    """
    local = datetime(2026, 8, 12, 9, 30, tzinfo=timezone_plus(5, 30))

    assert hour_of(local) == datetime(2026, 8, 12, 4, 0, tzinfo=UTC)


def timezone_plus(hours: int, minutes: int = 0):
    from datetime import timezone

    return timezone(timedelta(hours=hours, minutes=minutes))


def test_an_undated_transfer_is_excluded_and_counted():
    """
    Dropping it into the nearest hour would move a deposit into an hour it did
    not happen in, and nothing downstream could detect it.
    """
    stats = FlowStats()
    hours = roll_up(
        "ethereum",
        [Transfer(WALLET, BINANCE_1, at=None), Transfer(WALLET, BINANCE_1)],
        LABELS,
        stats=stats,
    )

    assert stats.undated == 1
    assert stats.deposits == 2, "it was still classified; only the bucket is missing"
    assert sum(hour.inflow_count for hour in hours) == 1


def test_every_transfer_is_accounted_for():
    stats = FlowStats()
    roll_up(
        "ethereum",
        [
            Transfer(WALLET, BINANCE_1),
            Transfer(BINANCE_1, WALLET),
            Transfer(BINANCE_1, COINBASE),
            Transfer(WALLET, OTHER),
        ],
        LABELS,
        stats=stats,
    )

    assert stats.seen == 4
    assert stats.attributed + stats.unrelated == stats.seen


def test_values_stay_exact_above_the_float_boundary():
    """A float loses precision above 2^53, about 0.009 ether. Every total would be wrong."""
    hours = roll_up(
        "ethereum",
        [Transfer(WALLET, BINANCE_1, Amount(50 * ETH)) for _ in range(3)],
        LABELS,
    )

    assert hours[0].inflow_value.raw == 150 * ETH


def test_the_capture_floor_of_the_hour_travels_with_the_row():
    """
    Without it "Binance took in 4,000 ETH" is asserted from a capture that
    dropped everything under one ether, and the row reads as complete.
    """
    quality = {
        hour_of(HOUR): HourQuality(
            blocks=300, complete_blocks=0, capture_floor=Amount(ETH)
        )
    }

    hours = roll_up("ethereum", [Transfer(WALLET, BINANCE_1)], LABELS, quality=quality)

    assert hours[0].capture_floor == Amount(ETH)
    assert hours[0].bounded
    assert not hours[0].all_complete


def test_an_hour_with_no_recorded_quality_claims_none():
    hours = roll_up("ethereum", [Transfer(WALLET, BINANCE_1)], LABELS)

    assert hours[0].blocks == 0
    assert hours[0].capture_floor is None
    assert not hours[0].all_complete, "an hour with no blocks recorded is not complete"


def test_the_addresses_that_moved_are_counted_not_the_ones_labelled():
    """
    A figure drawn from three of Binance's 118 addresses is a different claim
    from one drawn from all of them.
    """
    hours = roll_up(
        "ethereum",
        [Transfer(WALLET, BINANCE_1), Transfer(WALLET, BINANCE_1)],
        LABELS,
    )

    assert hours[0].addresses == 2, "the sender and the recipient, once each"


def test_the_rollup_is_deterministic():
    transfers = [
        Transfer(WALLET, COINBASE),
        Transfer(WALLET, BINANCE_1),
    ]

    first = roll_up("ethereum", transfers, LABELS)
    second = roll_up("ethereum", list(reversed(transfers)), LABELS)

    assert [hour.entity for hour in first] == [hour.entity for hour in second]


def test_totals_by_entity_ranks_by_volume_and_nets_last():
    hours = roll_up(
        "ethereum",
        [
            Transfer(WALLET, BINANCE_1, Amount(9 * ETH)),
            Transfer(BINANCE_1, WALLET, Amount(2 * ETH)),
            Transfer(WALLET, COINBASE, Amount(ETH)),
        ],
        LABELS,
    )

    totals = totals_by_entity(hours)

    assert list(totals) == ["Binance", "Coinbase"]
    assert totals["Binance"]["net_value"] == 7 * ETH


def test_the_per_transfer_counters_are_not_the_sum_of_the_rows():
    """
    Two correct views of one transfer, and they have to stay distinguishable.
    The hours say Binance and Coinbase each saw an internal movement; the
    counters say one transfer happened. A window total built by summing the
    rows would report a single rebalance as two.
    """
    stats = FlowStats()
    hours = roll_up(
        "ethereum", [Transfer(BINANCE_1, COINBASE, Amount(7 * ETH))], LABELS, stats=stats
    )

    assert sum(hour.internal_count for hour in hours) == 2
    assert stats.internal == 1
    assert stats.internal_value == 7 * ETH


def test_internal_movement_is_in_neither_side_of_the_net():
    """Folding a rebalance into either direction is how it becomes a signal."""
    stats = FlowStats()
    roll_up("ethereum", [Transfer(BINANCE_1, COINBASE)], LABELS, stats=stats)

    assert stats.net_value == 0
    assert stats.direction == "balanced"


def test_the_counters_net_deposits_against_withdrawals():
    stats = FlowStats()
    roll_up(
        "ethereum",
        [
            Transfer(WALLET, BINANCE_1, Amount(9 * ETH)),
            Transfer(BINANCE_1, WALLET, Amount(2 * ETH)),
        ],
        LABELS,
        stats=stats,
    )

    assert stats.net_value == 7 * ETH
    assert stats.direction == "inflow"


def test_an_empty_window_produces_no_rows():
    assert roll_up("ethereum", [], LABELS) == ()


def test_no_labels_means_nothing_is_attributed():
    """Every transfer is unrelated when there is nothing to relate it to."""
    stats = FlowStats()
    hours = roll_up(
        "ethereum",
        [Transfer(WALLET, BINANCE_1)],
        label_set_from([], chain="ethereum"),
        stats=stats,
    )

    assert hours == ()
    assert stats.unrelated == 1
