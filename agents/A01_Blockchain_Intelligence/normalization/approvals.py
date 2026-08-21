"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    normalization.approvals

Purpose:
    Turn a captured batch of event logs into stored-ready approval records,
    binding each to the block that emitted it.

Design goals:
    - Decoding delegated to ``blockchain.security.approval_risk``; this layer
      maps, binds to a block, and counts the remainder
    - Undecoded approvals counted, never silently dropped
    - Block linkage required, so an approval cannot outlive its block
    - Same refusal discipline as :mod:`normalization.logs`
    - Pure: no chain access, no contract calls

Notes:
    This module is the sibling of :mod:`normalization.logs`. A block's log
    batch carries transfers and approvals side by side; ``normalize_logs``
    files the transfers and counts the approvals as undecoded, and this files
    the approvals. Running both over the same payload is deliberate -- the two
    are different facts with different shapes, and folding an approval into
    transfer flow inflates every total it touches.

    **Every approval is bound to its own block hash**, taken from the log
    rather than from the caller. Storage cascades approvals from the block row,
    so a reorg withdrawal removes them with the block that carried them; binding
    to height instead would leave a grant attached to a height whose block was
    abandoned -- a live-looking approval on a chain that no longer exists.

    A decoded approval that arrives without a readable block hash is refused
    rather than stored under a guessed one, for the same reason
    ``normalize_logs`` refuses a transfer without linkage: a grant that survives
    a reorg it should not is worse than one that was never filed.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from typing import Any

from blockchain.security.approval_risk import DecodedApproval, decode_approvals
from config.security.validation import ValidationIssue

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


@dataclass(frozen=True, slots=True)
class StoredApproval:
    """
    One decoded approval and the block hash that binds it to storage.

    The decoder reads a grant's fields but not its block hash -- a log carries
    the hash in ``blockHash``, which is metadata about where the log sits, not
    part of the event. This pairs the two so a repository has the linkage it
    needs to cascade the grant away when its block is withdrawn.
    """

    approval: DecodedApproval
    block_hash: str


@dataclass(frozen=True, slots=True)
class ApprovalActivity:
    """
    What a log batch held in the way of approvals, ready to store.

    ``undecoded`` counts approval-shaped logs that could not be read, not every
    non-approval log in the batch. A rising count for one contract is the same
    signal a rising transfer-refusal rate is: a non-standard implementation, or
    occasionally something shaped to confuse a decoder.
    """

    chain: str
    approvals: tuple[StoredApproval, ...] = ()
    undecoded: int = 0
    source_record_id: str = ""

    @property
    def empty(self) -> bool:
        return not self.approvals

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "approvals": len(self.approvals),
            "undecoded": self.undecoded,
            "source_record_id": self.source_record_id,
        }


def normalize_approvals(
    payload: Any,
    *,
    chain: str,
    source_record_id: str = "",
) -> tuple[ApprovalActivity | None, tuple[ValidationIssue, ...]]:
    """
    Map a batch of logs onto stored-ready approvals.

    Each approval takes its block hash from its own log, so a batch spanning
    heights files each grant under the block that emitted it -- which is what
    lets a reorg withdrawal cascade them away.

    Returns ``(None, issues)`` only when the batch itself is unusable. An
    individual approval that cannot be read, or one with no block linkage, is
    counted or refused without costing the rest of the batch.
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
    decoded, refusals = decode_approvals(payload, chain=chain)

    records: list[StoredApproval] = []
    issues: list[ValidationIssue] = []

    for approval in decoded:
        origin = by_index.get(
            (approval.tx_hash, approval.log_index if approval.log_index is not None else 0),
            {},
        )
        block_hash = str(origin.get("blockHash", "") or "").lower()

        if not block_hash:
            issues.append(
                ValidationIssue(
                    field=f"log[{approval.log_index}].blockHash",
                    message="absent; an approval without block linkage would "
                    "survive a reorg that withdrew its block",
                )
            )
            continue

        records.append(StoredApproval(approval=approval, block_hash=block_hash))

    # Only approval-shaped logs that failed to decode, not every non-approval
    # log the batch carried: ``recognised`` is the decoder's own distinction
    # between a malformed approval and a log that is not an approval at all.
    undecoded = sum(1 for refusal in refusals if refusal.recognised)

    activity = ApprovalActivity(
        chain=chain,
        approvals=tuple(records),
        undecoded=undecoded,
        source_record_id=source_record_id,
    )

    if issues:
        logger.warning(
            "%s: %d decoded approval(s) could not be filed to a block",
            chain,
            len(issues),
        )

    return activity, tuple(issues)


__all__ = ["ApprovalActivity", "StoredApproval", "normalize_approvals"]
