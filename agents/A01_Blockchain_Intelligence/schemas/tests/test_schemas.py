"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for schemas -- exact quantities, canonical identity, and the reorg flag.

The cases that matter here all describe corruption that produces no error. A
64-bit column truncating a large transfer, a case-sensitive key splitting one
account into three, an unpadded value column ordering 9 after 10: each returns
a plausible answer and each makes a detector wrong. So the tests assert the
properties that prevent them, not just that the constructors work.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from schemas import (
    MAX_UINT256,
    ZERO_ADDRESS,
    Address,
    AddressError,
    Amount,
    AmountError,
    CanonicalBlock,
    CanonicalTransaction,
    from_unix,
)
from schemas.amount import AMOUNT_WIDTH

#: The largest value a signed 64-bit column can hold. Just under nine ether
#: expressed in wei -- the ceiling this package exists to get past.
SQLITE_INTEGER_MAX = 2**63 - 1


# ==============================================================================
# AMOUNT — precision
# ==============================================================================

def test_value_above_the_64_bit_ceiling_survives_intact():
    """
    1,000 ETH in wei is ~54x a signed 64-bit maximum. Stored in an INTEGER
    column it truncates, the write succeeds, and a whale detector reads the
    largest transfers on the chain as small ones.
    """
    thousand_eth = 1000 * 10**18
    assert thousand_eth > SQLITE_INTEGER_MAX

    amount = Amount(thousand_eth)
    assert Amount.from_stored(amount.stored()).raw == thousand_eth


def test_max_uint256_round_trips():
    amount = Amount(MAX_UINT256)
    assert Amount.from_stored(amount.stored()).raw == MAX_UINT256
    assert len(amount.stored()) == AMOUNT_WIDTH


def test_amount_above_uint256_is_refused():
    """No chain can state this, so whatever produced it is not a chain."""
    with pytest.raises(AmountError):
        Amount(MAX_UINT256 + 1)


def test_units_are_exact_not_floating():
    """
    A float64 has 53 bits of mantissa and cannot hold a wei value exactly. A
    balance that is nearly right is the hardest error to notice.
    """
    amount = Amount(123456789012345678901)
    assert isinstance(amount.units(), Decimal)
    assert amount.units() == Decimal("123.456789012345678901")


def test_negative_quantities_are_refused():
    with pytest.raises(AmountError):
        Amount(-1)


def test_float_input_is_refused():
    with pytest.raises(AmountError):
        Amount(1.5)  # type: ignore[arg-type]


def test_boolean_is_not_a_quantity():
    """bool is an int subclass in Python; accepting True as 1 wei is nonsense."""
    with pytest.raises(AmountError):
        Amount(True)  # type: ignore[arg-type]


# ==============================================================================
# AMOUNT — ordering
# ==============================================================================

def test_padding_makes_text_ordering_match_numeric_ordering():
    """
    The reason values are zero-padded. Unpadded, "10" sorts before "9", so
    ORDER BY value DESC returns small transfers and calls them the largest.
    """
    nine = Amount(9)
    ten = Amount(10)

    assert str(9) > str(10), "unpadded text ordering is wrong, which is the point"
    assert nine.stored() < ten.stored()


def test_stored_ordering_holds_across_magnitudes():
    values = [0, 1, 999, 10**18, 10**24, MAX_UINT256]
    stored = [Amount(v).stored() for v in values]
    assert stored == sorted(stored), "lexicographic order must match numeric order"


def test_amounts_compare_directly():
    assert Amount(5) < Amount(10)
    assert Amount(10) == Amount(10)


# ==============================================================================
# AMOUNT — denomination safety
# ==============================================================================

def test_mixing_denominations_is_refused():
    """
    Adding wei to satoshi produces a number with no meaning, and the result
    would look entirely ordinary in a report.
    """
    wei = Amount(10**18, decimals=18)
    satoshi = Amount(10**8, decimals=8)

    with pytest.raises(AmountError):
        _ = wei + satoshi


def test_addition_keeps_the_scale():
    total = Amount(10**18) + Amount(10**18)
    assert total.raw == 2 * 10**18
    assert total.decimals == 18


def test_subtraction_below_zero_is_refused():
    with pytest.raises(AmountError):
        _ = Amount(1) - Amount(2)


def test_hex_parse_refuses_rather_than_defaulting_to_zero():
    """A failed parse recorded as zero is a transfer of nothing — a fabricated fact."""
    for bad in ["", "0xzz", "junk", None, {}, True]:
        with pytest.raises(AmountError):
            Amount.from_hex(bad)


def test_hex_parse_reads_both_bases():
    assert Amount.from_hex("0x0de0b6b3a7640000").raw == 10**18
    assert Amount.from_hex("1000000000000000000").raw == 10**18


# ==============================================================================
# ADDRESS
# ==============================================================================

def test_evm_case_is_folded_so_one_account_is_one_key():
    """
    EIP-55 encodes a checksum in the case of the hex, so the same account is
    legitimately written three ways. A case-sensitive key splits one account
    into three across every join and aggregation, and nothing raises.
    """
    body = "1234567890AbCdEf1234567890aBcDeF12345678"
    variants = [f"0x{body}", f"0x{body.lower()}", f"0x{body.upper()}"]

    keys = {Address.parse(v, "ethereum").key for v in variants}
    assert len(keys) == 1


def test_original_form_is_preserved_for_display():
    checksummed = "0xAbCdEf1234567890AbCdEf1234567890aBcDeF12"
    address = Address.parse(checksummed, "ethereum")

    assert address.value == checksummed.lower()
    assert address.original == checksummed


def test_the_same_bytes_are_different_accounts_on_different_chains():
    """Contracts genuinely collide across EVM chains; keying on address merges them."""
    literal = "0x" + "1" * 40
    assert Address.parse(literal, "ethereum").key != Address.parse(literal, "polygon").key


def test_truncated_evm_address_is_refused():
    """
    An accepted truncated address becomes a real key, and every query for the
    true account silently misses those rows.
    """
    with pytest.raises(AddressError):
        Address.parse("0x1234", "ethereum")


def test_non_evm_addresses_keep_their_case():
    """Base58 is case-sensitive; lowercasing a Solana address gives a different account."""
    solana = "So11111111111111111111111111111111111111112"
    assert Address.parse(solana, "solana").value == solana


def test_absent_recipient_is_none_not_the_zero_address():
    """
    Contract creations have no `to`. The zero address is a real counterparty for
    mints and burns, so conflating them makes every deployment look like a burn.
    """
    assert Address.parse_optional(None, "ethereum") is None
    assert Address.parse(ZERO_ADDRESS, "ethereum").is_zero


def test_address_requires_a_chain():
    with pytest.raises(AddressError):
        Address(value="0x" + "1" * 40, chain="  ")


# ==============================================================================
# CANONICAL BLOCK
# ==============================================================================

def block_at(number: int, tag: str = "a") -> CanonicalBlock:
    return CanonicalBlock(
        chain="ethereum",
        number=number,
        block_hash=f"0x{tag}{number:06d}",
        parent_hash=f"0x{tag}{number - 1:06d}",
        timestamp=from_unix(1_700_000_000 + number * 12),
        transaction_count=0,
        source_record_id="rec-1",
    )


def test_block_key_is_the_hash_because_a_reorg_reuses_heights():
    original = block_at(100, "a")
    replacement = block_at(100, "b")

    assert original.number == replacement.number
    assert original.key != replacement.key


def test_withdrawal_produces_a_new_record_and_keeps_the_original():
    """An observation should not change after it is made."""
    block = block_at(100)
    withdrawn = block.withdrawn()

    assert block.canonical
    assert not withdrawn.canonical
    assert withdrawn.withdrawn_at is not None
    assert withdrawn.block_hash == block.block_hash


def test_canonical_and_withdrawn_at_cannot_disagree():
    with pytest.raises(ValueError):
        CanonicalBlock(
            chain="ethereum",
            number=1,
            block_hash="0xa",
            parent_hash="0xb",
            timestamp=datetime.now(UTC),
            transaction_count=0,
            canonical=True,
            withdrawn_at=datetime.now(UTC),
        )

    with pytest.raises(ValueError):
        CanonicalBlock(
            chain="ethereum",
            number=1,
            block_hash="0xa",
            parent_hash="0xb",
            timestamp=datetime.now(UTC),
            transaction_count=0,
            canonical=False,
        )


def test_missing_parent_hash_is_refused_above_genesis():
    with pytest.raises(ValueError):
        CanonicalBlock(
            chain="ethereum",
            number=100,
            block_hash="0xa",
            parent_hash="",
            timestamp=datetime.now(UTC),
            transaction_count=0,
        )


def test_expanded_flag_separates_an_empty_block_from_an_unexpanded_one():
    """Reading the second as the first reports a busy block as idle."""
    empty = block_at(1)
    assert empty.transaction_count == 0
    assert not empty.transactions_expanded

    counted_only = CanonicalBlock(
        chain="ethereum",
        number=2,
        block_hash="0xa2",
        parent_hash="0xa1",
        timestamp=datetime.now(UTC),
        transaction_count=200,
    )
    assert counted_only.transaction_count == 200
    assert not counted_only.transactions_expanded


def test_gas_utilisation_is_none_when_either_figure_is_missing():
    block = block_at(1)
    assert block.gas_utilisation is None


# ==============================================================================
# CANONICAL TRANSACTION
# ==============================================================================

def test_contract_creation_is_detectable():
    tx = CanonicalTransaction(
        chain="ethereum",
        tx_hash="0xdead",
        block_number=1,
        block_hash="0xa",
        index=0,
        from_address=Address.parse("0x" + "1" * 40, "ethereum"),
        to_address=None,
        value=Amount(0),
    )
    assert tx.is_contract_creation


def test_transaction_key_is_chain_scoped():
    kwargs = {
        "tx_hash": "0xdead",
        "block_number": 1,
        "block_hash": "0xa",
        "index": 0,
        "value": Amount(0),
    }
    ethereum = CanonicalTransaction(
        chain="ethereum",
        from_address=Address.parse("0x" + "1" * 40, "ethereum"),
        to_address=None,
        **kwargs,
    )
    polygon = CanonicalTransaction(
        chain="polygon",
        from_address=Address.parse("0x" + "1" * 40, "polygon"),
        to_address=None,
        **kwargs,
    )
    assert ethereum.key != polygon.key


def test_timestamp_conversion_is_utc():
    converted = from_unix(1_700_000_000)
    assert converted.tzinfo is not None
    assert converted.utcoffset() == timedelta(0)
