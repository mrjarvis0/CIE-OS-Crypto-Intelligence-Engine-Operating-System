"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.governance.analysis

Purpose:
    Report governance token holding patterns and interaction with labelled
    governance contracts from stored transfers.

Notes:
    Without governance event decoding (proposals, votes, delegations), this
    skill cannot report voting power or participation. It can report
    governance token flow and interactions with labelled governance contracts.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult


class GovernanceSkill(Skill):
    """
    Governance-related activity from stored transfers and labels.

    One responsibility: report governance token flows and contract interactions.
    Voting power, proposal outcomes, and delegation are not computable without
    governance event decoding.
    """

    name = "governance"
    description = "Governance token flows and labelled governance contract interactions"

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
                coverage, "governance analysis requires an address"
            )

        address = request.address
        contract_labels = LabelRepository(analytics.database).label_set(
            request.chain, category="contract"
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

        governance_interactions = 0
        gov_contracts: dict[str, int] = {}
        for t in addr_transfers:
            counterparty = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if counterparty and contract_labels and contract_labels.is_labelled(counterparty):
                entity = contract_labels.entity_of(counterparty) or counterparty
                if any(
                    kw in entity.lower()
                    for kw in ("gov", "dao", "vote", "timelock", "treasury")
                ):
                    governance_interactions += 1
                    gov_contracts[entity] = gov_contracts.get(entity, 0) + 1

        token_flows = analytics.token_flow(address)

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "contract_labels_loaded": len(contract_labels) > 0,
            "governance_interactions": governance_interactions,
            "governance_contracts": gov_contracts,
            "tokens_touched": len(token_flows),
            "transfers_analyzed": len(addr_transfers),
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no governance event decoding; votes, proposals, and delegations "
                "are not detectable",
                "governance contract identification uses keyword matching on labels; "
                "unlabelled governance contracts are invisible",
                "voting power and participation rate cannot be computed",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "governance_interactions": governance_interactions,
            "governance_contracts": len(gov_contracts),
        }

        reason = (
            f"{governance_interactions} interaction(s) with "
            f"{len(gov_contracts)} governance contract(s)"
            if governance_interactions
            else "no governance activity detected"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["GovernanceSkill"]
