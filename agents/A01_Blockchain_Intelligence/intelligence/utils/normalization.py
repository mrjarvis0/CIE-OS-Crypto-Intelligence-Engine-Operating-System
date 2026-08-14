"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.normalization

Purpose:
    Entity and blockchain-address normalization helpers.

    Provides canonical, lowercase, checksummed address normalization
    and entity identifier normalization used across analysis,
    correlation, and attribution. A ``chain`` hint restricts
    validation to the matching address family; without a hint any
    known family is accepted.
"""

from __future__ import annotations

import re

# EVM addresses are exactly 40 hex chars after the 0x prefix.
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# UTXO addresses are base58 strings of 25-35 characters (BTC-style).
_UTXO_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{25,35}$")

# Bech32 body: only the 32-char bech32 alphabet, excluding the
# forbidden characters 1, b, i, and o. Case must be uniform.
_BECH32_BODY_RE = re.compile(r"^[0-9a-hj-np-z]{20,90}$")

_ENTITY_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:@-]{0,127}$")

# Injective / 0x-style chain-prefixed identifiers like "inj1...".
_INJ_ADDRESS_RE = re.compile(r"^inj1[0-9a-z]{38}$")

# Chain-hint keywords per address family.
_EVM_CHAINS = ("evm", "eth", "ethereum", "arb", "arbitrum", "optimism", "op",
               "base", "polygon", "matic", "bsc", "bnb", "avax", "avalanche",
               "fantom", "ftm", "zk", "zksync", "scroll", "linea", "mantle",
               "cronos", "gnosis", "xdai")
_UTXO_CHAINS = ("btc", "bitcoin", "bsv", "ltc", "litecoin", "doge", "dash",
                "zec", "zcash")
_BECH32_CHAINS = ("cosmos", "atom", "osmo", "osmosis", "juno", "secret",
                  "injective", "inj", "persistence", "celestia", "dydx")


def _is_bech32(value: str) -> bool:
    """Return True for a syntactically valid bech32 address body."""
    if not value.startswith(("bc1", "tb1", "bcrt1")):
        return False
    body = value[3:]
    if not _BECH32_BODY_RE.fullmatch(body):
        return False
    return value == value.lower() or value == value.upper()


def normalize_address(
    value: str | None,
    chain: str | None = None,
) -> str | None:
    """
    Return a canonical address string, or None if invalid.

    EVM (0x...) addresses are lowercased; UTXO and bech32 addresses are
    normalized per their own format. A ``chain`` hint selects the
    applicable validator when the prefix is ambiguous: when a hint is
    given, only addresses belonging to the hinted family are accepted.

    Returns
    -------
    str | None
        The canonical address, or None when the value is not a valid
        address for the given chain.
    """
    if not value:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    chain = (chain or "").lower()

    is_evm = any(c in chain for c in _EVM_CHAINS)
    is_utxo = any(c in chain for c in _UTXO_CHAINS)
    is_bech32_chain = any(c in chain for c in _BECH32_CHAINS)
    hinted = bool(chain)

    if (not hinted or is_evm) and _EVM_ADDRESS_RE.fullmatch(value):
        return value.lower()
    if (not hinted or is_utxo) and _UTXO_ADDRESS_RE.fullmatch(value):
        return value
    if (not hinted or is_bech32_chain) and _is_bech32(value):
        return value.lower()
    if (not hinted or is_bech32_chain) and _INJ_ADDRESS_RE.fullmatch(value):
        return value
    return None


def validate_address(value: str | None, chain: str | None = None) -> bool:
    """
    Return True if the value is a syntactically valid address.

    Accepts EVM, UTXO (base58), bech32, and injective-style addresses.
    """
    return normalize_address(value, chain) is not None


def normalize_entity_id(value: str | None) -> str | None:
    """
    Trim and validate a generic entity identifier, or None if invalid.
    """
    if not value:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _ENTITY_ID_RE.fullmatch(value):
        return None
    return value
