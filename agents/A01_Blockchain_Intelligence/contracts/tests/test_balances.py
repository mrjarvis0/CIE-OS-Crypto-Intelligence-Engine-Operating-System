"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for contracts.balances — pure encoding and parsing for native and
ERC-20 balance reads.

The central risk is conflating "could not determine" with "balance is zero".
A failed read that returns zero tells a whale detector that an account is
empty when A01 simply could not ask.  These tests verify that unparseable
responses stay None.
"""

from __future__ import annotations

import pytest

from contracts.balances import (
    BALANCE_OF_SELECTOR,
    encode_balance_of_call,
    parse_balance_of_response,
    parse_balance_response,
)

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


# ==============================================================================
# SELECTOR
# ==============================================================================

def test_balance_of_selector_is_four_bytes():
    assert BALANCE_OF_SELECTOR.startswith("0x")
    assert len(BALANCE_OF_SELECTOR) == 10  # "0x" + 8 hex chars = 4 bytes


# ==============================================================================
# NATIVE BALANCE PARSING
# ==============================================================================

def test_parse_hex_balance():
    assert parse_balance_response("0x64") == 100


def test_parse_large_hex_balance():
    assert parse_balance_response("0xde0b6b3a7640000") == 10**18


def test_parse_zero_balance():
    assert parse_balance_response("0x0") == 0


def test_parse_int_balance():
    assert parse_balance_response(1000) == 1000


def test_parse_decimal_string():
    assert parse_balance_response("1000") == 1000


def test_parse_none_for_bad_input():
    assert parse_balance_response(None) is None
    assert parse_balance_response(True) is None
    assert parse_balance_response([]) is None
    assert parse_balance_response({}) is None
    assert parse_balance_response("") is None
    assert parse_balance_response("0x") is None
    assert parse_balance_response("not-hex") is None


def test_parse_none_for_negative_int():
    assert parse_balance_response(-1) is None


# ==============================================================================
# BALANCE_OF ENCODING
# ==============================================================================

def test_encode_balance_of_call_structure():
    call_obj, block_tag = encode_balance_of_call(USDC, ADDRESS)

    assert call_obj["to"] == USDC
    assert call_obj["data"].startswith(BALANCE_OF_SELECTOR)
    assert block_tag == "latest"


def test_encode_balance_of_data_length():
    """Selector (4 bytes = 8 hex chars) + padded address (32 bytes = 64 hex chars)."""
    call_obj, _ = encode_balance_of_call(USDC, ADDRESS)
    data = call_obj["data"]

    assert data.startswith("0x")
    hex_body = data[2:]
    assert len(hex_body) == 8 + 64  # selector + one ABI word


def test_encode_balance_of_address_is_right_padded():
    """The address must be the *last* 40 hex characters of the word, not the first."""
    call_obj, _ = encode_balance_of_call(USDC, ADDRESS)
    data = call_obj["data"]
    word = data[10:]  # skip "0x" + 8-char selector
    assert word.endswith(ADDRESS[2:].lower())
    assert word.startswith("0" * 24)  # 12 bytes of zero padding


def test_encode_balance_of_custom_block_tag():
    _, block_tag = encode_balance_of_call(USDC, ADDRESS, block_tag="0x100")
    assert block_tag == "0x100"


def test_encode_balance_of_rejects_short_address():
    with pytest.raises(ValueError, match="20 bytes"):
        encode_balance_of_call(USDC, "0x1234")


def test_encode_balance_of_case_insensitive():
    call_lower, _ = encode_balance_of_call(USDC, ADDRESS.lower())
    call_upper, _ = encode_balance_of_call(USDC, ADDRESS.upper().replace("0X", "0x"))
    assert call_lower["data"] == call_upper["data"]


# ==============================================================================
# BALANCE_OF RESPONSE PARSING
# ==============================================================================

def test_parse_balance_of_18_decimal_amount():
    response = "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000"
    assert parse_balance_of_response(response) == 10**18


def test_parse_balance_of_zero():
    response = "0x0000000000000000000000000000000000000000000000000000000000000000"
    assert parse_balance_of_response(response) == 0


def test_parse_balance_of_minimal_encoding():
    assert parse_balance_of_response("0x64") == 100


def test_parse_balance_of_none_for_non_string():
    assert parse_balance_of_response(None) is None
    assert parse_balance_of_response(100) is None
    assert parse_balance_of_response([]) is None


def test_parse_balance_of_none_for_empty():
    assert parse_balance_of_response("") is None
    assert parse_balance_of_response("0x") is None


def test_parse_balance_of_none_for_too_long():
    assert parse_balance_of_response("0x" + "0" * 66) is None


def test_parse_balance_of_none_for_invalid_hex():
    assert parse_balance_of_response("0xnothex") is None
