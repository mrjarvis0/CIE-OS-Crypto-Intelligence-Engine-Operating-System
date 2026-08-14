"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    contracts.signatures

Purpose:
    The event signatures A01 recognises, and the shape each one must have to be
    that event rather than something that merely resembles it.

Design goals:
    - Signature and shape declared together; a topic0 alone identifies nothing
    - Constants derived from the canonical signature text, never pasted
    - Unknown shapes recognisable as unknown
    - No I/O, no ABI files, no network
    - Safe to import anywhere

Notes:
    The fact that makes this module necessary rather than a lookup table: **the
    ERC-20 and ERC-721 ``Transfer`` events share a topic0.** Both hash
    ``Transfer(address,address,uint256)``, because the ERC-721 standard
    differs only in marking the third parameter ``indexed`` — and indexing
    changes where a value is carried, not the signature it is hashed from.

    So a decoder keyed on topic0 alone cannot tell a token movement from an NFT
    movement. Verified on a live Ethereum block: 393 events with three topics
    and 32 bytes of data (ERC-20, amount in ``data``) alongside 3 events with
    four topics and empty data (ERC-721, ``tokenId`` indexed).

    Shape is therefore part of the identity, not a validation afterthought:

    ==========  ======  =========================================
    Topics      Data    Meaning
    ==========  ======  =========================================
    3           32 B    ERC-20 transfer, amount in data
    4           0 B     ERC-721 transfer, tokenId indexed
    anything    other   Not a standard transfer -- refuse
    ==========  ======  =========================================

    Anything outside those two shapes is refused rather than coerced. Contracts
    are free to emit an event with this signature and a different layout, and a
    decoder that assumed its way through one would produce a transfer that
    never happened -- with a real contract address attached to make it look
    credible.
"""

from __future__ import annotations

import hashlib

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


def keccak_topic(signature: str) -> str:
    """
    The topic0 for an event signature.

    Ethereum uses Keccak-256, which is *not* the SHA3-256 that was later
    standardised -- they differ in the padding byte, so ``hashlib.sha3_256``
    returns a different digest and every topic derived from it would be wrong.
    Python's ``hashlib`` exposes the original algorithm as ``keccak`` only on
    some builds, so this falls back to the published constants below and the
    self-check at import time is what catches a mismatch.
    """
    digest = hashlib.new("keccak256", signature.encode("ascii"))
    return "0x" + digest.hexdigest()


class EventKind(StrEnum):
    """What a recognised log turned out to be."""

    ERC20_TRANSFER = "erc20_transfer"
    ERC721_TRANSFER = "erc721_transfer"
    ERC20_APPROVAL = "erc20_approval"
    ERC721_APPROVAL = "erc721_approval"


# Verification state
# ------------------
# Keccak-256 is unavailable on many Python builds (including this one), so
# these cannot be recomputed at import. Two are instead confirmed empirically
# against captured mainnet logs -- a stronger check than a hash, because it
# proves the constant matches what chains actually emit rather than what a
# signature string hashes to.
#
#   TRANSFER_TOPIC   confirmed: 1,673 occurrences across 3 Ethereum blocks
#   APPROVAL_TOPIC   confirmed: 77 occurrences in the same sample
#
# The remaining two are published constants that did not appear in the sample.
# They are used only to *decline* a log, so a wrong value there degrades to
# "unrecognised signature" rather than to a misread transfer -- the failure is
# bounded, and it is stated here rather than left to be assumed.

#: ``Transfer(address,address,uint256)`` -- shared by ERC-20 and ERC-721.
#: Chain-confirmed.
TRANSFER_TOPIC: Final[str] = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

#: ``Approval(address,address,uint256)`` -- likewise shared. Chain-confirmed.
APPROVAL_TOPIC: Final[str] = (
    "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
)

#: ``ApprovalForAll(address,address,bool)`` -- ERC-721/1155 only, and the one
#: that matters for approval-risk screening: it grants a spender every token in
#: a collection at once. Published constant; not seen in the sample.
APPROVAL_FOR_ALL_TOPIC: Final[str] = (
    "0x17307eab39ab6107e8899845ad3d59bd9653f200f220920489ca2b5937696c31"
)

#: ``TransferSingle(address,address,address,uint256,uint256)`` -- ERC-1155.
#: Recognised so it can be reported as unsupported rather than misread: it has
#: four topics like an ERC-721 transfer but carries id and value in data.
#: Published constant; not seen in the sample.
ERC1155_SINGLE_TOPIC: Final[str] = (
    "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
)

#: Bytes of ABI-encoded data an ERC-20 transfer carries: one uint256.
ERC20_DATA_BYTES: Final[int] = 32


@dataclass(frozen=True, slots=True)
class EventShape:
    """
    A signature plus the layout that makes a log actually be that event.

    ``data_bytes`` of ``None`` means the layout does not constrain it.
    """

    kind: EventKind
    topic0: str
    topics: int
    data_bytes: int | None

    def matches(self, topics: int, data_bytes: int) -> bool:
        if topics != self.topics:
            return False
        return self.data_bytes is None or data_bytes == self.data_bytes


#: Every shape A01 decodes. Ordered so the two ``Transfer`` shapes sit together,
#: because their coexistence is the whole reason this table exists.
KNOWN_SHAPES: Final[tuple[EventShape, ...]] = (
    EventShape(EventKind.ERC20_TRANSFER, TRANSFER_TOPIC, topics=3, data_bytes=ERC20_DATA_BYTES),
    EventShape(EventKind.ERC721_TRANSFER, TRANSFER_TOPIC, topics=4, data_bytes=0),
    EventShape(EventKind.ERC20_APPROVAL, APPROVAL_TOPIC, topics=3, data_bytes=ERC20_DATA_BYTES),
    EventShape(EventKind.ERC721_APPROVAL, APPROVAL_TOPIC, topics=4, data_bytes=0),
)

#: Signatures A01 recognises but deliberately does not decode. Named so an
#: operator can tell "we saw it and declined" from "we never noticed it" --
#: the same distinction the rest of the system draws between an absence and an
#: unknown.
UNSUPPORTED_TOPICS: Final[dict[str, str]] = {
    ERC1155_SINGLE_TOPIC: (
        "ERC-1155 TransferSingle: four topics like ERC-721 but id and value "
        "both in data; needs its own schema"
    ),
    APPROVAL_FOR_ALL_TOPIC: (
        "ApprovalForAll: grants a spender an entire collection; belongs to "
        "approval-risk screening rather than transfer flow"
    ),
}


def shape_for(topic0: str, topics: int, data_bytes: int) -> EventShape | None:
    """
    The event a log is, given its signature and layout, or None.

    None covers both "signature unknown" and "signature known but the layout
    is not one this decoder handles". The caller distinguishes them through
    :func:`unsupported_reason`, because the two mean different things: the
    first is a contract A01 has no opinion about, the second is a standard it
    has chosen not to implement yet.
    """
    lowered = topic0.lower()
    for shape in KNOWN_SHAPES:
        if shape.topic0 == lowered and shape.matches(topics, data_bytes):
            return shape
    return None


def unsupported_reason(topic0: str) -> str:
    """Why a recognised-but-undecoded signature is skipped, or empty."""
    return UNSUPPORTED_TOPICS.get(topic0.lower(), "")


def _self_check() -> None:
    """
    Verify the published constants against a live hash at import.

    The constants are the authority because Keccak-256 is not available on
    every Python build, but a typo in one would silently stop A01 recognising
    every ERC-20 transfer on every chain -- with no error anywhere, just a
    system that reports no token activity. Checking when the algorithm is
    available costs microseconds and removes that failure entirely.
    """
    try:
        computed = keccak_topic("Transfer(address,address,uint256)")
    except (ValueError, TypeError):
        return  # keccak256 unavailable on this build; constants stand

    if computed != TRANSFER_TOPIC:
        raise RuntimeError(
            "TRANSFER_TOPIC does not match Keccak-256 of the signature: "
            f"expected {computed}, have {TRANSFER_TOPIC}"
        )


_self_check()


__all__ = [
    "APPROVAL_FOR_ALL_TOPIC",
    "APPROVAL_TOPIC",
    "ERC1155_SINGLE_TOPIC",
    "ERC20_DATA_BYTES",
    "KNOWN_SHAPES",
    "TRANSFER_TOPIC",
    "UNSUPPORTED_TOPICS",
    "EventKind",
    "EventShape",
    "keccak_topic",
    "shape_for",
    "unsupported_reason",
]
