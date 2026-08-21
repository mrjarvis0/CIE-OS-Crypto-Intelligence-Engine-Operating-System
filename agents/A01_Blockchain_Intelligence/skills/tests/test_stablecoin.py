"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the stablecoin skill.

The property that earns this file is that the dollar figure is right where raw
units are wrong. A USDC transfer stored as 140261088 base units is $140.26, and
a BNB-chain USDC transfer of 5e18 base units is $5.00, not $5e12 -- the skill
gets both because the decimals travel per contract, and a reader can finally sum
across two stablecoins that a raw-unit total could never combine.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from database import (
    Database,
    RecordWriter,
    SqliteAnalyticsRepository,
    SqliteBlockRepository,
    SqliteTokenRepository,
)
from schemas import Address, Amount
from schemas.token import CanonicalTokenTransfer, TokenActivity
from sensors.envelope import Provenance, RawRecord, RecordKind
from skills.base import SkillRequest
from skills.stablecoin import StablecoinSkill

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
USDC_ETH = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI_ETH = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC_BNB = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
NOT_A_STABLE = "0x" + "cc" * 20


def block_hash(number: int) -> str:
    return f"0x{number:07d}"


def block_record(chain: str, number: int) -> RawRecord:
    return RawRecord(
        chain=chain,
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", chain, "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": block_hash(number),
            "parentHash": block_hash(number - 1),
            "timestamp": hex(1_700_000_000 + number * 12),
            "transactions": [],
        },
    )


def transfer(chain, token, sender, to, value, number=100, index=0):
    return CanonicalTokenTransfer(
        chain=chain,
        tx_hash=f"0xtx{index:04d}",
        log_index=index,
        block_number=number,
        block_hash=block_hash(number),
        token=Address.parse(token, chain),
        from_address=Address.parse(sender, chain),
        to_address=Address.parse(to, chain),
        value=Amount(value, decimals=0),
    )


def seed(db, chain, *transfers, number=100):
    RecordWriter(SqliteBlockRepository(db)).write(block_record(chain, number))
    SqliteTokenRepository(db).save(
        TokenActivity(
            chain=chain,
            block_number=number,
            block_hash=block_hash(number),
            transfers=tuple(transfers),
        )
    )


def run(db, chain, address=None):
    request = SkillRequest(
        chain=chain,
        address=Address.parse(address, chain) if address else None,
    )
    return StablecoinSkill().run(request, SqliteAnalyticsRepository(db))


# ==============================================================================
# NORMALISATION
# ==============================================================================

def test_a_usdc_flow_is_reported_in_dollars_not_raw_units():
    with Database() as db:
        seed(
            db,
            "ethereum",
            transfer("ethereum", USDC_ETH, BOB, ALICE, 140_261_088, index=0),
            transfer("ethereum", USDC_ETH, ALICE, BOB, 100_000_000, index=1),
        )
        result = run(db, "ethereum", ALICE)

        assert result.determined
        assert result.data["total_in_usd"] == "140.261088"
        assert result.data["total_out_usd"] == "100"
        assert result.data["net_usd"] == "40.261088"
        assert result.data["net_direction"] == "net_inflow"

        flow = result.data["flows"][0]
        assert flow["symbol"] == "USDC"
        assert flow["decimals"] == 6
        assert flow["decimals_known"] is True
        # The raw integer is kept alongside the normalised figure.
        assert flow["gross_in"] == "140261088"


def test_bnb_chain_usdc_normalises_at_eighteen_decimals():
    """The correctness guard: BNB-chain USDC is 18 decimals, so 5e18 base units
    is $5.00. At six it would read as five trillion."""
    with Database() as db:
        seed(
            db,
            "bnb_chain",
            transfer("bnb_chain", USDC_BNB, BOB, ALICE, 5 * 10**18, index=0),
        )
        result = run(db, "bnb_chain", ALICE)

        assert result.data["total_in_usd"] == "5"
        assert result.data["flows"][0]["decimals"] == 18


def test_two_stablecoins_sum_into_one_dollar_total():
    """USDC (6 dp) and DAI (18 dp) received, summed into one figure -- the thing
    raw base units can never be."""
    with Database() as db:
        seed(
            db,
            "ethereum",
            transfer("ethereum", USDC_ETH, BOB, ALICE, 25_000_000, index=0),        # $25
            transfer("ethereum", DAI_ETH, BOB, ALICE, 75 * 10**18, index=1),        # $75
        )
        result = run(db, "ethereum", ALICE)

        assert result.data["stablecoins_with_activity"] == 2
        assert result.data["total_in_usd"] == "100"
        # Sorted by dollar throughput: DAI ($75) leads USDC ($25).
        assert [f["symbol"] for f in result.data["flows"]] == ["DAI", "USDC"]


# ==============================================================================
# EXCLUSIONS AND BOUNDS
# ==============================================================================

def test_a_non_stablecoin_token_is_not_counted():
    with Database() as db:
        seed(
            db,
            "ethereum",
            transfer("ethereum", USDC_ETH, BOB, ALICE, 10_000_000, index=0),
            transfer("ethereum", NOT_A_STABLE, BOB, ALICE, 999, index=1),
        )
        result = run(db, "ethereum", ALICE)

        assert result.data["stablecoins_with_activity"] == 1
        assert result.data["flows"][0]["symbol"] == "USDC"


def test_the_report_carries_the_par_caveat():
    with Database() as db:
        seed(
            db,
            "ethereum",
            transfer("ethereum", USDC_ETH, BOB, ALICE, 1_000_000, index=0),
        )
        result = run(db, "ethereum", ALICE)
        joined = " ".join(result.data["bounds"]).lower()
        assert "par" in joined
        assert "de-pegged" in joined


def test_a_chain_with_no_listed_stablecoins_is_undetermined():
    with Database() as db:
        # Seed a block so coverage is not empty, then ask on a chain with no
        # curated stablecoins.
        seed(db, "gnosis", number=100)
        result = run(db, "gnosis", ALICE)
        assert not result.determined
        assert "no known stablecoin" in result.reason


def test_no_stablecoin_activity_reads_as_zero_not_undetermined():
    with Database() as db:
        seed(
            db,
            "ethereum",
            transfer("ethereum", NOT_A_STABLE, BOB, ALICE, 999, index=0),
        )
        result = run(db, "ethereum", ALICE)
        # Determined: the window was readable, it just held no stablecoin flow.
        assert result.determined
        assert result.data["stablecoins_with_activity"] == 0
        assert "no stablecoin activity" in result.reason
