"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.security.approval_risk.approvals

Purpose:
    Decode ERC-20 ``Approval``, ERC-721 ``Approval`` and ERC-721/1155
    ``ApprovalForAll`` logs into typed records.

Design goals:
    - Shape established before a single field is read
    - Refuse over guess; every refusal carries its reason
    - Amounts through :class:`Amount`, so 256-bit values survive
    - Pure: no I/O, no contract calls, no chain access

Why this decoder is here and not in ``contracts/``
--------------------------------------------------
``contracts/events.py`` recognises approvals and then declines them:

    "Approvals are recognised so they are not counted as unknown, but they
    are not transfers and must not enter flow analysis."

and ``contracts/signatures.py`` sends ``ApprovalForAll`` here by name:

    "ApprovalForAll: grants a spender an entire collection; belongs to
    approval-risk screening rather than transfer flow"

That is the correct split. An approval moves nothing, so letting one into
flow analysis would inflate every total it touched. This module is the
consumer those notes point at, and it reuses ``contracts.signatures`` for the
topic constants so there is exactly one place a signature is written down.

The trap this decoder has to avoid
----------------------------------
``Approval(address,address,uint256)`` and
``ApprovalForAll(address,address,bool)`` have **identical layout**: three
topics and one 32-byte data word. They are told apart by ``topic0`` alone.

So the layout check that saves ``contracts/events.py`` from confusing ERC-20
and ERC-721 transfers does nothing here, and the danger runs the other way:
read an ``ApprovalForAll`` as an ERC-20 ``Approval`` and its boolean ``true``
decodes as an allowance of exactly 1 base unit -- a harmless-looking dust
approval standing in for a grant over an entire NFT collection. The
signature is therefore matched first and exactly, and an unrecognised one is
refused rather than fitted to the nearest shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from contracts.signatures import APPROVAL_FOR_ALL_TOPIC, APPROVAL_TOPIC
from schemas.address import Address, AddressError, ZERO_ADDRESS
from schemas.amount import Amount, AmountError

__all__ = [
    "ApprovalKind",
    "ApprovalRefusal",
    "DecodedApproval",
    "decode_approval",
    "decode_approvals",
    "is_approval_topic",
]

#: Hex characters in a 32-byte topic word.
_WORD: Final[int] = 64

#: Bytes of ABI-encoded data an ERC-20 Approval and an ApprovalForAll each
#: carry: one uint256, or one bool padded to a word. Identical, deliberately
#: named once so the coincidence is visible at the point it matters.
_ONE_WORD_BYTES: Final[int] = 32


class ApprovalKind(StrEnum):
    """What a decoded approval grants."""

    #: ``approve(spender, value)`` -- a spending allowance over one token,
    #: capped at ``value``. Replaces any previous allowance; it does not add.
    ERC20 = "erc20_approval"
    #: ``approve(to, tokenId)`` -- one NFT. A ``to`` of the zero address is a
    #: revocation.
    ERC721_TOKEN = "erc721_approval"
    #: ``setApprovalForAll(operator, approved)`` -- every token the owner holds
    #: in that collection, now and in future. The widest grant on the chain.
    ERC721_ALL = "erc721_approval_for_all"


@dataclass(frozen=True, slots=True)
class ApprovalRefusal:
    """
    Why one log was not decoded.

    ``recognised`` separates "this is an approval whose layout is wrong" from
    "this is not an approval at all" -- the same distinction
    ``contracts/events.py`` draws, and for the same reason: an operator needs
    to tell a declined log from an unnoticed one.
    """

    reason: str
    topic0: str = ""
    recognised: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "decoded": False,
            "reason": self.reason,
            "topic0": self.topic0,
            "recognised": self.recognised,
        }


@dataclass(frozen=True, slots=True)
class DecodedApproval:
    """
    One approval, as the contract emitted it.

    ``allowance`` is present only for :attr:`ApprovalKind.ERC20`; ``token_id``
    only for :attr:`ApprovalKind.ERC721_TOKEN`; ``approved`` only for
    :attr:`ApprovalKind.ERC721_ALL`. Each is ``None`` elsewhere rather than
    defaulted, because a defaulted zero here reads as a revocation.

    Decimals are deliberately not resolved, for the reason
    ``contracts/events.py`` gives: the exponent lives in the contract's
    ``decimals()``, reachable only by ``eth_call``, which this layer does not
    do. Assuming 18 would render a 6-decimal token's allowance a trillion
    times too large.
    """

    kind: ApprovalKind
    chain: str
    token: Address
    owner: Address
    spender: Address
    allowance: Amount | None = None
    token_id: int | None = None
    approved: bool | None = None
    block_number: int | None = None
    log_index: int | None = None
    tx_hash: str = ""
    #: Block timestamp, when the caller has joined the block. A log does not
    #: carry one, so this is ``None`` far more often than not -- and it stays
    #: ``None`` rather than being filled with the time the log was read, which
    #: would make every approval look freshly granted.
    block_timestamp: float | None = None

    @property
    def is_revocation(self) -> bool:
        """
        True when this event withdraws a grant rather than making one.

        Each standard revokes differently, and reading one form as another is
        how a revoked approval stays on the books: ERC-20 sets the allowance
        to zero, ERC-721 approves the zero address, ApprovalForAll passes
        ``false``.
        """
        if self.kind is ApprovalKind.ERC20:
            return self.allowance is not None and self.allowance.raw == 0
        if self.kind is ApprovalKind.ERC721_TOKEN:
            return self.spender.value == ZERO_ADDRESS
        return self.approved is False

    @property
    def key(self) -> tuple[str, str, str, str]:
        """
        Identity of the grant this event sets, so a later event replaces it.

        The three standards do not agree on what a grant is keyed by, and
        using one key for all three is wrong in both directions:

        * **ERC-20** allows an owner many simultaneous spenders on one token.
          The spender is part of the identity; leaving it out would let an
          approval to a second spender overwrite the record of the first, and
          a live unlimited allowance would silently vanish from the report.

        * **ERC-721 per-token** allows exactly *one* approved address per
          token id -- ``approve`` overwrites, it does not accumulate. So the
          identity is the token id and the spender is deliberately **not** in
          it. Including it would leave every previously approved address on
          the books as though it were still live.

        * **ApprovalForAll** is per operator again, like ERC-20.

        The kind leads the key so a ``setApprovalForAll`` and a single-token
        approval to the same operator stay separate grants; revoking one must
        not appear to revoke the other.
        """
        if self.kind is ApprovalKind.ERC721_TOKEN:
            return (str(self.kind), self.token.value, self.owner.value, str(self.token_id))
        return (str(self.kind), self.token.value, self.owner.value, self.spender.value)

    @property
    def order(self) -> tuple[int, int]:
        """Chain order key. Missing positions sort last, never first."""
        return (
            self.block_number if self.block_number is not None else 1 << 62,
            self.log_index if self.log_index is not None else 1 << 62,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "decoded": True,
            "kind": str(self.kind),
            "chain": self.chain,
            "token": self.token.value,
            "owner": self.owner.value,
            "spender": self.spender.value,
            # A 256-bit allowance is not a JSON number.
            "allowance": str(self.allowance.raw) if self.allowance else None,
            "token_id": self.token_id,
            "approved": self.approved,
            "block_number": self.block_number,
            "log_index": self.log_index,
            "tx_hash": self.tx_hash,
            "block_timestamp": self.block_timestamp,
            "is_revocation": self.is_revocation,
        }


def is_approval_topic(topic0: Any) -> bool:
    """True when ``topic0`` is one of the approval signatures."""
    lowered = str(topic0 or "").lower()
    return lowered in {APPROVAL_TOPIC, APPROVAL_FOR_ALL_TOPIC}


def _address_from_topic(topic: str, chain: str) -> Address:
    """
    Read an address out of a 32-byte topic word.

    An indexed address is left-padded to 32 bytes, so the address is the last
    40 hex characters. Slicing from the front would yield twelve zero bytes
    followed by half an address -- valid-looking, and belonging to nobody.
    """
    body = topic[2:] if topic.startswith("0x") else topic
    if len(body) != _WORD:
        raise AddressError(f"topic is not a 32-byte word: {topic!r}")
    return Address.parse("0x" + body[-40:], chain)


def _uint_from(hex_text: str) -> int:
    body = hex_text[2:] if hex_text.startswith("0x") else hex_text
    if not body:
        raise ValueError("empty quantity")
    return int(body, 16)


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        text = str(value).strip()
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        number = float(int(text, 16)) if text.lower().startswith("0x") else float(text)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def decode_approval(log: Any, *, chain: str) -> DecodedApproval | ApprovalRefusal:
    """
    Decode one log into an approval, or refuse it and say why.

    Signature first, layout second, fields third. Reading fields before
    establishing what the event is produces a record that names a real
    contract, a real block and two real addresses, and is wrong -- the exact
    failure ``contracts/events.py`` is built to avoid.
    """
    if not isinstance(log, dict):
        return ApprovalRefusal(reason=f"log is not a mapping: {type(log).__name__}")

    topics = log.get("topics") or []
    if not isinstance(topics, (list, tuple)) or not topics:
        return ApprovalRefusal(reason="log carries no topics")

    topic0 = str(topics[0] or "").lower()
    if not is_approval_topic(topic0):
        return ApprovalRefusal(reason="not an approval signature", topic0=topic0)

    data = str(log.get("data", "0x") or "0x")
    data_bytes = max(len(data) - 2, 0) // 2

    if topic0 == APPROVAL_FOR_ALL_TOPIC:
        kind = ApprovalKind.ERC721_ALL
        expected_topics, expected_bytes = 3, _ONE_WORD_BYTES
    elif len(topics) == 4:
        kind = ApprovalKind.ERC721_TOKEN
        expected_topics, expected_bytes = 4, 0
    else:
        kind = ApprovalKind.ERC20
        expected_topics, expected_bytes = 3, _ONE_WORD_BYTES

    if len(topics) != expected_topics or data_bytes != expected_bytes:
        return ApprovalRefusal(
            reason=(
                f"{kind.value} needs {expected_topics} topic(s) and "
                f"{expected_bytes} byte(s) of data; this log has "
                f"{len(topics)} and {data_bytes}"
            ),
            topic0=topic0,
            recognised=True,
        )

    try:
        token = Address.parse(log.get("address"), chain)
        owner = _address_from_topic(str(topics[1]), chain)
        spender = _address_from_topic(str(topics[2]), chain)
    except (AddressError, AttributeError, TypeError) as exc:
        return ApprovalRefusal(
            reason=f"address field unreadable: {exc}", topic0=topic0, recognised=True
        )

    allowance: Amount | None = None
    token_id: int | None = None
    approved: bool | None = None

    try:
        if kind is ApprovalKind.ERC20:
            allowance = Amount(_uint_from(data), decimals=0)
        elif kind is ApprovalKind.ERC721_TOKEN:
            token_id = _uint_from(str(topics[3]))
        else:
            # A bool is ABI-encoded as a full word: zero is false, anything
            # else is true. Comparing against the literal one-word "true"
            # would refuse a technically valid encoding.
            approved = _uint_from(data) != 0
    except (AmountError, ValueError) as exc:
        return ApprovalRefusal(
            reason=f"quantity unreadable: {exc}", topic0=topic0, recognised=True
        )

    return DecodedApproval(
        kind=kind,
        chain=chain,
        token=token,
        owner=owner,
        spender=spender,
        allowance=allowance,
        token_id=token_id,
        approved=approved,
        block_number=_int_or_none(log.get("blockNumber", log.get("block_number"))),
        log_index=_int_or_none(log.get("logIndex", log.get("log_index"))),
        tx_hash=str(log.get("transactionHash", log.get("tx_hash", "")) or ""),
        block_timestamp=_float_or_none(
            log.get("blockTimestamp", log.get("block_timestamp", log.get("timestamp")))
        ),
    )


def decode_approvals(
    logs: Any, *, chain: str
) -> tuple[tuple[DecodedApproval, ...], tuple[ApprovalRefusal, ...]]:
    """
    Decode many logs, returning ``(approvals, refusals)``.

    Refusals are returned rather than dropped. A silently discarded log is
    indistinguishable from one that was never there, and the count of what a
    screen could not read is part of how far its answer should be trusted.
    """
    approvals: list[DecodedApproval] = []
    refusals: list[ApprovalRefusal] = []

    for log in logs or ():
        outcome = decode_approval(log, chain=chain)
        if isinstance(outcome, DecodedApproval):
            approvals.append(outcome)
        else:
            refusals.append(outcome)

    return tuple(approvals), tuple(refusals)
