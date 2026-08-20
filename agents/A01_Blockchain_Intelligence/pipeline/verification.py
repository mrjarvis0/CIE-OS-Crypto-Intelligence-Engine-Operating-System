"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.verification

Purpose:
    Verify and corroborate address labels by cross-referencing independent
    sources, upgrading their verification status and the confidence that
    flows from it.

    A label begins as UNVERIFIED (0.50 confidence). When two independent
    sources agree on the same address *and* entity, the label is
    CORROBORATED (0.75). When an operator publishes the address or
    on-chain proof exists, it is VERIFIED (0.95).

    Every upgrade is recorded with the evidence that justified it, so a
    later reader can see *why* a label carries its status rather than
    having to trust that somebody checked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

from database.connection import Database
from tiers.ledger import (
    CONFIDENCE,
    CORROBORATED,
    UNVERIFIED,
    VERIFIED,
    Label,
    LabelRepository,
    chain_scope,
)

logger = logging.getLogger(__name__)

_STATUS_RANK = {UNVERIFIED: 0, CORROBORATED: 1, VERIFIED: 2}


@dataclass(frozen=True, slots=True)
class VerificationChange:
    """One label whose status was upgraded, and why."""

    chain: str
    address: str
    entity: str
    old_status: str
    new_status: str
    old_confidence: float
    new_confidence: float
    sources: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "address": self.address,
            "entity": self.entity,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "old_confidence": self.old_confidence,
            "new_confidence": self.new_confidence,
            "sources": list(self.sources),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """What a verification scan found and changed."""

    chain: str
    scanned: int = 0
    already_verified: int = 0
    already_corroborated: int = 0
    corroborated: int = 0
    verified: int = 0
    unchanged: int = 0
    changes: tuple[VerificationChange, ...] = ()

    @property
    def upgraded(self) -> int:
        return self.corroborated + self.verified

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "scanned": self.scanned,
            "already_verified": self.already_verified,
            "already_corroborated": self.already_corroborated,
            "corroborated": self.corroborated,
            "verified": self.verified,
            "unchanged": self.unchanged,
            "upgraded": self.upgraded,
            "changes": [c.as_dict() for c in self.changes],
        }


class LabelVerifier:
    """
    Cross-references labels across sources to upgrade verification status.

    Two independent sources agreeing on the same (address, entity) pair is
    corroboration. An operator-published address or on-chain proof is
    verification --- supplied by the caller, not inferred.
    """

    def __init__(self, database: Database) -> None:
        self._db = database
        self._repo = LabelRepository(database)

    def corroborate(self, chain: str, address: str) -> VerificationChange | None:
        """
        Check one address for corroboration and upgrade if justified.

        Two independent sources naming the same entity for the same address
        is corroboration. Returns the change made, or None if no upgrade.
        """
        labels = self._repo.lookup(chain, address)
        if not labels:
            return None

        best = labels[0]
        if _STATUS_RANK.get(best.verification_status, 0) >= _STATUS_RANK[CORROBORATED]:
            return None

        sources_by_entity = _group_sources(labels)
        for entity, sources in sources_by_entity.items():
            if len(sources) >= 2:
                return self._upgrade(
                    chain, address, entity, sources,
                    new_status=CORROBORATED,
                    reason=f"{len(sources)} independent sources agree: {', '.join(sorted(sources))}",
                )
        return None

    def verify(
        self,
        chain: str,
        address: str,
        *,
        evidence: str,
        source: str = "operator",
    ) -> VerificationChange | None:
        """
        Mark an address as verified with explicit evidence.

        This is the manual path: an operator confirms an address through
        direct publication or on-chain proof. The evidence string is
        stored as the reason, so a later reader can check the claim.
        """
        labels = self._repo.lookup(chain, address)
        if not labels:
            return None

        best = labels[0]
        if best.verification_status == VERIFIED:
            return None

        all_sources = tuple(sorted({label.source for label in labels}))
        return self._upgrade(
            chain, address, best.entity or best.label, all_sources,
            new_status=VERIFIED,
            reason=evidence,
        )

    def scan(self, chain: str) -> VerificationReport:
        """
        Batch-corroborate every label on a chain.

        Reads all labels grouped by address, checks each for multiple
        independent sources, and upgrades those that qualify.
        """
        scope = chain_scope(chain)
        placeholders = ", ".join("?" * len(scope))

        rows = self._db.connection.execute(
            f"""
            SELECT address, label, entity, source, confidence,
                   verification_status
              FROM labels
             WHERE chain IN ({placeholders})
             ORDER BY address, confidence DESC
            """,
            scope,
        ).fetchall()

        by_address: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            addr = row["address"]
            by_address.setdefault(addr, []).append(dict(row))

        already_verified = 0
        already_corroborated = 0
        corroborated_count = 0
        unchanged = 0
        changes: list[VerificationChange] = []

        for address, entries in by_address.items():
            best_status = entries[0]["verification_status"]

            if best_status == VERIFIED:
                already_verified += 1
                continue
            if best_status == CORROBORATED:
                already_corroborated += 1
                continue

            sources_by_entity = _group_sources_from_rows(entries)
            upgraded = False
            for entity, sources in sources_by_entity.items():
                if len(sources) >= 2:
                    change = self._upgrade(
                        chain, address, entity, sources,
                        new_status=CORROBORATED,
                        reason=f"{len(sources)} independent sources agree: {', '.join(sorted(sources))}",
                    )
                    if change:
                        changes.append(change)
                        corroborated_count += 1
                        upgraded = True
                    break

            if not upgraded:
                unchanged += 1

        return VerificationReport(
            chain=chain,
            scanned=len(by_address),
            already_verified=already_verified,
            already_corroborated=already_corroborated,
            corroborated=corroborated_count,
            verified=0,
            unchanged=unchanged,
            changes=tuple(changes),
        )

    def status(self, chain: str) -> dict[str, Any]:
        """Summary of verification status across all labels on a chain."""
        scope = chain_scope(chain)
        placeholders = ", ".join("?" * len(scope))

        rows = self._db.connection.execute(
            f"""
            SELECT verification_status, COUNT(DISTINCT address) AS addresses
              FROM labels
             WHERE chain IN ({placeholders})
             GROUP BY verification_status
            """,
            scope,
        ).fetchall()

        counts = {row["verification_status"]: row["addresses"] for row in rows}
        total = sum(counts.values())
        return {
            "chain": chain,
            "total": total,
            "unverified": counts.get(UNVERIFIED, 0),
            "corroborated": counts.get(CORROBORATED, 0),
            "verified": counts.get(VERIFIED, 0),
            "coverage": (
                round((counts.get(CORROBORATED, 0) + counts.get(VERIFIED, 0)) / total, 4)
                if total
                else 0.0
            ),
        }

    def _upgrade(
        self,
        chain: str,
        address: str,
        entity: str,
        sources: tuple[str, ...] | Sequence[str],
        *,
        new_status: str,
        reason: str,
    ) -> VerificationChange | None:
        """Apply a status upgrade to all labels for an address."""
        labels = self._repo.lookup(chain, address)
        if not labels:
            return None

        old_status = labels[0].verification_status
        old_confidence = labels[0].confidence
        new_confidence = CONFIDENCE[new_status]

        with self._db.transaction() as conn:
            scope = chain_scope(chain)
            placeholders = ", ".join("?" * len(scope))
            conn.execute(
                f"""
                UPDATE labels
                   SET verification_status = ?,
                       confidence = ?,
                       last_verified = ?
                 WHERE chain IN ({placeholders})
                   AND address = ?
                """,
                (
                    new_status,
                    new_confidence,
                    datetime.now(UTC).isoformat(),
                    *scope,
                    address,
                ),
            )

        logger.info(
            "label %s on %s upgraded %s -> %s (%.2f -> %.2f): %s",
            address[:12], chain, old_status, new_status,
            old_confidence, new_confidence, reason,
        )

        return VerificationChange(
            chain=chain,
            address=address,
            entity=entity,
            old_status=old_status,
            new_status=new_status,
            old_confidence=old_confidence,
            new_confidence=new_confidence,
            sources=tuple(sorted(sources)),
            reason=reason,
        )


def _group_sources(labels: Sequence[Label]) -> dict[str, tuple[str, ...]]:
    """Group source names by the entity they attribute the address to."""
    by_entity: dict[str, set[str]] = {}
    for label in labels:
        name = label.entity or label.label
        by_entity.setdefault(name, set()).add(label.source)
    return {entity: tuple(sorted(sources)) for entity, sources in by_entity.items()}


def _group_sources_from_rows(rows: Sequence[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Same as _group_sources but from raw row dicts."""
    by_entity: dict[str, set[str]] = {}
    for row in rows:
        name = row.get("entity") or row.get("label", "")
        by_entity.setdefault(name, set()).add(row["source"])
    return {entity: tuple(sorted(sources)) for entity, sources in by_entity.items()}


__all__ = [
    "LabelVerifier",
    "VerificationChange",
    "VerificationReport",
]
