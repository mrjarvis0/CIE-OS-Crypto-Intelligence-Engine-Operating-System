"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    schemas.block

Purpose:
    The canonical block and transaction records every chain is mapped into, and
    the canonicality flag that makes a reorg survivable in storage.

Design goals:
    - One shape per entity, chain differences absorbed by normalization
    - Provenance referenced by id, not copied into every row
    - Withdrawal recorded, never performed by deletion
    - Amounts and addresses carried as value objects, not raw strings
    - No chain-specific field names in the canonical form

Notes:
    Provenance is referenced rather than embedded. Every canonical row carries
    the ``source_record_id`` of the raw capture it came from, so the provider,
    the method and the observation time are one lookup away without being
    duplicated across every transaction in a block. Copying them would violate
    single-source-of-truth and would make a provenance correction a migration.

    Canonicality is a flag, not a delete. Design rule DR-09 requires historical
    records to be immutable, and a reorg is exactly where that rule earns its
    place: the orphaned blocks are not wrong observations, they are correct
    observations of a chain state that was later abandoned. Deleting them throws
    away the evidence that a reorg happened at all, which is the one thing an
    analyst investigating a double-spend needs. So ``canonical`` goes false and
    ``withdrawn_at`` is set, and every read path filters on it.

    That filter is the part that has to be got right. A query that forgets
    ``WHERE canonical = 1`` reads abandoned history as fact, and it looks
    entirely normal while doing it -- which is why the repository exposes
    canonical-only reads by default and makes including withdrawn rows an
    explicit argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .address import Address
from .amount import Amount


def utc_now() -> datetime:
    return datetime.now(UTC)


def from_unix(seconds: int) -> datetime:
    """
    Chain timestamp to UTC datetime.

    Chain timestamps are set by whoever produced the block and are only loosely
    constrained, so this converts without asserting the value is sane -- that
    check belongs to the quality pass, which can report it rather than crash on
    it.
    """
    return datetime.fromtimestamp(seconds, tz=UTC)


@dataclass(frozen=True, slots=True)
class CanonicalTransaction:
    """
    One transaction, in the same shape whatever chain produced it.

    ``to_address`` is None for a contract creation. That is a real absence and
    must not be filled with the zero address: the zero address is a genuine
    counterparty for mints and burns, so conflating the two makes every
    deployment look like a burn.
    """

    chain: str
    tx_hash: str
    block_number: int
    block_hash: str
    #: Position within the block. Establishes ordering inside a block, which
    #: matters for anything reconstructing state transitions.
    index: int
    from_address: Address
    to_address: Address | None
    value: Amount
    #: Present only when the sensor was asked for expanded transactions.
    gas_limit: int | None = None
    gas_price: Amount | None = None
    nonce: int | None = None
    input_size: int = 0
    source_record_id: str = ""

    def __post_init__(self) -> None:
        if not self.tx_hash.strip():
            raise ValueError("transaction hash cannot be empty")
        if self.block_number < 0:
            raise ValueError("block number must be >= 0")
        if self.index < 0:
            raise ValueError("transaction index must be >= 0")

    @property
    def is_contract_creation(self) -> bool:
        return self.to_address is None

    @property
    def key(self) -> str:
        """Storage key. Chain-scoped: tx hashes are not unique across chains."""
        return f"{self.chain}:{self.tx_hash}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "index": self.index,
            "from": self.from_address.value,
            "to": self.to_address.value if self.to_address else None,
            "value": self.value.as_dict(),
            "contract_creation": self.is_contract_creation,
            "source_record_id": self.source_record_id,
        }


@dataclass(frozen=True, slots=True)
class CanonicalBlock:
    """
    One block, with the linkage that lets a reorg be detected after the fact.

    ``parent_hash`` is stored, not just the height, for the same reason the
    ingestion checkpoint stores it: a stored chain that records only heights
    cannot be checked for consistency later, so a reorg that was mishandled at
    capture time is undiscoverable in the data.
    """

    chain: str
    number: int
    block_hash: str
    parent_hash: str
    timestamp: datetime
    transaction_count: int
    #: False once a reorg abandons this block. Never deleted -- the observation
    #: was correct, the chain state it described was not final.
    canonical: bool = True
    withdrawn_at: datetime | None = None
    gas_used: int | None = None
    gas_limit: int | None = None
    miner: Address | None = None
    transactions: tuple[CanonicalTransaction, ...] = ()
    source_record_id: str = ""
    source_provider: str = ""
    observed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("block must name its chain")
        if self.number < 0:
            raise ValueError("block number must be >= 0")
        if not self.block_hash.strip():
            raise ValueError("block hash cannot be empty")
        if self.number > 0 and not self.parent_hash.strip():
            raise ValueError(f"block {self.number} has no parent hash")
        if self.transaction_count < 0:
            raise ValueError("transaction count must be >= 0")
        if self.canonical and self.withdrawn_at is not None:
            raise ValueError("a canonical block cannot have a withdrawal time")
        if not self.canonical and self.withdrawn_at is None:
            raise ValueError("a withdrawn block must record when it was withdrawn")

    # -- properties -------------------------------------------------------

    @property
    def key(self) -> str:
        """Storage key. The hash, not the height: a reorg reuses heights."""
        return f"{self.chain}:{self.block_hash}"

    @property
    def transactions_expanded(self) -> bool:
        """
        Whether the transaction bodies were captured, not just counted.

        Distinguishes an empty block from a block fetched without expansion.
        Reading the second as the first would report a busy block as idle.
        """
        return bool(self.transactions)

    @property
    def gas_utilisation(self) -> float | None:
        """Fraction of the gas limit consumed, when both figures are known."""
        if not self.gas_used or not self.gas_limit:
            return None
        return self.gas_used / self.gas_limit

    def withdrawn(self, at: datetime | None = None) -> CanonicalBlock:
        """
        The same block, marked as no longer canonical.

        Returns a new record rather than mutating: the block is frozen because
        an observation should not change after it is made, and a withdrawal is
        a new fact about it rather than a correction to it.
        """
        from dataclasses import replace

        return replace(self, canonical=False, withdrawn_at=at or utc_now())

    def as_dict(self, *, include_transactions: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chain": self.chain,
            "number": self.number,
            "block_hash": self.block_hash,
            "parent_hash": self.parent_hash,
            "timestamp": self.timestamp.isoformat(),
            "transaction_count": self.transaction_count,
            "canonical": self.canonical,
            "withdrawn_at": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
            "gas_used": self.gas_used,
            "gas_limit": self.gas_limit,
            "miner": self.miner.value if self.miner else None,
            "source_record_id": self.source_record_id,
            "source_provider": self.source_provider,
            "observed_at": self.observed_at.isoformat(),
        }
        if include_transactions:
            payload["transactions"] = [tx.as_dict() for tx in self.transactions]
        return payload


__all__ = ["CanonicalBlock", "CanonicalTransaction", "from_unix", "utc_now"]
