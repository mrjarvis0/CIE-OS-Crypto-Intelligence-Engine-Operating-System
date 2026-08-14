"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    normalization.logs

Purpose:
    Turn a captured batch of event logs into canonical token and NFT transfers,
    and report how much of the batch was left undecoded.

Design goals:
    - Decoding delegated to `contracts/`; this layer maps and validates
    - Undecoded logs counted, never silently dropped
    - Block linkage required, so a transfer cannot outlive its block
    - Same refusal discipline as `normalization.evm`
    - Pure: no chain access, no contract calls

Notes:
    This module is thin on purpose. Reading a log is
    :mod:`contracts.events`'s job and it already refuses what it cannot trust;
    the work here is turning what survived into records that storage can hold,
    and being accurate about the remainder.

    **The remainder is the interesting part.** A real Ethereum block emits
    somewhere around a thousand logs, of which a few hundred are transfers and
    the rest are protocol-specific events A01 has no opinion about. Reporting
    only the transfers invites "there were 300 events in this block", which is
    wrong by a factor of three. :class:`TokenActivity` therefore carries the
    denominator.

    **Every transfer is bound to its own block hash**, taken from the log
    rather than from the caller. Storage cascades token transfers from the
    block row, so a reorg withdrawal removes them with the block that carried
    them; binding to height instead would leave a transfer attached to a height
    whose block was abandoned — a movement on a chain that no longer exists,
    indistinguishable from a live one.

    Reading the hash per log also handles a batch that spans heights, and lets
    a caller who knows which block it asked for pass ``expected_hash`` as a
    cross-check. A mismatch there is a provider inconsistency: it answered for
    a block other than the one requested, and the affected logs are refused
    rather than filed under the wrong block.
"""

from __future__ import annotations

import logging

from typing import Any

from config.security.validation import ValidationIssue
from contracts.events import DecodedTransfer, decode_logs
from contracts.signatures import EventKind
from schemas.token import CanonicalNftTransfer, CanonicalTokenTransfer, TokenActivity

logger = logging.getLogger(__name__)


def _height_of(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
        except ValueError:
            return None
    return None


def normalize_logs(
    payload: Any,
    *,
    chain: str,
    expected_hash: str = "",
    block_number: int | None = None,
    source_record_id: str = "",
) -> tuple[TokenActivity | None, tuple[ValidationIssue, ...]]:
    """
    Map a batch of logs onto canonical transfers.

    Each transfer takes its block hash from its own log, so a batch spanning
    heights files each record under the block that emitted it. ``expected_hash``
    is an optional cross-check for a caller that requested one specific block;
    a log disagreeing with it is refused rather than filed under the wrong
    block.

    Returns ``(None, issues)`` only when the batch itself is unusable. An
    individual log that cannot be decoded is counted, not fatal: one
    non-standard contract must not cost the rest of the block.
    """
    if not isinstance(payload, list):
        return None, (
            ValidationIssue(
                field="logs",
                message=f"expected a list, got {type(payload).__name__}",
            ),
        )

    by_index = {
        (str(log.get("transactionHash", "")), _height_of(log.get("logIndex")) or 0): log
        for log in payload
        if isinstance(log, dict)
    }
    decoded, refusals = decode_logs(payload, chain=chain)

    transfers: list[CanonicalTokenTransfer] = []
    nfts: list[CanonicalNftTransfer] = []
    issues: list[ValidationIssue] = []

    skipped_hash_mismatch = 0

    for item in decoded:
        origin = by_index.get((item.tx_hash, item.log_index), {})
        log_hash = str(origin.get("blockHash", "") or "").lower()

        if not log_hash:
            issues.append(
                ValidationIssue(
                    field=f"log[{item.log_index}].blockHash",
                    message="absent; a transfer without block linkage would "
                    "survive a reorg that withdrew its block",
                )
            )
            continue

        if expected_hash and log_hash != expected_hash.lower():
            # The provider answered for a block other than the one requested.
            # Filing this under the requested block would attach a real
            # transfer to the wrong history.
            skipped_hash_mismatch += 1
            continue

        height = block_number if block_number is not None else item.block_number
        try:
            record = _to_canonical(
                item,
                chain=chain,
                block_hash=log_hash,
                block_number=height,
                source_record_id=source_record_id,
            )
        except ValueError as exc:
            # The decoder trusted it; the schema did not. Worth surfacing:
            # it means the two disagree about what a valid record is.
            issues.append(
                ValidationIssue(field=f"log[{item.log_index}]", message=str(exc))
            )
            continue

        if isinstance(record, CanonicalNftTransfer):
            nfts.append(record)
        else:
            transfers.append(record)

    unsupported = sum(1 for r in refusals if r.recognised)

    if skipped_hash_mismatch:
        issues.append(
            ValidationIssue(
                field="blockHash",
                message=(
                    f"{skipped_hash_mismatch} log(s) reported a block other than "
                    f"{expected_hash[:12]}…; the provider answered for the wrong block"
                ),
            )
        )

    activity = TokenActivity(
        chain=chain,
        block_number=block_number if block_number is not None else 0,
        block_hash=expected_hash,
        transfers=tuple(transfers),
        nft_transfers=tuple(nfts),
        undecoded=len(refusals),
        unsupported=unsupported,
        source_record_id=source_record_id,
        quality_notes=_notes(transfers),
    )

    if issues:
        logger.warning(
            "%s block %s: %d decoded log(s) could not be filed",
            chain,
            (expected_hash or "?")[:12],
            len(issues),
        )

    return activity, tuple(issues)


def _to_canonical(
    item: DecodedTransfer,
    *,
    chain: str,
    block_hash: str,
    block_number: int,
    source_record_id: str,
) -> CanonicalTokenTransfer | CanonicalNftTransfer:
    """One decoded transfer as the canonical record for its kind."""
    common = {
        "chain": chain,
        "tx_hash": item.tx_hash,
        "log_index": item.log_index,
        "block_number": block_number,
        "block_hash": block_hash,
        "from_address": item.sender,
        "to_address": item.recipient,
        "is_mint": item.is_mint,
        "is_burn": item.is_burn,
        "source_record_id": source_record_id,
    }

    if item.kind is EventKind.ERC721_TRANSFER:
        return CanonicalNftTransfer(
            collection=item.contract,
            token_id=item.token_id if item.token_id is not None else 0,
            **common,
        )

    if item.amount is None:
        raise ValueError("an ERC-20 transfer arrived without an amount")

    return CanonicalTokenTransfer(
        token=item.contract,
        value=item.amount,
        # Nothing here can establish the exponent, and saying so is the point.
        decimals_known=False,
        **common,
    )


def _notes(transfers: list[CanonicalTokenTransfer]) -> tuple[str, ...]:
    """
    What a consumer must not conclude from these records.

    Follows the pattern in :mod:`normalization.quality`: a limitation that
    travels with the data is a caveat, one recorded elsewhere is a footnote
    nobody reads.
    """
    notes: list[str] = []
    if transfers:
        notes.append(
            "token amounts are raw base units; decimals are unresolved, so "
            "values are comparable within one token and not across tokens"
        )
    return tuple(notes)


__all__ = ["normalize_logs"]
