"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.smart_contract.analysis

Purpose:
    Report contract interaction patterns for an address from stored
    transfers. Without ABI resolution or bytecode analysis, this identifies
    contract creation (transfers to the zero address with no recipient) and
    interaction frequency with labelled contracts.

Notes:
    A "contract" label category exists in the label ledger. When loaded,
    this skill can report which contracts an address interacted with. Without
    labels, it can still detect contract-creation transactions and report
    interaction patterns with unique addresses (though it cannot distinguish
    contracts from EOAs).
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult

DEFAULT_SCAN_LIMIT: Final[int] = 5_000


class SmartContractSkill(Skill):
    """
    Contract interaction patterns from stored transfers.

    One responsibility: describe how an address interacts with contracts.
    Whether the pattern implies a protocol user, a bot, or a developer is
    decided elsewhere.
    """

    name = "smart_contract"
    description = "Contract interaction patterns and creation detection from stored transfers"

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
                coverage, "smart_contract requires an address"
            )

        address = request.address
        contract_labels = LabelRepository(analytics.database).label_set(
            request.chain, category="contract"
        )

        limit = int(request.option("scan_limit", DEFAULT_SCAN_LIMIT))
        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=limit,
        )

        addr_transfers = [
            t for t in transfers
            if address.value in (t.from_address, t.to_address)
        ]

        contract_creations = sum(
            1 for t in addr_transfers
            if t.from_address == address.value and t.to_address is None
        )

        labelled_interactions = 0
        interacted_contracts: dict[str, int] = {}
        for t in addr_transfers:
            counterparty = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if counterparty and contract_labels and contract_labels.is_labelled(counterparty):
                labelled_interactions += 1
                entity = contract_labels.entity_of(counterparty) or counterparty
                interacted_contracts[entity] = interacted_contracts.get(entity, 0) + 1

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "transfers_analyzed": len(addr_transfers),
            "contract_creations": contract_creations,
            "contract_labels_loaded": len(contract_labels) > 0,
            "labelled_contract_interactions": labelled_interactions,
            "unique_contracts": len(interacted_contracts),
            "contract_entities": dict(
                sorted(interacted_contracts.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no ABI resolution or bytecode analysis",
                "contract vs EOA distinction requires labels; without them only "
                "creation transactions (to=null) are detectable",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "contract_creations": contract_creations,
            "labelled_interactions": labelled_interactions,
            "unique_contracts": len(interacted_contracts),
        }

        parts: list[str] = []
        if contract_creations:
            parts.append(f"{contract_creations} contract creation(s)")
        if labelled_interactions:
            parts.append(
                f"{labelled_interactions} interaction(s) with "
                f"{len(interacted_contracts)} labelled contract(s)"
            )
        reason = "; ".join(parts) if parts else (
            f"{len(addr_transfers)} transfer(s), no contract interactions detected"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["SmartContractSkill"]
