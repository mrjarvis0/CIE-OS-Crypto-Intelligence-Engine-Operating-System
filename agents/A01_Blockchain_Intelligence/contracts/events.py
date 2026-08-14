"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    contracts.events

Purpose:
    Turn one raw log into a typed transfer, or refuse it and say why.

Design goals:
    - Refuse over guess; a decoded transfer must be one the contract emitted
    - Shape checked before fields are read, never after
    - Every refusal carries its reason, so a skipped log is explicable
    - Amounts through :class:`Amount`, so 256-bit values survive
    - Pure: no I/O, no contract calls, no chain access

Notes:
    Decoding a log is trivially easy to do almost-correctly, and an
    almost-correct transfer is worse than none: it names a real contract, a
    real block, and two real addresses, so nothing about it looks wrong. The
    guard is to establish *what the event is* from its shape before reading a
    single field -- see :mod:`contracts.signatures` for why topic0 alone cannot
    do that.

    **Decimals are deliberately not resolved here.** An ERC-20 amount is an
    integer in the token's own base unit, and the exponent lives in the
    contract's ``decimals()`` -- reachable only by ``eth_call``, which this
    layer does not do. Assuming 18 would render 6-decimal USDC a trillion times
    too large, and the number would look entirely ordinary. So the raw integer
    is carried with ``decimals_known = False``, and every consumer has to
    decide what it may say about a quantity whose scale is unknown.

    **Mints and burns are transfers from or to the zero address** and are
    emitted exactly like any other. They are decoded normally and flagged,
    because folding them into flow totals silently doubles supply movements
    that never touched a holder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from schemas.address import Address, AddressError, ZERO_ADDRESS
from schemas.amount import Amount, AmountError

from .signatures import EventKind, shape_for, unsupported_reason

#: An ABI-encoded 32-byte word as hex characters, without the 0x prefix.
_WORD: Final[int] = 64


@dataclass(frozen=True, slots=True)
class DecodedTransfer:
    """
    One transfer read out of a log.

    ``token_id`` is set for ERC-721 and ``amount`` for ERC-20; they are never
    both meaningful. Keeping one type rather than two mirrors how the chain
    emits them -- one signature, two shapes -- and lets a caller handle the
    common fields once.
    """

    kind: EventKind
    chain: str
    contract: Address
    sender: Address
    recipient: Address
    #: ERC-20 only. The raw integer in the token's base unit.
    amount: Amount | None = None
    #: ERC-721 only.
    token_id: int | None = None
    tx_hash: str = ""
    block_number: int = 0
    log_index: int = 0

    @property
    def is_nft(self) -> bool:
        return self.kind is EventKind.ERC721_TRANSFER

    @property
    def is_mint(self) -> bool:
        """
        Created rather than moved.

        Flagged because a mint counted as a transfer inflates a holder's
        apparent receipts with tokens that no one sent them.
        """
        return self.sender.value == ZERO_ADDRESS

    @property
    def is_burn(self) -> bool:
        return self.recipient.value == ZERO_ADDRESS

    @property
    def economic(self) -> bool:
        """Whether this moved value between two holders."""
        return not (self.is_mint or self.is_burn)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "chain": self.chain,
            "contract": self.contract.value,
            "from": self.sender.value,
            "to": self.recipient.value,
            "amount": self.amount.as_dict() if self.amount else None,
            "token_id": self.token_id,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "log_index": self.log_index,
            "is_mint": self.is_mint,
            "is_burn": self.is_burn,
        }


@dataclass(frozen=True, slots=True)
class DecodeRefusal:
    """
    A log that was not decoded, and why.

    Refusals are returned rather than dropped so a caller can count them. A
    rising refusal rate for one contract is a signal -- it usually means a
    non-standard implementation, occasionally something deliberately shaped to
    confuse a decoder.
    """

    reason: str
    topic0: str = ""
    #: True when the signature is one A01 knows and has chosen not to decode,
    #: as opposed to one it does not recognise at all.
    recognised: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "topic0": self.topic0,
            "recognised": self.recognised,
        }


def _address_from_topic(topic: str, chain: str) -> Address:
    """
    Read an address out of a 32-byte topic word.

    An indexed address is left-padded to 32 bytes, so the address is the last
    40 hex characters. Slicing from the front would produce twelve zero bytes
    followed by the first half of the address -- a valid-looking address that
    belongs to nobody.
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


def decode_log(log: Any, *, chain: str) -> DecodedTransfer | DecodeRefusal:
    """
    Decode one log into a transfer, or refuse it.

    The order matters: shape is established first, and only then are fields
    read. Reading first and validating afterwards is how a decoder ends up
    having already produced a plausible transfer by the time it discovers the
    event was something else.
    """
    if not isinstance(log, dict):
        return DecodeRefusal(reason=f"log is {type(log).__name__}, not an object")

    topics = log.get("topics")
    if not isinstance(topics, list) or not topics:
        return DecodeRefusal(reason="log has no topics")

    topic0 = str(topics[0]).lower()
    data = str(log.get("data", "0x") or "0x")
    data_bytes = max(len(data) - 2, 0) // 2

    shape = shape_for(topic0, len(topics), data_bytes)
    if shape is None:
        declined = unsupported_reason(topic0)
        if declined:
            return DecodeRefusal(reason=declined, topic0=topic0, recognised=True)
        return DecodeRefusal(
            reason=(
                f"no known event has {len(topics)} topic(s) and {data_bytes} "
                "byte(s) of data for this signature"
            ),
            topic0=topic0,
        )

    if shape.kind not in {EventKind.ERC20_TRANSFER, EventKind.ERC721_TRANSFER}:
        # Approvals are recognised so they are not counted as unknown, but they
        # are not transfers and must not enter flow analysis.
        return DecodeRefusal(
            reason=f"{shape.kind.value} is not a transfer",
            topic0=topic0,
            recognised=True,
        )

    try:
        contract = Address.parse(log.get("address"), chain)
        sender = _address_from_topic(str(topics[1]), chain)
        recipient = _address_from_topic(str(topics[2]), chain)
    except (AddressError, AttributeError, TypeError) as exc:
        return DecodeRefusal(reason=f"address field unreadable: {exc}", topic0=topic0)

    amount: Amount | None = None
    token_id: int | None = None
    try:
        if shape.kind is EventKind.ERC20_TRANSFER:
            # decimals unknown at this layer -- see the module note.
            amount = Amount(_uint_from(data), decimals=0)
        else:
            token_id = _uint_from(str(topics[3]))
    except (AmountError, ValueError) as exc:
        return DecodeRefusal(reason=f"quantity unreadable: {exc}", topic0=topic0)

    return DecodedTransfer(
        kind=shape.kind,
        chain=chain,
        contract=contract,
        sender=sender,
        recipient=recipient,
        amount=amount,
        token_id=token_id,
        tx_hash=str(log.get("transactionHash", "") or ""),
        block_number=_safe_height(log.get("blockNumber")),
        log_index=_safe_height(log.get("logIndex")),
    )


def _safe_height(value: Any) -> int:
    """A log's block number or index, or zero when unreadable."""
    if isinstance(value, int) and not isinstance(value, bool):
        return max(value, 0)
    if isinstance(value, str) and value.strip():
        try:
            return max(_uint_from(value), 0)
        except ValueError:
            return 0
    return 0


def decode_logs(
    logs: Any, *, chain: str
) -> tuple[tuple[DecodedTransfer, ...], tuple[DecodeRefusal, ...]]:
    """
    Decode a batch, split into transfers and refusals.

    Split rather than filtered, for the same reason
    :meth:`normalization.Normalizer.normalize_all` splits: silently dropping
    what could not be read makes a contract emitting garbage look like a
    contract emitting nothing.
    """
    if not isinstance(logs, list):
        return (), (DecodeRefusal(reason=f"expected a list, got {type(logs).__name__}"),)

    transfers: list[DecodedTransfer] = []
    refusals: list[DecodeRefusal] = []
    for log in logs:
        result = decode_log(log, chain=chain)
        if isinstance(result, DecodedTransfer):
            transfers.append(result)
        else:
            refusals.append(result)

    return tuple(transfers), tuple(refusals)


__all__ = ["DecodeRefusal", "DecodedTransfer", "decode_log", "decode_logs"]
