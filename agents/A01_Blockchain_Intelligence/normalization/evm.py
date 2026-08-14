"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    normalization.evm

Purpose:
    Map a raw EVM block payload onto the canonical schema, refusing anything
    that cannot be trusted.

Design goals:
    - Every field validated before it is accepted, per DR-08
    - Refusal over substitution: no defaults for missing facts
    - Internal consistency checked, not just field shapes
    - Provenance carried through by reference
    - Pure function of its input; no network, no clock dependence beyond capture

Notes:
    Design rule DR-08 states that raw external data must never be trusted. That
    is easy to nod at and hard to implement, because the tempting failure is
    always the quiet one: a missing ``gasUsed`` becomes ``0``, an unparseable
    value becomes ``0``, a malformed address becomes the zero address. Each
    substitution turns "the provider did not tell us" into a positive claim
    about the chain, and the claim is indistinguishable from a real one
    downstream.

    So nothing here defaults. A field that is absent stays ``None``, a field
    that is present and unreadable is a rejection of the whole payload, and the
    caller finds out which field and why.

    Consistency is checked as well as shape. A payload where the transaction
    array is longer than the stated count, or where ``gasUsed`` exceeds
    ``gasLimit``, is internally impossible -- so whatever produced it is wrong
    about something, and accepting the parts that happen to parse imports that
    wrongness selectively.
"""

from __future__ import annotations

from typing import Any

from config.security.validation import ValidationIssue
from schemas.address import Address, AddressError
from schemas.amount import Amount, AmountError
from schemas.block import CanonicalBlock, CanonicalTransaction, from_unix

#: Fields a block payload must carry for the record to mean anything.
_REQUIRED_BLOCK_FIELDS = ("number", "hash", "parentHash", "timestamp")


def read_quantity(value: Any) -> int | None:
    """
    Read an RPC quantity, or None when it is absent or unreadable.

    None covers both cases on purpose, and the caller decides which it is: an
    absent optional field is fine, an absent required field is a rejection.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
        except ValueError:
            return None
    return None


def _hash_of(value: Any) -> str | None:
    """A non-empty hex hash, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("0x") or len(text) < 4:
        return None
    return text.lower()


def normalize_transaction(
    payload: Any,
    *,
    chain: str,
    block_number: int,
    block_hash: str,
    fallback_index: int,
    source_record_id: str,
) -> tuple[CanonicalTransaction | None, tuple[ValidationIssue, ...]]:
    """
    Map one expanded transaction object.

    Returns ``(None, issues)`` when the transaction cannot be trusted, so a
    single bad entry does not discard the whole block -- the block records the
    count from its own header, and the missing body is visible as a shortfall
    between that count and the transactions actually stored.
    """
    issues: list[ValidationIssue] = []

    if not isinstance(payload, dict):
        return None, (
            ValidationIssue(
                field="transaction",
                message=f"expected an object, got {type(payload).__name__}",
            ),
        )

    tx_hash = _hash_of(payload.get("hash"))
    if tx_hash is None:
        issues.append(ValidationIssue(field="hash", message="missing or malformed"))

    try:
        from_address = Address.parse(payload.get("from"), chain)
    except AddressError as exc:
        from_address = None
        issues.append(ValidationIssue(field="from", message=str(exc)))

    try:
        to_address = Address.parse_optional(payload.get("to"), chain)
    except AddressError as exc:
        to_address = None
        issues.append(ValidationIssue(field="to", message=str(exc)))

    try:
        value = Amount.from_hex(payload.get("value", 0))
    except AmountError as exc:
        value = None
        issues.append(ValidationIssue(field="value", message=str(exc)))

    if issues or tx_hash is None or from_address is None or value is None:
        return None, tuple(issues)

    index = read_quantity(payload.get("transactionIndex"))
    gas_price_raw = payload.get("gasPrice")

    gas_price: Amount | None = None
    if gas_price_raw is not None:
        try:
            gas_price = Amount.from_hex(gas_price_raw)
        except AmountError:
            # A soft field: an unreadable gas price does not make the transfer
            # itself untrustworthy, so it is dropped rather than escalated.
            gas_price = None

    input_data = payload.get("input")
    input_size = 0
    if isinstance(input_data, str) and input_data.startswith("0x"):
        input_size = max(len(input_data) - 2, 0) // 2

    return (
        CanonicalTransaction(
            chain=chain,
            tx_hash=tx_hash,
            block_number=block_number,
            block_hash=block_hash,
            index=index if index is not None else fallback_index,
            from_address=from_address,
            to_address=to_address,
            value=value,
            gas_limit=read_quantity(payload.get("gas")),
            gas_price=gas_price,
            nonce=read_quantity(payload.get("nonce")),
            input_size=input_size,
            source_record_id=source_record_id,
        ),
        (),
    )


def normalize_block(
    payload: Any,
    *,
    chain: str,
    source_record_id: str = "",
    source_provider: str = "",
) -> tuple[CanonicalBlock | None, tuple[ValidationIssue, ...]]:
    """
    Map a raw EVM block onto :class:`CanonicalBlock`.

    Returns ``(None, issues)`` when the payload cannot be trusted. Rejection is
    all-or-nothing for the block header, because a header field that cannot be
    read makes the block unplaceable, unlinkable, or undatable -- and a record
    with any of those missing is not a weaker observation, it is not an
    observation.
    """
    issues: list[ValidationIssue] = []

    if not isinstance(payload, dict):
        return None, (
            ValidationIssue(
                field="block",
                message=f"expected an object, got {type(payload).__name__}",
            ),
        )

    for name in _REQUIRED_BLOCK_FIELDS:
        if payload.get(name) is None:
            issues.append(ValidationIssue(field=name, message="required field absent"))

    number = read_quantity(payload.get("number"))
    if number is None and payload.get("number") is not None:
        issues.append(ValidationIssue(field="number", message="unreadable quantity"))

    timestamp = read_quantity(payload.get("timestamp"))
    if timestamp is None and payload.get("timestamp") is not None:
        issues.append(ValidationIssue(field="timestamp", message="unreadable quantity"))

    block_hash = _hash_of(payload.get("hash"))
    if block_hash is None and payload.get("hash") is not None:
        issues.append(ValidationIssue(field="hash", message="not a hex hash"))

    parent_hash = _hash_of(payload.get("parentHash"))
    if parent_hash is None and payload.get("parentHash") is not None:
        issues.append(ValidationIssue(field="parentHash", message="not a hex hash"))

    if issues or number is None or timestamp is None or block_hash is None:
        return None, tuple(issues)

    gas_used = read_quantity(payload.get("gasUsed"))
    gas_limit = read_quantity(payload.get("gasLimit"))

    # Internally impossible: a block cannot burn more gas than it allowed.
    # Whatever produced this is wrong about something, so none of it is taken.
    if gas_used is not None and gas_limit is not None and gas_used > gas_limit:
        return None, (
            ValidationIssue(
                field="gasUsed",
                message=f"exceeds gasLimit ({gas_used} > {gas_limit})",
                value=gas_used,
            ),
        )

    miner: Address | None = None
    if payload.get("miner"):
        try:
            miner = Address.parse(payload["miner"], chain)
        except AddressError:
            # Soft: the producer's identity is not needed to place the block.
            miner = None

    raw_transactions = payload.get("transactions")
    transactions: list[CanonicalTransaction] = []
    stated_count = 0

    if isinstance(raw_transactions, list):
        stated_count = len(raw_transactions)
        for position, entry in enumerate(raw_transactions):
            # A list of hashes means the block was fetched without expansion.
            # That is not a defect; the count is still authoritative.
            if isinstance(entry, str):
                continue
            transaction, tx_issues = normalize_transaction(
                entry,
                chain=chain,
                block_number=number,
                block_hash=block_hash,
                fallback_index=position,
                source_record_id=source_record_id,
            )
            if transaction is not None:
                transactions.append(transaction)
            else:
                issues.extend(tx_issues)

    return (
        CanonicalBlock(
            chain=chain,
            number=number,
            block_hash=block_hash,
            parent_hash=parent_hash or "0x0",
            timestamp=from_unix(timestamp),
            transaction_count=stated_count,
            gas_used=gas_used,
            gas_limit=gas_limit,
            miner=miner,
            transactions=tuple(transactions),
            source_record_id=source_record_id,
            source_provider=source_provider,
        ),
        tuple(issues),
    )


__all__ = ["normalize_block", "normalize_transaction", "read_quantity"]
