"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.validator.analysis

Purpose:
    Report validator-related patterns from stored execution-layer transfers.
    Without consensus-layer data, this detects interactions with known
    validator-related contracts and withdrawal patterns.

Notes:
    Validator health, attestation performance, and slashing live at the
    consensus layer. This skill can only observe execution-layer effects:
    reward withdrawals, deposit contract interactions, and transfers involving
    labelled validator addresses.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult


class ValidatorSkill(Skill):
    """
    Validator-related activity from execution-layer transfers.

    One responsibility: detect validator-related patterns. Attestation
    performance, uptime, and slashing risk require consensus-layer data
    that A01 does not ingest.
    """

    name = "validator"
    description = "Validator deposit/withdrawal patterns from execution-layer transfers"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        if request.address is None:
            return self.undetermined(
                coverage, "validator analysis requires an address"
            )

        address = request.address
        contract_labels = LabelRepository(analytics.database).label_set(
            request.chain, category="contract"
        )

        summary = analytics.address_summary(address)
        if not summary.seen:
            return self.answer(
                coverage,
                {"chain": request.chain, "address": address.value, "seen": False},
                {},
                "address not present in stored history",
            )

        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=5_000,
        )

        addr_transfers = [
            t for t in transfers
            if address.value in (t.from_address, t.to_address)
        ]

        validator_interactions: dict[str, int] = {}
        for t in addr_transfers:
            counterparty = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if counterparty and contract_labels and contract_labels.is_labelled(counterparty):
                entity = contract_labels.entity_of(counterparty) or counterparty
                if any(
                    kw in entity.lower()
                    for kw in ("validator", "beacon", "deposit", "withdrawal", "consensus")
                ):
                    validator_interactions[entity] = validator_interactions.get(entity, 0) + 1

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "transaction_count": summary.transaction_count,
            "validator_interactions": validator_interactions,
            "contract_labels_loaded": len(contract_labels) > 0,
            "transfers_analyzed": len(addr_transfers),
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no consensus-layer data; attestation performance, uptime, and "
                "slashing are invisible",
                "validator identification uses keyword matching on contract labels",
                "reward amounts cannot be distinguished from regular transfers "
                "without consensus context",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "validator_contract_interactions": sum(validator_interactions.values()),
            "validator_contracts": len(validator_interactions),
        }

        total = sum(validator_interactions.values())
        reason = (
            f"{total} interaction(s) with {len(validator_interactions)} "
            "validator-related contract(s)"
            if total
            else "no validator-related patterns detected"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["ValidatorSkill"]
