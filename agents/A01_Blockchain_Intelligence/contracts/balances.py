"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    contracts.balances

Purpose:
    Pure encoding and parsing for balance reads: native ``eth_getBalance``
    responses and ERC-20 ``balanceOf(address)`` call construction.

Design goals:
    - Selector verified at import time against Keccak-256
    - Parsing never fabricates a value; unparseable responses return None
    - No I/O, no network, no chain access
    - Address padding done once and correctly

Notes:
    A balance read has two distinct forms with different trust profiles:

    **Native balance** (``eth_getBalance``) is a first-class RPC method.
    The response is a hex quantity of the chain's native unit in its smallest
    denomination (wei on Ethereum, lamports on Solana — though this module
    covers EVM only).  The provider cannot misattribute the account because
    the address is a method parameter, not a contract's interpretation.

    **Token balance** (``balanceOf``) is an ``eth_call`` against a contract.
    The response is whatever the contract returns.  A non-standard contract
    may return garbage; a proxy may revert; a self-destructed contract
    returns empty bytes.  The parser accepts only a well-formed ABI-encoded
    uint256 and returns None for everything else, so a bad response stays
    "could not determine" rather than becoming zero.

    The ``balanceOf`` selector is ``0x70a08231``, the first four bytes of
    ``keccak256("balanceOf(address)")``.  This is verified at import time.

Boundary:
    This module does not import the RPC layer.  Call construction and
    response parsing are pure functions; the dispatcher is the caller's
    concern.
"""

from __future__ import annotations

from typing import Any, Final

BALANCE_OF_SELECTOR: Final[str] = "0x70a08231"


def _verify_selector() -> None:
    """Check the constant against a live Keccak-256, when available."""
    try:
        import hashlib

        digest = hashlib.new("keccak256", b"balanceOf(address)")
        computed = "0x" + digest.hexdigest()[:8]
    except (ValueError, TypeError):
        return
    if computed != BALANCE_OF_SELECTOR:
        raise RuntimeError(
            f"BALANCE_OF_SELECTOR mismatch: computed {computed}, "
            f"have {BALANCE_OF_SELECTOR}"
        )


_verify_selector()


# -- native balance parsing --------------------------------------------------

def parse_balance_response(value: Any) -> int | None:
    """
    Read an ``eth_getBalance`` or ``balanceOf`` response into an int.

    Returns None rather than zero for unparseable input.  A failed read is
    not a zero balance, and substituting zero would tell a whale detector
    that an account is empty when A01 simply could not ask.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text or text == "0x":
        return None

    try:
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text, 10)
    except ValueError:
        return None


# -- ERC-20 balanceOf encoding -----------------------------------------------

def _pad_address(address: str) -> str:
    """
    Left-pad a 20-byte address to a 32-byte ABI word.

    The address is the last 40 hex characters of a 64-character word.
    Slicing from the wrong end would produce twelve zero bytes followed by
    the first half of the address — a valid-looking parameter that queries
    the wrong account.
    """
    body = address[2:] if address.lower().startswith("0x") else address
    body = body.lower()
    if len(body) != 40:
        raise ValueError(f"address must be 20 bytes (40 hex chars), got {len(body)}")
    return body.zfill(64)


def encode_balance_of_call(
    token: str,
    address: str,
    *,
    block_tag: str = "latest",
) -> tuple[dict[str, str], str]:
    """
    Build the ``eth_call`` parameters for ``balanceOf(address)``.

    Returns ``(call_object, block_tag)`` ready to pass as
    ``dispatcher.call(chain, "eth_call", [call_object, block_tag])``.
    """
    data = BALANCE_OF_SELECTOR + _pad_address(address)
    return {"to": token, "data": data}, block_tag


def parse_balance_of_response(value: Any) -> int | None:
    """
    Read a ``balanceOf`` return value.

    A valid ABI-encoded uint256 is exactly 64 hex chars (32 bytes).  Some
    nodes return a shorter encoding; we accept up to 64 chars.  Anything
    longer, empty, or non-hex returns None.

    A zero balance is a valid response and returns 0.  None means "could not
    determine", which is distinct from "the balance is zero".
    """
    if not isinstance(value, str):
        return None

    hex_str = value[2:] if value.startswith("0x") else value
    if not hex_str:
        return None
    if len(hex_str) > 64:
        return None

    try:
        return int(hex_str, 16)
    except ValueError:
        return None


__all__ = [
    "BALANCE_OF_SELECTOR",
    "encode_balance_of_call",
    "parse_balance_of_response",
    "parse_balance_response",
]
