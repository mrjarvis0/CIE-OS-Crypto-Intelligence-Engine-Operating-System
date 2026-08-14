"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.linkage

Purpose:
    Extract the three fields that establish chain linkage from a raw block
    payload, so the reorg tracker can be fed without normalization existing.

Design goals:
    - Structural extraction only: number, hash, parent hash
    - Missing or malformed linkage refused, never guessed
    - Works on the provider's payload shape, no canonical schema required
    - No network I/O

Notes:
    This is deliberately not normalization. Normalization decides what a block
    *means* in A01's canonical model -- which fields exist, what they are
    called, how values are typed across chains. This module answers a narrower
    question that ingestion cannot proceed without: which block is this, and
    which block does it claim to follow.

    The distinction matters because linkage is needed *before* a canonical
    schema exists. Reorg detection is the one thing that must work from the
    first block captured, since a reorg missed during early ingestion silently
    poisons everything built on top of it. Waiting for ``normalization/`` to
    land would mean running unprotected until it did.

    Nothing here defaults. A block whose parent hash is absent is not a block
    with parent ``"0x0"``; treating it as one would fabricate linkage to a
    genesis that is not there, and the tracker would report a clean extension
    across a break it should have caught.
"""

from __future__ import annotations

from typing import Any, Final

from blockchain.reorg import BlockRef

from sensors.envelope import RawRecord, RecordKind
from sensors.evm.rpc_sensor import parse_quantity

#: EVM block fields carrying linkage. Named once so a payload-shape change is
#: a one-line edit rather than a hunt through string literals.
_F_NUMBER: Final[str] = "number"
_F_HASH: Final[str] = "hash"
_F_PARENT: Final[str] = "parentHash"


class LinkageError(ValueError):
    """
    Raised when a payload cannot yield trustworthy linkage.

    A ValueError rather than a pipeline exception: this is a statement about
    one payload, not a failure of the ingestion run. The caller decides
    whether to skip the block, try another provider, or stop.
    """


def _text(value: Any) -> str:
    """A non-empty string, or empty if the value is not usable as one."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


def block_ref_from_payload(payload: Any) -> BlockRef:
    """
    Build a :class:`BlockRef` from a raw EVM block payload.

    Raises :class:`LinkageError` when any of the three fields is missing or
    unreadable. Every one is load-bearing: without the number the block cannot
    be placed, without the hash it cannot be identified, and without the parent
    hash a reorg is indistinguishable from ordinary progress.
    """
    if not isinstance(payload, dict):
        raise LinkageError(f"block payload is {type(payload).__name__}, not an object")

    number = parse_quantity(payload.get(_F_NUMBER))
    if number is None:
        raise LinkageError(f"block payload has no readable {_F_NUMBER!r}")

    block_hash = _text(payload.get(_F_HASH))
    if not block_hash:
        raise LinkageError(f"block {number} payload has no {_F_HASH!r}")

    parent_hash = _text(payload.get(_F_PARENT))
    # Genesis is the one block that legitimately has no parent. Above it, an
    # absent parent hash is a defective payload, not a chain start.
    if not parent_hash and number > 0:
        raise LinkageError(f"block {number} payload has no {_F_PARENT!r}")

    return BlockRef(
        number=number,
        hash=block_hash,
        parent_hash=parent_hash or "0x0",
    )


def block_ref_from_record(record: RawRecord) -> BlockRef:
    """
    Build a :class:`BlockRef` from a captured record.

    Cross-checks the height the sensor recorded against the height the payload
    reports. A mismatch means the record is filed under the wrong height, and
    every downstream consumer -- checkpoints, gap detection, backfill ranges --
    keys off that height.
    """
    if record.kind not in {RecordKind.BLOCK, RecordKind.FINALIZED_HEAD}:
        raise LinkageError(
            f"record kind {record.kind.value!r} does not carry block linkage"
        )

    ref = block_ref_from_payload(record.payload)
    if record.height is not None and record.height != ref.number:
        raise LinkageError(
            f"record filed at height {record.height} contains block {ref.number}"
        )
    return ref


def has_linkage(payload: Any) -> bool:
    """Whether a payload would yield linkage, without raising."""
    try:
        block_ref_from_payload(payload)
    except (LinkageError, ValueError):
        return False
    return True


__all__ = [
    "LinkageError",
    "block_ref_from_payload",
    "block_ref_from_record",
    "has_linkage",
]
