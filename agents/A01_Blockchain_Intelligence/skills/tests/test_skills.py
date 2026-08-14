"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the skills layer -- what an answer means, and when it means nothing.

The property under test throughout is coverage honesty. A skill reading a
four-block database must not report that an address has no history, because
that is true of the database and false of the chain, and the number itself
shows no difference. Most of these tests exist to prove the shallow case
declines rather than answers.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from pipeline import MaterialityGate, SelectiveWriter
from schemas import Address, Amount
from sensors.envelope import CaptureGap, Provenance, RawRecord, RecordKind
from tiers import BlockAggregateRepository
from skills import (
    Coverage,
    SkillRegistry,
    SkillRequest,
    TokenFlowSkill,
    WalletProfileSkill,
    WhaleTransferSkill,
    default_registry,
)
from skills.registry import PLANNED_SKILLS, Readiness, SkillEntry
from skills.whale_detection.transfers import MIN_POPULATION

TIMESTAMP = 1_700_000_000
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
CAROL = "0x" + "c3" * 20


def block_record(number: int, transfers: list[tuple[str, str, int]]) -> RawRecord:
    """A raw block carrying the given (from, to, value) transfers."""
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


@pytest.fixture
def stored():
    """
    A database holding a small, contiguous slice of history.

    Deliberately shallow: this is the situation the layer has to be honest
    about, so it is the default the tests run against.
    """
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.write(block_record(100, [(ALICE, BOB, 10**18)]))
        writer.write(block_record(101, [(BOB, CAROL, 5 * 10**18), (ALICE, CAROL, 10**24)]))
        writer.write(block_record(102, [(CAROL, ALICE, 2 * 10**18)]))
        yield SqliteAnalyticsRepository(db)


def request_for(address: str | None = None, **options) -> SkillRequest:
    parsed = Address.parse(address, "ethereum") if address else None
    return SkillRequest(chain="ethereum", address=parsed, options=options)


# ==============================================================================
# COVERAGE
# ==============================================================================

def test_a_shallow_window_licenses_no_absence_claim(stored):
    """The core guarantee: three blocks cannot say an address is inactive."""
    coverage = WalletProfileSkill().coverage_for(request_for(), stored)

    assert coverage.blocks == 3
    assert not coverage.supports_absence
    assert "3600 needed" in coverage.limitation


def test_a_deep_contiguous_window_licenses_absence(stored):
    skill = WalletProfileSkill(absence_threshold=2)
    coverage = skill.coverage_for(request_for(), stored)

    assert coverage.supports_absence
    assert coverage.limitation == ""


def test_a_window_with_an_incomplete_block_never_licenses_absence():
    """
    Contiguity is not enough either, and this is the one that was missed.

    Every height present, no holes, deep enough for the threshold — and still
    unable to carry a negative claim, because one of those blocks was stored
    without the logs it was asked for. Its transfers are missing, not absent.
    Counting it toward an absence is how "no transfers for this address" gets
    asserted from a fetch that never happened.
    """
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.write(block_record(100, [(ALICE, BOB, 10**18)]))
        writer.write(block_record(101, [(BOB, CAROL, 10**18)]))
        writer.write(
            replace(
                block_record(102, [(CAROL, ALICE, 10**18)]),
                capture_gaps=(CaptureGap.LOGS,),
            )
        )
        analytics = SqliteAnalyticsRepository(db)

        coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        )

        assert coverage.blocks == 3
        assert coverage.window.contiguous, "the failure must not be a holed window"
        assert coverage.window.incomplete_blocks == 1
        assert not coverage.supports_absence
        assert "1 of 3 stored blocks are incomplete" in coverage.limitation


def test_a_window_with_holes_never_licenses_absence():
    """
    Depth alone is not enough. An event may sit in a gap, so a count from a
    holed window is a floor rather than a total.
    """
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        for number in (100, 101, 105):  # 102-104 never stored
            writer.write(block_record(number, [(ALICE, BOB, 10**18)]))
        analytics = SqliteAnalyticsRepository(db)

        coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        )

        assert coverage.blocks == 3
        assert not coverage.window.contiguous
        assert not coverage.supports_absence
        assert "gaps" in coverage.limitation


def selectively_captured(db, numbers, *, floor=10**18, refused=()):
    """
    Store blocks the way live selective capture stores them.

    Through the real :class:`SelectiveWriter` rather than by hand, because what
    is under test is whether the reason survives the whole path -- gate, quality
    report, repository, column, window. A hand-written row would prove only that
    the last step works.
    """
    writer = SelectiveWriter(
        SqliteBlockRepository(db),
        BlockAggregateRepository(db),
        gate=MaterialityGate(floor=Amount(floor)),
    )
    for number in numbers:
        record = block_record(number, [(ALICE, BOB, 10**15)])  # far below any floor
        if number in refused:
            record = replace(record, capture_gaps=(CaptureGap.LOGS,))
        writer.write(record)
    return SqliteAnalyticsRepository(db)


def test_a_selectively_captured_window_licenses_an_absence_above_its_floor():
    """
    The gate that was shut by its own success.

    Selective capture drops what is below a stated floor, so every block it
    writes is incomplete -- and `complete = 0` was all that reached storage, so
    a selectively captured window read exactly like a window of refused fetches
    and could never license anything. But the two are not the same. A refused
    fetch is missing transfers nobody can describe; a filtered block is missing
    everything below a number that was written down. That supports a real claim
    with a stated edge, and refusing it throws away the point of filtering.
    """
    with Database() as db:
        analytics = selectively_captured(db, range(100, 105), floor=13 * 10**18)

        coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        )

        assert coverage.window.contiguous
        assert coverage.window.selective_blocks == 5
        assert coverage.window.unfetched_blocks == 0
        assert coverage.supports_bounded_absence
        assert coverage.absence_floor is not None
        assert coverage.absence_floor.raw == 13 * 10**18


def test_a_bounded_window_still_refuses_the_unqualified_claim():
    """
    `supports_absence` answers for the whole window, floor included, so it must
    stay false. A bounded claim read as an unbounded one is the failure; the
    reverse only costs a claim that could have been made.
    """
    with Database() as db:
        analytics = selectively_captured(db, range(100, 105))

        coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        )

        assert not coverage.supports_absence
        assert coverage.supports_bounded_absence


def test_a_bounded_window_answers_at_the_floor_and_not_below_it():
    """The question a caller actually has, and the only honest answer to it."""
    with Database() as db:
        analytics = selectively_captured(db, range(100, 105), floor=10 * 10**18)

        coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        )

        assert coverage.supports_absence_above(Amount(10 * 10**18)), "at the floor"
        assert coverage.supports_absence_above(Amount(500 * 10**18)), "above it"
        assert not coverage.supports_absence_above(Amount(10**18)), "below it"


def test_a_selective_window_is_not_described_as_a_fetch_that_never_happened():
    """
    The message an operator acts on. Told that transfers "were never fetched",
    someone goes looking for a broken provider; the transfers were fetched,
    counted, and dropped on purpose at a floor this line now states.
    """
    with Database() as db:
        analytics = selectively_captured(db, range(100, 105), floor=13 * 10**18)

        limitation = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        ).limitation

        assert "never fetched" not in limitation
        assert "13000000000000000000" in limitation
        assert "at or above that floor, not below it" in limitation


def test_one_unfetched_block_closes_the_gate_over_every_filtered_one():
    """
    Bounded and unbounded do not average. One block whose logs were refused
    leaves the window silent about a range nothing can describe, and a floor
    elsewhere in the window says nothing about that range.
    """
    with Database() as db:
        analytics = selectively_captured(db, range(100, 105), refused=(102,))

        coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
            request_for(), analytics
        )

        assert coverage.window.selective_blocks == 4
        assert coverage.window.unfetched_blocks == 1
        assert not coverage.supports_bounded_absence
        assert coverage.absence_floor is None
        # Counted over unfetched blocks alone. Counting every incomplete block
        # here was the bug: it reported five, four of which were deliberate.
        assert "1 of 5 stored blocks" in coverage.limitation


def test_a_window_captured_whole_needs_no_floor(stored):
    """
    The unfiltered path keeps its meaning: a floor of zero is every transfer
    there is, so the bounded claim and the unqualified one are the same claim.
    """
    coverage = WalletProfileSkill(absence_threshold=2).coverage_for(
        request_for(), stored
    )

    assert coverage.supports_absence
    assert coverage.absence_floor == Amount(0)
    assert coverage.window.capture_floor is None


def test_an_empty_database_says_so(stored):
    with Database() as empty:
        coverage = WalletProfileSkill().coverage_for(
            request_for(), SqliteAnalyticsRepository(empty)
        )
        assert coverage.empty
        assert "no history stored" in coverage.limitation


# ==============================================================================
# WALLET PROFILE
# ==============================================================================

def test_wallet_profile_counts_both_directions(stored):
    result = WalletProfileSkill().run(request_for(ALICE), stored)

    assert result.determined
    assert result.data["sent_count"] == 2
    assert result.data["received_count"] == 1
    assert result.data["counterparties"] == 2


def test_wallet_profile_sums_exactly_past_the_64_bit_ceiling(stored):
    """Alice sent 1 ETH and 1,000,000 ETH; the total must not be truncated."""
    result = WalletProfileSkill().run(request_for(ALICE), stored)

    assert int(result.data["sent_total"]["raw"]) == 10**18 + 10**24


def test_wallet_profile_withholds_timing_when_the_window_is_thin(stored):
    """
    A last_outbound_at from three blocks would tell the dormancy detector that
    a busy address has been silent, and the detector cannot see the artefact.
    """
    result = WalletProfileSkill().run(request_for(ALICE), stored)

    assert result.subject["dormancy_determinable"] is False
    assert "last_outbound_at" not in result.subject
    assert "first_seen_at" not in result.subject


def test_wallet_profile_supplies_timing_once_the_window_is_deep_enough(stored):
    result = WalletProfileSkill(absence_threshold=2).run(request_for(ALICE), stored)

    assert result.subject["dormancy_determinable"] is True
    assert "last_outbound_at" in result.subject


def test_wallet_profile_never_reports_a_balance(stored):
    """
    Storage holds transfers, not state. A summed window presented as a balance
    would satisfy the dormancy detector's materiality check with a wrong number.
    """
    result = WalletProfileSkill(absence_threshold=2).run(request_for(ALICE), stored)
    assert "balance" not in result.subject


def test_an_unseen_address_is_reported_as_unseen_not_inactive(stored):
    unknown = "0x" + "f0" * 20
    result = WalletProfileSkill().run(request_for(unknown), stored)

    assert result.determined
    assert result.data["seen_in_window"] is False
    assert result.data["absence_meaningful"] is False
    assert "3600 needed" in result.reason


def test_wallet_profile_requires_an_address(stored):
    result = WalletProfileSkill().run(request_for(), stored)

    assert not result.determined
    assert "requires an address" in result.reason


# ==============================================================================
# WHALE TRANSFERS
# ==============================================================================

def test_whale_skill_supplies_the_population_the_detector_needs(stored):
    """
    DET-WHALE-01 refuses absolute thresholds, so it needs a population it
    cannot fetch for itself. Supplying it is this skill's whole purpose.
    """
    result = WhaleTransferSkill().run(request_for(), stored)

    assert result.determined
    assert result.subject["transfer_population"]
    assert len(result.subject["transfer_population"]) == 4


def test_a_thin_population_is_flagged_rather_than_used_silently(stored):
    """The 99.9th percentile of four transfers is just the biggest of four."""
    result = WhaleTransferSkill().run(request_for(), stored)

    assert result.data["population_usable"] is False
    assert str(MIN_POPULATION) in result.data["population_note"]


def test_transfers_are_scoped_to_the_address_when_one_is_given(stored):
    result = WhaleTransferSkill().run(request_for(BOB), stored)

    involved = {t["counterparty"] for t in result.data["transfers"]}
    assert result.data["transfer_count"] == 2
    assert BOB not in involved


def test_direction_is_relative_to_the_address_asked_about(stored):
    """A transfer has no intrinsic direction; only one relative to a party."""
    outbound = WhaleTransferSkill().run(request_for(ALICE), stored)
    directions = {t["direction"] for t in outbound.data["transfers"]}

    assert "out" in directions
    assert "in" in directions


def test_no_usd_value_is_invented(stored):
    """A01 ingests no price feed; a fabricated figure would trip the USD floor."""
    result = WhaleTransferSkill().run(request_for(ALICE), stored)

    assert all(t["usd_value"] == 0.0 for t in result.subject["large_transfers"])


def test_counterparty_type_is_unknown_not_guessed(stored):
    """
    Guessing 'exchange' would invent the sell-pressure signal the detector
    reports from it.
    """
    result = WhaleTransferSkill().run(request_for(ALICE), stored)

    assert all(
        t["counterparty_type"] == "unknown" for t in result.subject["large_transfers"]
    )


# ==============================================================================
# TOKEN FLOW
# ==============================================================================

def test_flow_reports_gross_and_net_separately(stored):
    """
    A net of zero can mean no activity or a hundred million each way. Reporting
    only the net makes the two identical.
    """
    result = TokenFlowSkill().run(request_for(ALICE), stored)

    assert int(result.data["gross_out"]["raw"]) == 10**18 + 10**24
    assert int(result.data["gross_in"]["raw"]) == 2 * 10**18
    assert result.data["net_direction"] == "net_outflow"


def test_flow_reports_concentration(stored):
    """One transfer at 99% is not sustained activity, however large the total."""
    result = TokenFlowSkill().run(request_for(ALICE), stored)

    assert result.data["concentration"] > 0.99
    assert result.data["single_transfer_dominated"] is True


def test_chain_wide_flow_has_no_direction(stored):
    """Every transfer is both an inflow and an outflow; a chain net is zero."""
    result = TokenFlowSkill().run(request_for(), stored)

    assert result.data["net_direction"] == "not_applicable"


def test_flow_covers_native_and_tokens_and_says_they_cannot_be_summed(stored):
    """
    They are denominated in different units, and one of those units has an
    unknown exponent. A total across them looks entirely ordinary and means
    nothing.
    """
    result = TokenFlowSkill().run(request_for(ALICE), stored)

    assert result.data["scope"] == "native_and_tokens"
    assert "must not" in result.data["scope_note"]
    assert "token_flows" in result.data


def test_token_flow_is_reported_per_contract(stored_with_tokens):
    """
    A cross-token total adds a 6-decimal token's units to an 18-decimal
    token's, so the result is decided by which contract uses more digits.
    """
    analytics, usdc, bigtoken = stored_with_tokens
    result = TokenFlowSkill().run(request_for(ALICE), analytics)

    flows = {row["token"]: row for row in result.data["token_flows"]}
    assert set(flows) == {usdc, bigtoken}
    assert all(row["decimals_known"] is False for row in flows.values())


def test_an_address_with_only_token_movement_is_not_reported_as_inactive(
    stored_with_tokens,
):
    """
    On L2 this is the normal case: native value is zero and everything real
    happens in tokens. Declining here would report a busy address as idle.
    """
    analytics, _, _ = stored_with_tokens
    result = TokenFlowSkill().run(request_for(CAROL), analytics)

    assert result.subject["flow_determinable"] is True
    assert result.data["transfer_count"] == 0, "no native movement"
    assert result.data["tokens_touched"] >= 1
    assert "no native movement" in result.reason


def test_token_flows_stay_out_of_the_native_observed_flow(stored_with_tokens):
    """
    A detector reading `observed_flow` expects one denomination. Mixing token
    figures in would put raw base units where wei is expected.
    """
    analytics, _, _ = stored_with_tokens
    result = TokenFlowSkill().run(request_for(ALICE), analytics)

    assert "token_flows" not in result.subject["observed_flow"]
    assert "token_flows" in result.subject


def test_an_address_with_no_transfers_is_not_determinable(stored):
    result = TokenFlowSkill().run(request_for("0x" + "f0" * 20), stored)

    assert result.subject["flow_determinable"] is False


def test_flow_arithmetic_is_exact(stored):
    """Float accumulation would lose the digits that distinguish large sums."""
    result = TokenFlowSkill().run(request_for(ALICE), stored)

    assert int(result.data["total_moved"]["raw"]) == 10**18 + 10**24 + 2 * 10**18


# ==============================================================================
# REQUESTS
# ==============================================================================

def test_a_request_refuses_an_address_from_another_chain():
    with pytest.raises(ValueError):
        SkillRequest(chain="ethereum", address=Address.parse(ALICE, "polygon"))


def test_a_request_refuses_an_inverted_range():
    with pytest.raises(ValueError):
        SkillRequest(chain="ethereum", from_height=100, to_height=50)


# ==============================================================================
# REGISTRY
# ==============================================================================

def test_only_implemented_skills_are_registered():
    """
    Fourteen folders hold a .gitkeep. Listing them would turn a plan into an
    advertised capability.

    ``exchange_flow`` joined this set when address labels became loadable, and
    it is the only entry here whose answer depends on data A01 did not observe
    itself -- which is why it is LIMITED and says so.
    """
    registry = default_registry()

    assert set(registry.names()) == {
        "wallet_profile",
        "whale_transfers",
        "token_flow",
        "exchange_flow",
    }
    assert "exchange_flow" not in PLANNED_SKILLS


def test_every_registered_skill_declares_what_bounds_it():
    for entry in default_registry():
        assert entry.readiness is not Readiness.PLANNED
        if entry.readiness is Readiness.LIMITED:
            assert entry.bounded_by, f"{entry.name} is limited but says by what"


def test_unbuilt_skills_record_why():
    """An unexplained absence is indistinguishable from an oversight."""
    planned = default_registry().planned()

    assert {e["name"] for e in planned} == set(PLANNED_SKILLS)
    assert all(e["blocked_by"] for e in planned)


def test_smart_money_is_not_registered():
    """
    It needs prices and entity labels A01 does not ingest. A ranking built
    without them would order addresses by activity under the name of skill.
    """
    registry = default_registry()

    assert "smart_money" not in registry.names()
    assert "smart_money" in PLANNED_SKILLS


def test_an_unknown_skill_names_what_is_available():
    with pytest.raises(KeyError) as excinfo:
        default_registry().get("nope")
    assert "wallet_profile" in str(excinfo.value)


def test_a_registered_skill_can_be_replaced():
    registry = SkillRegistry()
    replacement = WalletProfileSkill(absence_threshold=1)
    registry.register(SkillEntry(replacement, Readiness.IMPLEMENTED))

    assert registry.get("wallet_profile") is replacement


# ==============================================================================
# TOKENS
# ==============================================================================

USDC = "0x" + "c6" * 20
BIGTOKEN = "0x" + "d8" * 20
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def topic(address: str) -> str:
    return "0x" + address[2:].rjust(64, "0")


def log_of(token: str, sender: str, recipient: str, value: int, index: int) -> dict:
    return {
        "address": token,
        "topics": [TRANSFER_SIG, topic(sender), topic(recipient)],
        "data": "0x" + f"{value:064x}",
        "transactionHash": f"0xtx{index:04d}",
        "blockHash": "0xa000100",
        "blockNumber": hex(100),
        "logIndex": hex(index),
    }


@pytest.fixture
def stored_with_tokens():
    """
    One block with native transfers plus token transfers, including an address
    (CAROL) that moves tokens and no native value at all.
    """
    from database import SqliteTokenRepository
    from sensors.envelope import Provenance

    with Database() as db:
        writer = RecordWriter(
            SqliteBlockRepository(db), tokens=SqliteTokenRepository(db)
        )
        writer.write(block_record(100, [(ALICE, BOB, 10**18)]))
        writer.write(
            RawRecord(
                chain="ethereum",
                kind=RecordKind.LOGS,
                height=100,
                provenance=Provenance("fixture", "ethereum", "eth_getLogs", "ok"),
                payload=[
                    log_of(USDC, ALICE, BOB, 1_000_000, 0),
                    log_of(BIGTOKEN, ALICE, BOB, 10**18, 1),
                    log_of(USDC, CAROL, BOB, 500_000, 2),
                ],
            )
        )
        yield SqliteAnalyticsRepository(db), USDC, BIGTOKEN
