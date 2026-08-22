"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the curated stablecoin table.

Two properties earn this file. The first is that the chain keys are the
registry's own slugs, because a table keyed on ``bnb`` or ``bsc`` while lookups
arrive as ``bnb_chain`` is a table that silently answers nothing. The second is
that BNB Chain's USDC and USDT are eighteen decimals, not six: normalising them
at six overstates every transfer by a trillion, the exact error resolving
decimals is meant to prevent.
"""

from __future__ import annotations

from decimal import Decimal

from config.rpc.chains import ChainName
from contracts.decimals import WELL_KNOWN
from knowledge.stablecoins import (
    STABLECOINS,
    Stablecoin,
    chains,
    is_stablecoin,
    lookup,
    normalize,
    symbols,
)

USDC_ETH = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDC_BNB = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
USDT_BNB = "0x55d398326f99059ff775485246999027b3197955"


# ==============================================================================
# CHAIN KEYS
# ==============================================================================

def test_every_chain_key_is_a_registry_slug():
    """A key that is not a real chain name is a row no lookup can ever hit."""
    valid = {c.value for c in ChainName}
    for chain, _address in STABLECOINS:
        assert chain in valid, f"{chain!r} is not a ChainName slug"


def test_bnb_is_keyed_by_its_registry_slug_not_bnb_or_bsc():
    assert lookup("bnb_chain", USDC_BNB) is not None
    # The two keys the earlier tables used, both dead against the registry.
    assert lookup("bnb", USDC_BNB) is None
    assert lookup("bsc", USDC_BNB) is None


# ==============================================================================
# DECIMALS
# ==============================================================================

def test_bnb_chain_usdc_and_usdt_are_eighteen_decimals():
    assert lookup("bnb_chain", USDC_BNB).decimals == 18
    assert lookup("bnb_chain", USDT_BNB).decimals == 18


def test_ethereum_usdc_is_six_decimals():
    assert lookup("ethereum", USDC_ETH) == Stablecoin("USDC", 6)


def test_decimals_agree_with_the_well_known_resolver_where_both_list_it():
    """The curated table and the decimals resolver must not disagree on a coin
    they both know, or a normalised figure depends on which one answered."""
    for (chain, address), coin in STABLECOINS.items():
        known = WELL_KNOWN.get((chain, address))
        if known is not None:
            assert coin.decimals == known, f"{chain}:{address} disagrees"


def test_well_known_resolver_keys_bnb_by_its_registry_slug():
    """Regression guard: the decimals resolver keyed BNB Chain as `bsc`, so a
    `bnb_chain` lookup fell through to an eth_call and BNB's 18-decimal USDC/USDT
    were never answered offline. Both tables must now spell it the same way."""
    assert WELL_KNOWN.get(("bnb_chain", USDC_BNB)) == 18
    assert WELL_KNOWN.get(("bsc", USDC_BNB)) is None


# ==============================================================================
# LOOKUP HELPERS
# ==============================================================================

def test_lookup_is_case_insensitive():
    assert lookup("ethereum", USDC_ETH.upper()) is not None


def test_is_stablecoin_matches_lookup():
    assert is_stablecoin("ethereum", USDC_ETH) is True
    assert is_stablecoin("ethereum", "0x" + "de" * 20) is False


def test_symbols_returns_address_to_symbol_for_one_chain():
    eth = symbols("ethereum")
    assert eth[USDC_ETH] == "USDC"
    # Scoped to the chain asked for: a BNB address is not in the ethereum map.
    assert USDC_BNB not in eth


def test_symbols_is_empty_for_an_unlisted_chain():
    assert symbols("bitcoin") == {}


def test_chains_covers_the_expected_networks():
    covered = chains()
    assert {"ethereum", "bnb_chain", "polygon", "arbitrum", "optimism"} <= covered


# ==============================================================================
# NORMALIZATION
# ==============================================================================

def test_normalize_turns_raw_units_into_a_face_quantity():
    # 140261088 raw USDC units at 6 decimals is $140.261088.
    assert normalize(140_261_088, 6) == Decimal("140.261088")


def test_normalize_keeps_precision_a_float_would_lose():
    """A whale-scale stablecoin transfer exceeds float's exact range; the point
    of resolving decimals is to not lose the low-order digits doing so."""
    raw = 123_456_789_012_345_678_901_234  # ~1.2e23 base units
    assert normalize(raw, 6) == Decimal("123456789012345678.901234")


def test_two_stablecoins_normalise_to_a_summable_scale():
    """The whole point: 1 USDC (6 dp) and 1 DAI (18 dp) are the same dollar
    once decimals are resolved, though their raw units differ by 1e12."""
    one_usdc = normalize(1_000_000, 6)
    one_dai = normalize(10**18, 18)
    assert one_usdc == one_dai == Decimal(1)
