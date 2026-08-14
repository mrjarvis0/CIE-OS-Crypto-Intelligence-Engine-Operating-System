"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    schemas.token

Purpose:
    The canonical shapes for token and NFT movements, and the record that says
    how much of a block's event stream A01 actually understood.

Design goals:
    - Amount scale carried, never assumed
    - Fungible and non-fungible kept as separate types, not one with nulls
    - Mint and burn distinguishable from a transfer between holders
    - Identity keyed on the log's own position, so a replay is idempotent
    - Coverage of the decode stated alongside the results

Notes:
    **Scale is the field that decides whether any of this is usable.** An
    ERC-20 amount is an integer in the token's own base unit and the exponent
    lives in the contract's ``decimals()``, which needs an ``eth_call`` A01 does
    not make. USDC uses 6, most tokens use 18, and some use neither. Assuming 18
    renders a 140 USDC transfer as 140 trillion — a number that passes every
    sanity check a reader applies and is wrong by twelve orders of magnitude.

    So :class:`CanonicalTokenTransfer` carries ``decimals_known``, and a
    consumer that wants a human-readable figure has to confront the fact that
    it cannot have one yet. This is the same discipline as
    :class:`skills.base.Coverage`: state the limit rather than paper over it.

    **Fungible and non-fungible are separate types** even though the chain
    emits them under one signature. A single type with an optional ``amount``
    and an optional ``token_id`` puts the burden of checking on every consumer,
    and the one that forgets treats a tokenId as a quantity — the exact
    confusion :mod:`contracts.events` exists to prevent, reintroduced one layer
    up.

    Identity is ``chain:tx_hash:log_index``. A transaction can emit the same
    transfer twice (a router moving through two pools), so the transaction hash
    alone is not unique and deduplicating on it would silently drop real
    movements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .address import Address
from .amount import Amount


@dataclass(frozen=True, slots=True)
class CanonicalTokenTransfer:
    """
    One ERC-20 movement.

    ``value`` is the raw integer the contract emitted. ``decimals_known`` says
    whether the exponent needed to make it a human quantity has been
    established; while it is False, the number is comparable against other
    transfers of the *same* token and against nothing else.
    """

    chain: str
    tx_hash: str
    log_index: int
    block_number: int
    block_hash: str
    #: The token contract. Not the sender -- the contract that emitted the event.
    token: Address
    from_address: Address
    to_address: Address
    value: Amount
    #: False until a decimals source exists. See the module note.
    decimals_known: bool = False
    is_mint: bool = False
    is_burn: bool = False
    source_record_id: str = ""

    def __post_init__(self) -> None:
        if not self.tx_hash.strip():
            raise ValueError("token transfer has no transaction hash")
        if self.log_index < 0:
            raise ValueError("log index must be >= 0")
        if self.block_number < 0:
            raise ValueError("block number must be >= 0")
        if self.is_mint and self.is_burn:
            raise ValueError(
                "a transfer cannot be both a mint and a burn; zero-to-zero is "
                "not a movement"
            )

    @property
    def key(self) -> str:
        """
        Storage key.

        Log index is part of it because one transaction routinely emits the
        same transfer twice — a swap through two pools, say — and keying on the
        hash alone would drop the second as a duplicate.
        """
        return f"{self.chain}:{self.tx_hash}:{self.log_index}"

    @property
    def economic(self) -> bool:
        """Whether value moved between two holders, rather than being created."""
        return not (self.is_mint or self.is_burn)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "tx_hash": self.tx_hash,
            "log_index": self.log_index,
            "block_number": self.block_number,
            "token": self.token.value,
            "from": self.from_address.value,
            "to": self.to_address.value,
            "value": self.value.as_dict(),
            "decimals_known": self.decimals_known,
            "is_mint": self.is_mint,
            "is_burn": self.is_burn,
            "economic": self.economic,
        }


@dataclass(frozen=True, slots=True)
class CanonicalNftTransfer:
    """
    One ERC-721 movement.

    Deliberately has no amount field. An NFT transfer moves exactly one token,
    and a `value: 1` would invite summing across collections into a figure that
    means nothing.
    """

    chain: str
    tx_hash: str
    log_index: int
    block_number: int
    block_hash: str
    collection: Address
    from_address: Address
    to_address: Address
    token_id: int
    is_mint: bool = False
    is_burn: bool = False
    source_record_id: str = ""

    def __post_init__(self) -> None:
        if not self.tx_hash.strip():
            raise ValueError("nft transfer has no transaction hash")
        if self.token_id < 0:
            raise ValueError("token id must be >= 0")
        if self.is_mint and self.is_burn:
            raise ValueError("a transfer cannot be both a mint and a burn")

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.tx_hash}:{self.log_index}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "tx_hash": self.tx_hash,
            "log_index": self.log_index,
            "block_number": self.block_number,
            "collection": self.collection.value,
            "from": self.from_address.value,
            "to": self.to_address.value,
            "token_id": str(self.token_id),
            "is_mint": self.is_mint,
            "is_burn": self.is_burn,
        }


@dataclass(frozen=True, slots=True)
class TokenActivity:
    """
    Everything A01 understood from one block's event stream, and how much it
    did not.

    ``undecoded`` is carried rather than discarded because it is the honest
    denominator. "Twelve token transfers in this block" invites the reading
    that twelve is all there were; "twelve decoded of nine hundred events"
    does not.
    """

    chain: str
    block_number: int
    block_hash: str
    transfers: tuple[CanonicalTokenTransfer, ...] = ()
    nft_transfers: tuple[CanonicalNftTransfer, ...] = ()
    #: Logs seen but not decoded — other standards, other events, malformed.
    undecoded: int = 0
    #: Logs recognised as a standard A01 has chosen not to decode yet.
    unsupported: int = 0
    source_record_id: str = ""
    quality_notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_logs(self) -> int:
        return len(self.transfers) + len(self.nft_transfers) + self.undecoded

    @property
    def decoded_fraction(self) -> float:
        """
        Share of the event stream A01 turned into records.

        Low is normal — most logs are protocol-specific events A01 has no
        opinion about. It is reported so a consumer can tell a quiet block from
        a block full of events A01 cannot read.
        """
        if not self.total_logs:
            return 0.0
        return round(
            (len(self.transfers) + len(self.nft_transfers)) / self.total_logs, 4
        )

    @property
    def empty(self) -> bool:
        return not self.transfers and not self.nft_transfers

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "block_number": self.block_number,
            "token_transfers": len(self.transfers),
            "nft_transfers": len(self.nft_transfers),
            "undecoded": self.undecoded,
            "unsupported": self.unsupported,
            "total_logs": self.total_logs,
            "decoded_fraction": self.decoded_fraction,
            "quality_notes": list(self.quality_notes),
        }


__all__ = ["CanonicalNftTransfer", "CanonicalTokenTransfer", "TokenActivity"]
