"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    sensors.envelope

Purpose:
    The container every sensor emits: a raw payload, where it came from, and
    a stable identity for it.

Design goals:
    - Raw payload preserved byte-for-byte in shape; no reshaping, no renaming
    - Provenance attached at capture, never reconstructed later
    - Deterministic identity, so the same observation dedupes across runs
    - "Not determined" distinguishable from "determined to be empty"
    - No network I/O

Notes:
    Provenance has to be attached here or it is lost. Once a payload has been
    handed to normalization it is one dict among many, and any later claim
    about which provider served it is a reconstruction -- which is precisely
    the thing an evidence standard exists to forbid. Capture is the only
    moment the answer is known for certain, so it is recorded here.

    The identity is content-addressed rather than sequential. A sequence
    number identifies a *fetch*; two fetches of block 100 get two numbers and
    dedupe fails. Hashing the payload identifies the *observation*, so the
    same block fetched twice, from two providers, in two processes, collapses
    to one record. That is what makes the pipeline replayable.

    The hash deliberately excludes the provider and the timestamp. Including
    them would make every re-fetch a new record, which is the bug this is
    meant to prevent; the provider that served a given observation belongs in
    provenance, not in its identity.

    ``determined`` mirrors the same discipline as
    :class:`blockchain.rpc.clients.dispatch.CallResult`. A sensor that returns
    an empty payload because the network was unreachable, using the same shape
    it uses for a genuinely empty answer, invites a caller to record a
    confident negative built out of a timeout.
"""

from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

#: Length of the truncated digest used for record ids. 128 bits of a SHA-256
#: is far past collision risk for a per-chain observation stream, and a short
#: id stays readable in logs and evidence citations.
_DIGEST_CHARS: Final[int] = 32


def utc_now() -> datetime:
    return datetime.now(UTC)


class RecordKind(StrEnum):
    """What sort of observation a record carries."""

    #: A chain head height.
    HEAD = "head"
    #: The height the chain reports as finalized.
    FINALIZED_HEAD = "finalized_head"
    #: A full block, with or without expanded transactions.
    BLOCK = "block"
    #: A batch of logs for a height range or filter.
    LOGS = "logs"
    #: A transaction receipt.
    RECEIPT = "receipt"
    #: A balance snapshot — native or token.
    BALANCE = "balance"


def content_id(chain: str, kind: RecordKind | str, payload: Any) -> str:
    """
    Deterministic identity for one observation.

    Built from the chain, the kind, and a canonical JSON rendering of the
    payload with sorted keys, so two structurally identical payloads that
    differ only in key order produce the same id.
    """
    kind_value = kind.value if isinstance(kind, RecordKind) else str(kind)
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str covers most
        canonical = repr(payload)

    digest = hashlib.sha256(f"{chain}|{kind_value}|{canonical}".encode()).hexdigest()
    return f"{kind_value}-{digest[:_DIGEST_CHARS]}"


class CaptureGap(StrEnum):
    """
    Something a capture was asked for and did not obtain.

    The distinction this exists to preserve is the module's own: "not
    determined" must stay distinguishable from "determined to be empty". A
    sensor already refuses to answer an unreachable call with an empty payload.
    A *composite* capture -- a block plus the logs it emitted -- can still lose
    that distinction, because the block arrives determined and complete while
    its logs quietly do not arrive at all.

    Nothing here describes the chain. It describes the capture: the chain may
    well have emitted a hundred transfers in a block whose ``LOGS`` gap is set.
    That is the point -- absence in the record is not absence on the chain.
    """

    #: Event logs were requested for this height and never obtained. Token and
    #: NFT transfers for the block are therefore missing, not zero.
    LOGS = "logs"


@dataclass(frozen=True, slots=True)
class Provenance:
    """
    Where an observation came from.

    Never carries the endpoint URL. A keyed URL holds the credential in its
    path, and these records are written to disk and rendered into reports;
    the provider name is the citable identity.
    """

    provider: str
    chain: str
    method: str
    outcome: str
    from_cache: bool = False
    attempts: int = 0
    observed_at: datetime = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "chain": self.chain,
            "method": self.method,
            "outcome": self.outcome,
            "from_cache": self.from_cache,
            "attempts": self.attempts,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class RawRecord:
    """
    One captured observation, exactly as the provider returned it.

    The payload is not reshaped here. Sensors capture; normalization
    interprets. A sensor that renames ``parentHash`` to ``parent_hash`` has
    already made an interpretive decision, and the layer boundary exists so
    that decision is reviewable in one place instead of seventeen.
    """

    chain: str
    kind: RecordKind
    payload: Any
    provenance: Provenance
    #: Height this record pertains to, when it pertains to one. Used to order
    #: and checkpoint the stream; None for records that are not height-scoped.
    height: int | None = None
    record_id: str = ""
    #: What this capture was asked for and did not get. Empty is the normal
    #: case and means the capture is whole, not merely that nothing was checked.
    #:
    #: Deliberately excluded from ``record_id``, which hashes the payload alone.
    #: Two captures of the same block are the same observation whether or not
    #: one of them also managed to fetch that block's logs, and folding the gap
    #: into the identity would break the dedup this record exists to provide.
    capture_gaps: tuple[CaptureGap, ...] = ()

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("record chain cannot be empty")
        if self.height is not None and self.height < 0:
            raise ValueError("record height must be >= 0")
        if not self.record_id:
            object.__setattr__(
                self, "record_id", content_id(self.chain, self.kind, self.payload)
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "chain": self.chain,
            "kind": self.kind.value,
            "height": self.height,
            "provenance": self.provenance.as_dict(),
            "capture_gaps": [gap.value for gap in self.capture_gaps],
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class SensorResult:
    """
    The outcome of one sensor read.

    ``determined`` is the field that matters, for the same reason it matters
    on ``CallResult``: false means A01 did not learn the answer, which is not
    the same as learning that the answer is empty.
    """

    determined: bool
    record: RawRecord | None = None
    chain: str = ""
    method: str = ""
    #: Machine-readable failure class, taken from the transport outcome.
    outcome: str = ""
    reason: str = ""
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.determined and self.record is not None

    def unwrap(self) -> RawRecord:
        """
        The record, or an error naming why there is none.

        For callers that genuinely cannot proceed without the answer. Anything
        that can degrade should test ``ok`` instead of catching this.
        """
        if self.record is None:
            raise LookupError(
                f"{self.chain or 'chain'} {self.method or 'read'} undetermined: "
                f"{self.reason or self.outcome or 'no reason recorded'}"
            )
        return self.record

    def as_dict(self) -> dict[str, Any]:
        return {
            "determined": self.determined,
            "chain": self.chain,
            "method": self.method,
            "outcome": self.outcome,
            "reason": self.reason,
            "duration_ms": round(self.duration_ms, 2),
            "record": self.record.as_dict() if self.record else None,
        }


__all__ = [
    "CaptureGap",
    "Provenance",
    "RawRecord",
    "RecordKind",
    "SensorResult",
    "content_id",
    "utc_now",
]
