"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    contracts

Purpose:
    Event signatures and decoders. Turns a raw log into a typed transfer, or
    refuses it.

Why this package exists
-----------------------
Native transactions are only part of a chain, and on layer 2 they are barely
any of it. Measured on live Arbitrum and Optimism blocks, the largest *native*
transfer was `0.0000` — every real movement was a token transfer carried in an
event log. One Ethereum block held 393 ERC-20 transfers against 505 native
transactions whose largest was 6 ETH.

The one fact that shapes this package
-------------------------------------
**ERC-20 and ERC-721 `Transfer` events share a topic0.** Both hash
`Transfer(address,address,uint256)`; ERC-721 differs only in marking the third
parameter `indexed`, which changes where the value is carried, not the
signature it hashes from.

So identity comes from **shape**, verified on live data:

| Topics | Data | Event |
| --- | --- | --- |
| 3 | 32 bytes | ERC-20 — amount in `data` |
| 4 | 0 bytes | ERC-721 — `tokenId` indexed |
| anything else | — | refused, never guessed |

A decoder keyed on topic0 alone reads every NFT movement as a token transfer of
`tokenId` units — a number that is enormous, plausible, and meaningless.

Decimals
--------
Resolved by :mod:`contracts.decimals`.  The exponent lives in the contract's
``decimals()`` view function, reachable only by ``eth_call``.  The event
decoder still carries raw integers with ``decimals=0`` (scale unknown), but
consumers can resolve the scale through :class:`TokenDecimalsResolver`, which
checks a well-known table first, then an in-memory cache, then falls back to
``eth_call``.  A contract that does not implement ``decimals()`` returns
``None`` — never a default of 18, because assuming 18 renders 6-decimal USDC
a trillion times too large and the figure looks ordinary.
"""

from __future__ import annotations

from .balances import (
    BALANCE_OF_SELECTOR,
    encode_balance_of_call,
    parse_balance_of_response,
    parse_balance_response,
)
from .decimals import (
    DECIMALS_SELECTOR,
    WELL_KNOWN,
    DecimalsResult,
    TokenDecimalsResolver,
    encode_decimals_call,
    parse_decimals_response,
)
from .events import DecodeRefusal, DecodedTransfer, decode_log, decode_logs
from .signatures import (
    APPROVAL_FOR_ALL_TOPIC,
    APPROVAL_TOPIC,
    ERC1155_SINGLE_TOPIC,
    KNOWN_SHAPES,
    TRANSFER_TOPIC,
    UNSUPPORTED_TOPICS,
    EventKind,
    EventShape,
    shape_for,
    unsupported_reason,
)

__all__ = [
    "APPROVAL_FOR_ALL_TOPIC",
    "APPROVAL_TOPIC",
    "BALANCE_OF_SELECTOR",
    "DECIMALS_SELECTOR",
    "ERC1155_SINGLE_TOPIC",
    "KNOWN_SHAPES",
    "TRANSFER_TOPIC",
    "UNSUPPORTED_TOPICS",
    "WELL_KNOWN",
    "DecimalsResult",
    "DecodeRefusal",
    "DecodedTransfer",
    "EventKind",
    "EventShape",
    "TokenDecimalsResolver",
    "decode_log",
    "decode_logs",
    "encode_balance_of_call",
    "encode_decimals_call",
    "parse_balance_of_response",
    "parse_balance_response",
    "parse_decimals_response",
    "shape_for",
    "unsupported_reason",
]
