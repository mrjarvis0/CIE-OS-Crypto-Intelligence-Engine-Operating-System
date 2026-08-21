"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.defi.analysis

Purpose:
    Report DeFi protocol interaction from stored transfers, using the
    contract label ledger for protocol identification.

Notes:
    Without protocol-specific adapters, this skill cannot decode swap
    amounts, LP positions, or lending balances. What it can report is
    interaction frequency with labelled DeFi contracts and the diversity
    of protocols touched.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult


class DefiSkill(Skill):
    """
    DeFi protocol interaction from stored transfers and labels.

    One responsibility: report which protocols an address interacted with.
    Position sizes, yields, and risk are not computable without protocol
    adapters.
    """

    name = "defi"
    description = "DeFi protocol interaction frequency from transfer patterns and contract labels"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        if request.address is None:
            return self.undetermined(coverage, "defi analysis requires an address")

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

        protocol_interactions: dict[str, int] = {}
        total_contract_interactions = 0

        for t in addr_transfers:
            counterparty = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if counterparty and contract_labels and contract_labels.is_labelled(counterparty):
                entity = contract_labels.entity_of(counterparty) or counterparty
                protocol_interactions[entity] = protocol_interactions.get(entity, 0) + 1
                total_contract_interactions += 1

        token_flows = analytics.token_flow(address)

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "contract_labels_loaded": len(contract_labels) > 0,
            "protocol_interactions": total_contract_interactions,
            "unique_protocols": len(protocol_interactions),
            "protocols": dict(
                sorted(protocol_interactions.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "tokens_touched": len(token_flows),
            "transfers_analyzed": len(addr_transfers),
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no protocol adapters; swap amounts, LP positions, and yields "
                "are not computable",
                "protocol identification requires contract labels; without them "
                "all interactions look the same",
                "token flows are reported by contract, not by protocol",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "defi_interactions": total_contract_interactions,
            "unique_protocols": len(protocol_interactions),
            "tokens_touched": len(token_flows),
        }

        reason = (
            f"{total_contract_interactions} interaction(s) with "
            f"{len(protocol_interactions)} protocol(s)"
            if total_contract_interactions
            else f"no labelled DeFi interactions in {len(addr_transfers)} transfer(s)"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["DefiSkill"]
