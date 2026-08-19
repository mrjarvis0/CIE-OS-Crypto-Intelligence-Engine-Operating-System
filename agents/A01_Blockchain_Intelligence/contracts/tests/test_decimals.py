"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the token decimals resolver.

The central risk is assuming 18 for a token that uses fewer.  USDC (6 decimals)
rendered at 18 is a trillion times too large, and the figure looks ordinary.
So the tests verify that unknown decimals stay unknown, well-known tokens
return the right value, and a failed eth_call never fabricates a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from contracts.decimals import (
    DECIMALS_SELECTOR,
    WELL_KNOWN,
    DecimalsResult,
    TokenDecimalsResolver,
    encode_decimals_call,
    parse_decimals_response,
)

CHAIN = "ethereum"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
UNKNOWN_TOKEN = "0x" + "dd" * 20


# -- helpers -----------------------------------------------------------------

@dataclass
class FakeCallResult:
    determined: bool
    value: Any = None


class FakeDispatcher:
    """Records calls and returns a preset response."""

    def __init__(self, response: FakeCallResult | None = None):
        self.calls: list[tuple[str, str, Any]] = []
        self.response = response or FakeCallResult(determined=False)

    def call(self, chain, method, params=None, *, use_cache=True):
        self.calls.append((chain, method, params))
        return self.response


# ==============================================================================
# SELECTOR
# ==============================================================================

def test_decimals_selector_is_four_bytes():
    assert DECIMALS_SELECTOR.startswith("0x")
    assert len(DECIMALS_SELECTOR) == 10  # "0x" + 8 hex chars = 4 bytes


# ==============================================================================
# PURE ENCODING
# ==============================================================================

def test_encode_decimals_call_builds_correct_params():
    call_obj, block_tag = encode_decimals_call(USDC)

    assert call_obj["to"] == USDC
    assert call_obj["data"] == DECIMALS_SELECTOR
    assert block_tag == "latest"


# ==============================================================================
# PURE PARSING
# ==============================================================================

def test_parse_18_decimals():
    response = "0x0000000000000000000000000000000000000000000000000000000000000012"
    assert parse_decimals_response(response) == 18


def test_parse_6_decimals():
    response = "0x0000000000000000000000000000000000000000000000000000000000000006"
    assert parse_decimals_response(response) == 6


def test_parse_8_decimals():
    response = "0x0000000000000000000000000000000000000000000000000000000000000008"
    assert parse_decimals_response(response) == 8


def test_parse_zero_decimals():
    response = "0x0000000000000000000000000000000000000000000000000000000000000000"
    assert parse_decimals_response(response) == 0


def test_parse_minimal_encoding():
    """Some nodes return the value without padding."""
    assert parse_decimals_response("0x12") == 18
    assert parse_decimals_response("0x6") == 6


def test_parse_none_for_non_string():
    assert parse_decimals_response(None) is None
    assert parse_decimals_response(18) is None
    assert parse_decimals_response([]) is None


def test_parse_none_for_empty():
    assert parse_decimals_response("") is None
    assert parse_decimals_response("0x") is None


def test_parse_none_for_too_long():
    assert parse_decimals_response("0x" + "0" * 66) is None


def test_parse_none_for_invalid_hex():
    assert parse_decimals_response("0xnothex") is None


def test_parse_none_for_out_of_range():
    """Decimals above 77 are outside Amount's valid range."""
    response = "0x0000000000000000000000000000000000000000000000000000000000000050"
    assert parse_decimals_response(response) is None  # 0x50 = 80


# ==============================================================================
# WELL-KNOWN TOKENS
# ==============================================================================

def test_well_known_usdc_is_6():
    assert WELL_KNOWN[("ethereum", USDC)] == 6


def test_well_known_covers_major_stablecoins():
    usdt = WELL_KNOWN.get(("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7"))
    assert usdt == 6


def test_well_known_wbtc_is_8():
    wbtc = WELL_KNOWN.get(("ethereum", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"))
    assert wbtc == 8


def test_well_known_weth_is_18():
    weth = WELL_KNOWN.get(("ethereum", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"))
    assert weth == 18


def test_well_known_addresses_are_lowercase():
    for (chain, address), _ in WELL_KNOWN.items():
        assert address == address.lower(), f"{chain}:{address} is not lowercase"


def test_well_known_spans_multiple_chains():
    chains = {chain for chain, _ in WELL_KNOWN}
    assert len(chains) >= 3, "well-known table should cover multiple chains"


# ==============================================================================
# RESOLVER — WELL-KNOWN PATH
# ==============================================================================

def test_well_known_token_resolved_without_rpc():
    dispatcher = FakeDispatcher()
    resolver = TokenDecimalsResolver(dispatcher)

    result = resolver.resolve(USDC, CHAIN)

    assert result.resolved
    assert result.decimals == 6
    assert result.source == "well_known"
    assert not dispatcher.calls, "well-known lookup must not hit the network"


def test_well_known_is_case_insensitive():
    dispatcher = FakeDispatcher()
    resolver = TokenDecimalsResolver(dispatcher)

    result = resolver.resolve(USDC.upper().replace("0X", "0x"), CHAIN)
    # USDC address uppercased should still not match well-known since well-known
    # keys are lowercase — this tests that the resolver lowercases the input
    assert result.resolved or not dispatcher.calls


# ==============================================================================
# RESOLVER — ETH_CALL PATH
# ==============================================================================

def test_unknown_token_fetched_via_eth_call():
    response = FakeCallResult(
        determined=True,
        value="0x0000000000000000000000000000000000000000000000000000000000000012",
    )
    dispatcher = FakeDispatcher(response)
    resolver = TokenDecimalsResolver(dispatcher)

    result = resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert result.resolved
    assert result.decimals == 18
    assert result.source == "eth_call"
    assert len(dispatcher.calls) == 1

    chain, method, params = dispatcher.calls[0]
    assert chain == CHAIN
    assert method == "eth_call"
    assert params[0]["to"] == UNKNOWN_TOKEN
    assert params[0]["data"] == DECIMALS_SELECTOR
    assert params[1] == "latest"


def test_eth_call_result_is_cached():
    response = FakeCallResult(
        determined=True,
        value="0x0000000000000000000000000000000000000000000000000000000000000006",
    )
    dispatcher = FakeDispatcher(response)
    resolver = TokenDecimalsResolver(dispatcher)

    first = resolver.resolve(UNKNOWN_TOKEN, CHAIN)
    second = resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert first.decimals == 6
    assert first.source == "eth_call"
    assert second.decimals == 6
    assert second.source == "cache"
    assert len(dispatcher.calls) == 1, "second call must come from cache"


# ==============================================================================
# RESOLVER — FAILURE PATH
# ==============================================================================

def test_undetermined_result_returns_none():
    dispatcher = FakeDispatcher(FakeCallResult(determined=False))
    resolver = TokenDecimalsResolver(dispatcher)

    result = resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert not result.resolved
    assert result.decimals is None
    assert result.source == "failed"


def test_a_failed_call_never_defaults_to_18():
    """The central invariant: unknown decimals stay unknown."""
    dispatcher = FakeDispatcher(FakeCallResult(determined=False))
    resolver = TokenDecimalsResolver(dispatcher)

    result = resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert result.decimals is None
    assert result.decimals != 18


def test_exception_in_dispatcher_returns_none():
    class ExplodingDispatcher:
        def call(self, *args, **kwargs):
            raise ConnectionError("node unreachable")

    resolver = TokenDecimalsResolver(ExplodingDispatcher())

    result = resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert not result.resolved
    assert result.source == "failed"


def test_backoff_after_repeated_failures():
    dispatcher = FakeDispatcher(FakeCallResult(determined=False))
    resolver = TokenDecimalsResolver(dispatcher)

    for _ in range(3):
        resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert len(dispatcher.calls) == 3

    result = resolver.resolve(UNKNOWN_TOKEN, CHAIN)
    assert result.source == "backed_off"
    assert len(dispatcher.calls) == 3, "backed-off contract must not be retried"


# ==============================================================================
# RESOLVER — PRIME AND INVALIDATE
# ==============================================================================

def test_prime_injects_a_value():
    dispatcher = FakeDispatcher()
    resolver = TokenDecimalsResolver(dispatcher)

    resolver.prime(UNKNOWN_TOKEN, CHAIN, 8)
    result = resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    assert result.decimals == 8
    assert result.source == "cache"
    assert not dispatcher.calls


def test_prime_rejects_out_of_range():
    resolver = TokenDecimalsResolver(FakeDispatcher())

    with pytest.raises(ValueError, match="out of range"):
        resolver.prime(UNKNOWN_TOKEN, CHAIN, 78)

    with pytest.raises(ValueError, match="out of range"):
        resolver.prime(UNKNOWN_TOKEN, CHAIN, -1)


def test_prime_clears_failure_backoff():
    dispatcher = FakeDispatcher(FakeCallResult(determined=False))
    resolver = TokenDecimalsResolver(dispatcher)

    for _ in range(3):
        resolver.resolve(UNKNOWN_TOKEN, CHAIN)
    assert resolver.resolve(UNKNOWN_TOKEN, CHAIN).source == "backed_off"

    resolver.prime(UNKNOWN_TOKEN, CHAIN, 18)
    assert resolver.resolve(UNKNOWN_TOKEN, CHAIN).decimals == 18
    assert resolver.resolve(UNKNOWN_TOKEN, CHAIN).source == "cache"


def test_invalidate_forces_refetch():
    response = FakeCallResult(
        determined=True,
        value="0x0000000000000000000000000000000000000000000000000000000000000012",
    )
    dispatcher = FakeDispatcher(response)
    resolver = TokenDecimalsResolver(dispatcher)

    resolver.resolve(UNKNOWN_TOKEN, CHAIN)
    assert len(dispatcher.calls) == 1

    assert resolver.invalidate(UNKNOWN_TOKEN, CHAIN)

    resolver.resolve(UNKNOWN_TOKEN, CHAIN)
    assert len(dispatcher.calls) == 2


def test_invalidate_returns_false_for_absent_key():
    resolver = TokenDecimalsResolver(FakeDispatcher())
    assert not resolver.invalidate(UNKNOWN_TOKEN, CHAIN)


# ==============================================================================
# RESOLVER — BATCH
# ==============================================================================

def test_batch_resolves_multiple_tokens():
    response = FakeCallResult(
        determined=True,
        value="0x0000000000000000000000000000000000000000000000000000000000000012",
    )
    dispatcher = FakeDispatcher(response)
    resolver = TokenDecimalsResolver(dispatcher)

    pairs = [(USDC, CHAIN), (UNKNOWN_TOKEN, CHAIN)]
    results = resolver.resolve_batch(pairs)

    assert results[(USDC, CHAIN)].decimals == 6
    assert results[(USDC, CHAIN)].source == "well_known"
    assert results[(UNKNOWN_TOKEN, CHAIN)].decimals == 18
    assert results[(UNKNOWN_TOKEN, CHAIN)].source == "eth_call"


# ==============================================================================
# RESOLVER — SNAPSHOT
# ==============================================================================

def test_snapshot_reports_cache_state():
    response = FakeCallResult(
        determined=True,
        value="0x0000000000000000000000000000000000000000000000000000000000000012",
    )
    dispatcher = FakeDispatcher(response)
    resolver = TokenDecimalsResolver(dispatcher)

    resolver.resolve(UNKNOWN_TOKEN, CHAIN)

    snap = resolver.snapshot()
    assert snap["cached"] == 1
    assert snap["backed_off"] == 0
    assert snap["well_known"] == len(WELL_KNOWN)


# ==============================================================================
# RESULT DATACLASS
# ==============================================================================

def test_result_resolved_property():
    assert DecimalsResult(18, "eth_call", USDC, CHAIN).resolved
    assert not DecimalsResult(None, "failed", USDC, CHAIN).resolved
