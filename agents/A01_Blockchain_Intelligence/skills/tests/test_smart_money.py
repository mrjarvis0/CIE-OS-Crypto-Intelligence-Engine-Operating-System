"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the smart-money skill.

The headline property is coverage honesty -- shared with every other skill --
but the smart-money-specific tests are about behavioral signals: first-mover
timing, counterparty diversity, and size discipline. These are the signals
that stand in for profitability, which needs prices A01 does not ingest.
"""

from __future__ import annotations

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from schemas import Address
from sensors.envelope import Provenance, RawRecord, RecordKind
from skills.base import SkillRequest
from skills.smart_money import SmartMoneySkill
from tiers.ledger import EVM_SCOPE, Label, LabelRepository

TIMESTAMP = 1_700_000_000
ETH = 10**18

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
CAROL = "0x" + "c3" * 20
DAVE = "0x" + "d4" * 20
EVE = "0x" + "e5" * 20


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


def smart_money_label(address: str, entity: str, **overrides) -> Label:
    fields = {
        "chain": EVM_SCOPE,
        "address": address,
        "label": f"{entity} wallet",
        "entity": entity,
        "category": "smart_money",
        "source": "internal:research",
        "confidence": 0.7,
    }
    fields.update(overrides)
    return Label(**fields)


def request_for(address: str | None = None, **options) -> SkillRequest:
    parsed = Address.parse(address, "ethereum") if address else None
    return SkillRequest(chain="ethereum", address=parsed, options=options)


FRANK = "0x" + "f6" * 20
GRACE = "0x" + "a7" * 20


@pytest.fixture
def db():
    """
    A database where ALICE acts before the crowd: she reaches BOB, CAROL, and
    DAVE at earlier heights than everyone else. The crowd (FRANK, GRACE)
    arrives before EVE, making EVE clearly late.
    """
    with Database() as database:
        writer = RecordWriter(SqliteBlockRepository(database))
        # ALICE is an early mover: reaches counterparties first
        writer.write(block_record(100, [(ALICE, BOB, 2 * ETH)]))
        writer.write(block_record(101, [(ALICE, CAROL, 3 * ETH)]))
        writer.write(block_record(102, [(ALICE, DAVE, 1 * ETH)]))
        # The crowd follows: FRANK and GRACE arrive before EVE
        writer.write(block_record(105, [(FRANK, BOB, ETH)]))
        writer.write(block_record(106, [(FRANK, CAROL, ETH)]))
        writer.write(block_record(107, [(FRANK, DAVE, ETH)]))
        writer.write(block_record(108, [(GRACE, BOB, ETH)]))
        writer.write(block_record(109, [(GRACE, CAROL, ETH)]))
        writer.write(block_record(110, [(GRACE, DAVE, ETH)]))
        # EVE is late: arrives after the crowd
        writer.write(block_record(115, [(EVE, BOB, ETH)]))
        writer.write(block_record(116, [(EVE, CAROL, ETH)]))
        writer.write(block_record(117, [(EVE, DAVE, ETH)]))
        yield database


@pytest.fixture
def analytics(db):
    return SqliteAnalyticsRepository(db)


# ==============================================================================
# BASIC REQUIREMENTS
# ==============================================================================

def test_requires_an_address(analytics):
    result = SmartMoneySkill().run(request_for(), analytics)
    assert not result.determined
    assert "requires an address" in result.reason


def test_empty_database_declines():
    with Database() as empty:
        result = SmartMoneySkill().run(
            request_for(ALICE), SqliteAnalyticsRepository(empty)
        )
        assert not result.determined
        assert "no ethereum history" in result.reason


def test_unseen_address_without_label(analytics):
    unknown = "0x" + "f0" * 20
    result = SmartMoneySkill().run(request_for(unknown), analytics)

    assert result.determined
    assert result.data["seen_in_window"] is False
    assert result.subject == {}


# ==============================================================================
# LABEL INTEGRATION
# ==============================================================================

def test_labelled_address_with_activity(db):
    LabelRepository(db).save(smart_money_label(ALICE, "AlphaTrader"))
    result = SmartMoneySkill().run(request_for(ALICE), SqliteAnalyticsRepository(db))

    assert result.determined
    assert result.data["labelled_smart_money"] is True
    assert result.data["label_entity"] == "AlphaTrader"
    assert result.subject["labelled_smart_money"] is True
    assert result.subject["track_record"] == 1.0


def test_labelled_unseen_address(db):
    LabelRepository(db).save(smart_money_label("0x" + "f0" * 20, "GhostWhale"))
    result = SmartMoneySkill().run(
        request_for("0x" + "f0" * 20), SqliteAnalyticsRepository(db)
    )

    assert result.determined
    assert result.data["labelled_smart_money"] is True
    assert result.data["seen_in_window"] is False
    assert result.subject["behavioral_evidence"] is False
    assert "no activity" in result.reason


def test_unlabelled_address_still_reports_behavior(analytics):
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    assert result.determined
    assert result.data["labelled_smart_money"] is False
    assert "early_mover_ratio" in result.subject


# ==============================================================================
# FIRST-MOVER TIMING
# ==============================================================================

def test_an_early_mover_has_high_ratio(analytics):
    """ALICE reached BOB, CAROL, DAVE before anyone else."""
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    timing = result.data["first_mover"]
    assert timing["determinable"] is True
    assert timing["early_mover_ratio"] >= 0.5
    assert timing["early_arrivals"] >= 2


def test_a_late_mover_has_low_ratio(analytics):
    """EVE reached the same counterparties after ALICE."""
    result = SmartMoneySkill().run(request_for(EVE), analytics)

    timing = result.data["first_mover"]
    assert timing["early_mover_ratio"] < 0.5


def test_first_mover_needs_enough_counterparties():
    """One counterparty is not enough to judge."""
    with Database() as database:
        writer = RecordWriter(SqliteBlockRepository(database))
        writer.write(block_record(100, [(ALICE, BOB, ETH)]))
        analytics = SqliteAnalyticsRepository(database)

        result = SmartMoneySkill().run(request_for(ALICE), analytics)

        assert result.data["first_mover"]["determinable"] is False


# ==============================================================================
# COUNTERPARTY DIVERSITY
# ==============================================================================

def test_diverse_counterparties_are_reported(analytics):
    """ALICE interacts with BOB, CAROL, DAVE: 3 unique out of 3 transfers."""
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    profile = result.data["counterparty_profile"]
    assert profile["unique_counterparties"] == 3
    assert profile["diverse"] is True
    assert profile["diversity_ratio"] == 1.0


def test_concentrated_counterparties_are_flagged():
    """One address sending to the same recipient repeatedly is not diverse."""
    with Database() as database:
        writer = RecordWriter(SqliteBlockRepository(database))
        writer.write(block_record(100, [(ALICE, BOB, ETH)]))
        writer.write(block_record(101, [(ALICE, BOB, 2 * ETH)]))
        writer.write(block_record(102, [(ALICE, BOB, 3 * ETH)]))
        analytics = SqliteAnalyticsRepository(database)

        result = SmartMoneySkill().run(request_for(ALICE), analytics)

        profile = result.data["counterparty_profile"]
        assert profile["unique_counterparties"] == 1
        assert profile["diverse"] is False
        assert profile["top_counterparty_share"] == 1.0


# ==============================================================================
# SIZE DISCIPLINE
# ==============================================================================

def test_consistent_sizes_are_disciplined(analytics):
    """ALICE sends 2, 3, 1 ETH: CV < 1.0 → disciplined."""
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    discipline = result.data["size_discipline"]
    assert discipline["determinable"] is True
    assert discipline["coefficient_of_variation"] < 1.0
    assert discipline["disciplined"] is True


def test_one_transfer_is_not_enough_for_discipline():
    with Database() as database:
        writer = RecordWriter(SqliteBlockRepository(database))
        writer.write(block_record(100, [(ALICE, BOB, ETH)]))
        analytics = SqliteAnalyticsRepository(database)

        result = SmartMoneySkill().run(request_for(ALICE), analytics)

        assert result.data["size_discipline"]["determinable"] is False


# ==============================================================================
# BOUNDS
# ==============================================================================

def test_profitability_bound_is_always_stated(analytics):
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    assert any("no price feed" in b for b in result.data["bounds"])


def test_first_mover_bound_is_stated(analytics):
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    assert any("stored population" in b for b in result.data["bounds"])


def test_no_labels_bound_is_stated(analytics):
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    assert any("no smart_money labels" in b for b in result.data["bounds"])


def test_unverified_label_bound_is_stated(db):
    LabelRepository(db).save(smart_money_label(ALICE, "Trader", confidence=0.5))
    result = SmartMoneySkill().run(request_for(ALICE), SqliteAnalyticsRepository(db))

    assert any("unverified" in b for b in result.data["bounds"])


# ==============================================================================
# SUBJECT FOR SCORER
# ==============================================================================

def test_early_mover_feeds_profitable_trades(analytics):
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    assert result.subject["profitable_trades"] > 0.0


def test_late_mover_gets_zero_profitable_trades(analytics):
    result = SmartMoneySkill().run(request_for(EVE), analytics)

    assert result.subject["profitable_trades"] == 0.0


def test_subject_carries_all_behavioral_dimensions(analytics):
    result = SmartMoneySkill().run(request_for(ALICE), analytics)

    assert "early_mover_ratio" in result.subject
    assert "counterparty_diversity" in result.subject
    assert "size_cv" in result.subject
    assert "observed_transaction_count" in result.subject
