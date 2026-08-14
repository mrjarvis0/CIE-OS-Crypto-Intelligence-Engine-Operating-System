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
Not resolved here. The exponent lives in the contract's `decimals()`, reachable
only by `eth_call`, which this layer does not do. Assuming 18 renders 6-decimal
USDC a trillion times too large and the figure looks ordinary. Raw integers are
carried with the scale marked unknown, and consumers decide what they may say.
"""

from __future__ import annotations

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
    "ERC1155_SINGLE_TOPIC",
    "KNOWN_SHAPES",
    "TRANSFER_TOPIC",
    "UNSUPPORTED_TOPICS",
    "DecodeRefusal",
    "DecodedTransfer",
    "EventKind",
    "EventShape",
    "decode_log",
    "decode_logs",
    "shape_for",
    "unsupported_reason",
]
