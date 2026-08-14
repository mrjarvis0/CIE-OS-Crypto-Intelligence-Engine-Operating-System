"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    normalization.normalizer

Purpose:
    Turn a captured raw record into a canonical one, or explain why it cannot
    be turned into one.

Design goals:
    - Validate, map, then assess quality, in that order
    - One result type covering accepted and rejected outcomes
    - Chain dialect chosen from the registry, not guessed from the payload
    - Rejections counted and reported, never swallowed
    - Pure: no network, no storage, no global state

Notes:
    The order matters. Quality is assessed after mapping because a completeness
    judgement needs the canonical record to look at -- how many transactions
    were stated versus captured is not visible in the raw payload without
    duplicating the mapping logic to find out.

    Rejection is a first-class outcome rather than an exception. A run that
    processes ten thousand blocks will meet a handful of bad payloads, and
    raising on each would either abort the run or teach the caller to wrap
    everything in a bare ``except``. Returning them as results keeps the count
    visible, which is what turns "one provider is serving junk" into something
    an operator can see rather than infer.

    The dialect is selected from the chain registry, not sniffed from the
    payload. Sniffing would make a Solana payload that happens to have a
    ``number`` field get parsed as EVM, producing a canonical record that is
    confidently wrong. An unregistered or non-EVM chain is refused by name.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

from config.rpc.chains import ChainType, get_chain, is_supported_chain
from config.security.validation import ValidationIssue
from schemas.block import CanonicalBlock
from schemas.token import TokenActivity
from sensors.envelope import RawRecord, RecordKind

from .evm import normalize_block
from .logs import normalize_logs
from .quality import QualityReport, assess_block

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """
    What normalization made of one raw record.

    ``accepted`` is the field to branch on. A rejected result still carries the
    issues, so a caller can log precisely which field of which provider's
    payload was wrong instead of reporting a count.
    """

    accepted: bool
    record_id: str
    chain: str
    block: CanonicalBlock | None = None
    #: Set for a LOGS record. A result carries a block or an activity, never
    #: both: they come from different RPC calls and are normalized separately.
    activity: TokenActivity | None = None
    quality: QualityReport = field(default_factory=QualityReport)
    issues: tuple[ValidationIssue, ...] = ()
    reason: str = ""

    @property
    def storable(self) -> bool:
        """
        Whether this may be written.

        Per DR-08 only validated data reaches storage. Quality findings do not
        block a write -- they travel with the record so a reader knows what it
        may not conclude from it.
        """
        return self.accepted and (self.block is not None or self.activity is not None)

    @property
    def is_token_activity(self) -> bool:
        return self.activity is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "record_id": self.record_id,
            "chain": self.chain,
            "reason": self.reason,
            "issues": [
                {"field": i.field, "message": i.message} for i in self.issues
            ],
            "quality": self.quality.as_dict(),
            "block": self.block.as_dict() if self.block else None,
            "activity": self.activity.as_dict() if self.activity else None,
        }


@dataclass(slots=True)
class NormalizerStats:
    """Counters for doctor and for noticing a provider gone bad."""

    seen: int = 0
    accepted: int = 0
    rejected: int = 0
    incomplete: int = 0
    implausible: int = 0
    unsupported: int = 0
    token_transfers: int = 0
    nft_transfers: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "seen": self.seen,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "incomplete": self.incomplete,
            "implausible": self.implausible,
            "unsupported": self.unsupported,
            "token_transfers": self.token_transfers,
            "nft_transfers": self.nft_transfers,
        }


class Normalizer:
    """
    Maps raw records to canonical ones for every chain A01 supports.

    Stateless apart from counters, so one instance serves every chain and every
    worker. The chain dialect is looked up per record rather than fixed at
    construction, because a single ingestion run may cover several chains.
    """

    def __init__(self) -> None:
        self.stats = NormalizerStats()

    def normalize(self, record: RawRecord) -> NormalizationResult:
        """Map one captured record, or explain the refusal."""
        self.stats.seen += 1

        if record.kind is RecordKind.LOGS:
            return self._normalize_logs(record)

        if record.kind not in {RecordKind.BLOCK, RecordKind.FINALIZED_HEAD}:
            self.stats.unsupported += 1
            return self._reject(
                record,
                f"no canonical mapping for record kind {record.kind.value!r}",
            )

        if not is_supported_chain(record.chain):
            self.stats.unsupported += 1
            return self._reject(record, f"chain {record.chain!r} is not registered")

        chain_type = get_chain(record.chain).chain_type
        if chain_type is not ChainType.EVM:
            # Named rather than sniffed: an EVM parse of a Solana payload would
            # produce a canonical record that is confidently wrong.
            self.stats.unsupported += 1
            return self._reject(
                record,
                f"{record.chain} is {chain_type.value}; no normalizer for that dialect",
            )

        block, issues = normalize_block(
            record.payload,
            chain=record.chain,
            source_record_id=record.record_id,
            source_provider=record.provenance.provider,
        )

        if block is None:
            self.stats.rejected += 1
            logger.warning(
                "%s: rejected record %s from %s (%d issue(s))",
                record.chain,
                record.record_id,
                record.provenance.provider,
                len(issues),
            )
            return NormalizationResult(
                accepted=False,
                record_id=record.record_id,
                chain=record.chain,
                issues=issues,
                reason="payload failed validation",
            )

        quality = assess_block(block, capture_gaps=record.capture_gaps)
        self.stats.accepted += 1
        if not quality.complete:
            self.stats.incomplete += 1
        if not quality.plausible:
            self.stats.implausible += 1

        return NormalizationResult(
            accepted=True,
            record_id=record.record_id,
            chain=record.chain,
            block=block,
            quality=quality,
            # Partial transaction failures are reported alongside an accepted
            # block: the header is trustworthy even when some bodies were not.
            issues=issues,
        )

    def _normalize_logs(self, record: RawRecord) -> NormalizationResult:
        """
        Map a captured log batch onto canonical token movements.

        Each transfer binds to the block hash carried in its own log, so a
        batch spanning heights files each record under the block that emitted
        it — which is what lets a reorg withdrawal cascade them away.
        """
        if not is_supported_chain(record.chain):
            self.stats.unsupported += 1
            return self._reject(record, f"chain {record.chain!r} is not registered")

        # No expected hash is passed: each transfer takes the block hash from
        # its own log, which is what binds it to the block that emitted it. A
        # caller wanting the cross-check calls normalize_logs directly.
        activity, issues = normalize_logs(
            record.payload,
            chain=record.chain,
            block_number=record.height,
            source_record_id=record.record_id,
        )

        if activity is None:
            self.stats.rejected += 1
            return NormalizationResult(
                accepted=False,
                record_id=record.record_id,
                chain=record.chain,
                issues=issues,
                reason="log batch failed validation",
            )

        self.stats.accepted += 1
        self.stats.token_transfers += len(activity.transfers)
        self.stats.nft_transfers += len(activity.nft_transfers)

        return NormalizationResult(
            accepted=True,
            record_id=record.record_id,
            chain=record.chain,
            activity=activity,
            issues=issues,
        )

    def normalize_all(
        self, records: list[RawRecord]
    ) -> tuple[list[NormalizationResult], list[NormalizationResult]]:
        """
        Map a batch, split into accepted and rejected.

        Splitting rather than filtering keeps the rejections in the caller's
        hands. A batch writer that silently drops them makes a provider serving
        junk look like a chain with no activity.
        """
        accepted: list[NormalizationResult] = []
        rejected: list[NormalizationResult] = []
        for record in records:
            result = self.normalize(record)
            (accepted if result.storable else rejected).append(result)
        return accepted, rejected

    def _reject(self, record: RawRecord, reason: str) -> NormalizationResult:
        return NormalizationResult(
            accepted=False,
            record_id=record.record_id,
            chain=record.chain,
            reason=reason,
        )

    def health(self) -> dict[str, Any]:
        return {"normalizer": "evm", "stats": self.stats.as_dict()}

    def __repr__(self) -> str:
        return f"Normalizer(seen={self.stats.seen}, accepted={self.stats.accepted})"


__all__ = ["NormalizationResult", "Normalizer", "NormalizerStats"]
