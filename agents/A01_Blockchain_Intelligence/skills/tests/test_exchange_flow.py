"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the exchange flow skill.

This is the first skill whose answer depends on something A01 did not observe.
A transfer's direction is a fact about the chain; that the recipient is Binance
is somebody's claim about an address. So most of what is asserted here is about
the seam between the two: no labels means the question cannot be asked at all,
an unverified list bounds the answer, and a zero is licensed by coverage or
withheld.
"""

from __future__ import annotations

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from schemas import Address
from sensors.envelope import Provenance, RawRecord, RecordKind
from skills.base import SkillRequest
from skills.exchange_flow import ExchangeFlowSkill
from tiers.ledger import EVM_SCOPE, Label, LabelRepository

TIMESTAMP = 1_700_000_000
ETH = 10**18

BINANCE_1 = "0x28c6c06298d514db089934071355e5743bf21d60"
BINANCE_2 = "0x21a31ee1afc51d94c2efccaa2092ad1028285549"
COINBASE = "0x71660c4005ba85c37ccec55d0c4493e66fe775d3"
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20


def block_record(number: int, transfers: list[tuple[str, str, int]]) -> RawRecord:
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", "ethereum", "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": f"0xa{number:06d}",
            "parentHash": f"0xa{number - 1:06d}",
            "timestamp": hex(TIMESTAMP + number * 12),
            "transactions": [
                {
                    "hash": f"0xtx{number:05d}{i:03d}",
                    "from": sender,
                    "to": recipient,
                    "value": hex(value),
                    "transactionIndex": hex(i),
                    "input": "0x",
                }
                for i, (sender, recipient, value) in enumerate(transfers)
            ],
        },
    )


def exchange_label(address: str, entity: str, **overrides) -> Label:
    fields = {
        "chain": EVM_SCOPE,
        "address": address,
        "label": f"{entity} hot",
        "entity": entity,
        "category": "exchange",
        "source": "gist:xfwil/07dadf39",
        "confidence": 0.5,
    }
    fields.update(overrides)
    return Label(**fields)


@pytest.fixture
def db():
    with Database() as database:
        writer = RecordWriter(SqliteBlockRepository(database))
        # A deposit, a withdrawal, an inter-exchange move, and traffic that
        # touches no exchange at all.
        writer.write(block_record(100, [(ALICE, BINANCE_1, 4 * ETH)]))
        writer.write(block_record(101, [(BINANCE_1, BOB, ETH)]))
        writer.write(block_record(102, [(BINANCE_1, COINBASE, 7 * ETH)]))
        writer.write(block_record(103, [(ALICE, BOB, 2 * ETH)]))
        yield database


@pytest.fixture
def labelled(db):
    repository = LabelRepository(db)
    repository.save_many(
        [
            exchange_label(BINANCE_1, "Binance"),
            exchange_label(BINANCE_2, "Binance"),
            exchange_label(COINBASE, "Coinbase"),
        ]
    )
    return SqliteAnalyticsRepository(db)


def run(analytics, **options):
    return ExchangeFlowSkill().run(
        SkillRequest(chain="ethereum", options=options), analytics
    )


# ==============================================================================
# WITHOUT LABELS THE QUESTION CANNOT BE ASKED
# ==============================================================================

def test_no_labels_means_undetermined_not_zero(db):
    """
    A flow figure of zero with no labels loaded is a confident statement about
    a rule that never ran. The distinction between "nothing arrived" and
    "nothing could be attributed" is the whole reason this returns undetermined.
    """
    result = run(SqliteAnalyticsRepository(db))

    assert not result.determined
    assert "no exchange address labels loaded" in result.reason
    assert result.subject == {}, "an undetermined skill contributes nothing"


def test_an_empty_database_with_labels_still_declines():
    with Database() as database:
        LabelRepository(database).save(exchange_label(BINANCE_1, "Binance"))

        result = run(SqliteAnalyticsRepository(database))

        assert not result.determined
        assert "no ethereum history" in result.reason


# ==============================================================================
# ATTRIBUTION
# ==============================================================================

def test_a_deposit_and_a_withdrawal_are_reported_separately(labelled):
    result = run(labelled)

    totals = result.data["totals"]

    assert result.determined
    assert totals["inflow_count"] == 1
    assert totals["outflow_count"] == 1
    assert totals["internal_count"] == 1


def test_the_window_total_counts_a_transfer_once_however_many_sides_it_had(labelled):
    """
    The Binance-to-Coinbase move is recorded on both operators' hours, and that
    is right: it is a fact about each of them. Summing those rows into a window
    total would report one rebalance as two, so the total comes from the
    per-transfer counters instead.
    """
    result = run(labelled)

    per_entity = sum(
        entry["internal_count"] for entry in result.data["entities"].values()
    )

    assert result.data["totals"]["internal_count"] == 1, "one transfer happened"
    assert per_entity == 2, "and it concerned two operators"


def test_an_inter_exchange_transfer_is_not_counted_as_a_deposit(labelled):
    """
    The seven-ether move from Binance to Coinbase is the exchange's own money.
    Counted as inflow it produces sell pressure with nobody behind it.
    """
    result = run(labelled)

    assert result.data["entities"]["Coinbase"]["inflow_count"] == 0
    assert result.data["entities"]["Coinbase"]["internal_count"] == 1


def test_flow_is_attributed_to_the_operator(labelled):
    result = run(labelled)

    assert set(result.data["entities"]) == {"Binance", "Coinbase"}


def test_unrelated_traffic_is_counted_and_excluded(labelled):
    """
    The block of wallet-to-wallet traffic must not vanish: a reader has to see
    how much of the window the labels actually explain.
    """
    result = run(labelled)

    assert result.data["filter"]["unrelated"] == 1
    assert result.data["filter"]["seen"] == 4


def test_the_label_source_travels_with_the_answer(labelled):
    """
    The figure inherits the list's authority. A flow total whose source cannot
    be named afterwards cannot be checked.
    """
    result = run(labelled)

    assert result.data["label_source"] == "gist:xfwil/07dadf39"


# ==============================================================================
# BOUNDS
# ==============================================================================

def test_the_answer_states_that_tokens_are_not_covered(labelled):
    """
    Stablecoins dominate real exchange traffic and are ERC-20 transfers, which
    this does not attribute. Silence there would overstate the coverage.
    """
    result = run(labelled)

    assert any("native value only" in bound for bound in result.data["bounds"])


def test_an_unverified_list_bounds_the_answer(labelled):
    result = run(labelled)

    assert any("unverified" in bound for bound in result.data["bounds"])


def test_the_reported_confidence_is_the_weakest_label_not_the_best(db):
    """
    Which label an attribution rested on is not recorded per transfer, so
    anything read off this answer could be resting on the weakest one. A
    ceiling taken from the strongest would be a ceiling nothing guarantees.
    """
    LabelRepository(db).save_many(
        [
            exchange_label(BINANCE_1, "Binance", confidence=0.95, verification_status="verified"),
            exchange_label(COINBASE, "Coinbase", confidence=0.5),
        ]
    )

    result = run(SqliteAnalyticsRepository(db))

    assert result.data["label_confidence"] == 0.5
    assert any("confidence 0.5" in bound for bound in result.data["bounds"])


def test_the_incompleteness_of_the_label_list_is_stated(labelled):
    """No exchange list is complete, and an unlisted address is invisible."""
    result = run(labelled)

    assert any("no exchange list is complete" in bound for bound in result.data["bounds"])


def test_a_capped_scan_makes_every_total_a_floor(labelled):
    result = run(labelled, scan_limit=1)

    assert any("row cap" in bound for bound in result.data["bounds"])


# ==============================================================================
# THE NEGATIVE CLAIM
# ==============================================================================

def test_a_shallow_window_with_no_flow_declines_rather_than_reporting_zero(db):
    """
    "No exchange deposits" from a four-block window is a statement about
    storage wearing the clothes of a statement about the chain.
    """
    LabelRepository(db).save(exchange_label(BINANCE_2, "Binance"))

    result = run(SqliteAnalyticsRepository(db))

    assert not result.determined
    assert result.data["absence_licensed"] is False
    assert "cannot license an absence" in result.reason


def test_a_deep_window_with_no_flow_licenses_the_absence(db):
    """
    The other side of the same gate: with enough contiguous, complete history,
    "nothing arrived" becomes a claim the window can carry.
    """
    LabelRepository(db).save(exchange_label(BINANCE_2, "Binance"))
    skill = ExchangeFlowSkill(absence_threshold=2)

    result = skill.run(
        SkillRequest(chain="ethereum"), SqliteAnalyticsRepository(db)
    )

    assert result.determined
    assert result.data["absence_licensed"] is True
    assert "no transfer in the stored window" in result.reason


def test_a_present_flow_never_touches_the_absence_gate(labelled):
    """A positive claim needs no coverage licence; only a negative one does."""
    result = run(labelled)

    assert "absence_licensed" not in result.data


# ==============================================================================
# NO INTERPRETATION
# ==============================================================================

def test_the_result_describes_direction_and_never_intent(labelled):
    """
    Deposits are consistent with an intent to sell and with collateral, market
    making and custody migration. The evidence standard forbids naming which.
    """
    rendered = str(result_text(run(labelled)))

    for forbidden in ("bullish", "bearish", "sell pressure", "dump", "accumulation"):
        assert forbidden not in rendered.lower(), f"{forbidden} is a judgement, not an observation"


def result_text(result) -> str:
    return f"{result.reason} {result.data}"


def test_direction_is_one_of_three_stated_words(labelled):
    assert run(labelled).data["totals"]["direction"] in ("inflow", "outflow", "balanced")


# ==============================================================================
# COMPOSITION
# ==============================================================================

def test_the_skill_contributes_its_flow_to_the_subject(labelled):
    result = run(labelled)

    assert "exchange_flow" in result.subject
    assert result.subject["exchange_flow_hours"], "the hours travel for the rollup"


def test_the_skill_appears_in_the_registry_with_its_bound():
    from skills import default_registry
    from skills.registry import Readiness

    entry = default_registry().entry("exchange_flow")

    assert entry.readiness is Readiness.LIMITED
    assert "label list" in entry.bounded_by
