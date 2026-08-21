"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.staking.analysis

Purpose:
    Report staking-related transfer patterns from stored history. Without
    consensus-layer data, this detects large transfers to/from known staking
    contract addresses (if labelled) and reports flow patterns consistent
    with staking behavior.

Notes:
    Staking on PoS chains happens at the consensus layer, which A01 does
    not ingest. This skill can only observe execution-layer transfers that
    may represent staking deposits (e.g., 32 ETH to the beacon deposit
    contract) or staking rewards withdrawals. The signal is weak without
    consensus data and this is stated in every result.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult

ETH_DEPOSIT_CONTRACT: Final[str] = "0x00000000219ab540356cbb839cbe05303d7705fa"
STAKE_AMOUNT_32_ETH: Final[int] = 32 * 10**18


class StakingSkill(Skill):
    """
    Staking-related transfer pattern detection.

    One responsibility: identify transfers consistent with staking behavior.
    Actual stake state, rewards, and slashing are at the consensus layer
    which A01 does not ingest.
    """

    name = "staking"
    description = "Staking deposit/withdrawal detection from execution-layer transfers"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        if request.address is None:
            return self.undetermined(coverage, "staking analysis requires an address")

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

        deposit_contract_transfers = 0
        staking_sized_transfers = 0
        staking_interactions: dict[str, int] = {}

        for t in addr_transfers:
            if (
                t.to_address
                and t.to_address.lower() == ETH_DEPOSIT_CONTRACT
                and t.from_address == address.value
            ):
                deposit_contract_transfers += 1

            if t.value.raw == STAKE_AMOUNT_32_ETH:
                staking_sized_transfers += 1

            counterparty = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if counterparty and contract_labels and contract_labels.is_labelled(counterparty):
                entity = contract_labels.entity_of(counterparty) or counterparty
                if any(kw in entity.lower() for kw in ("stake", "deposit", "beacon", "lido", "rocket")):
                    staking_interactions[entity] = staking_interactions.get(entity, 0) + 1

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "deposit_contract_transfers": deposit_contract_transfers,
            "staking_sized_transfers": staking_sized_transfers,
            "staking_interactions": staking_interactions,
            "transfers_analyzed": len(addr_transfers),
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no consensus-layer data; actual stake state, rewards, and "
                "slashing are invisible",
                "staking detection is heuristic: 32 ETH transfers and known "
                "contract interactions",
                "liquid staking (Lido, Rocket Pool) requires contract labels",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "deposit_contract_transfers": deposit_contract_transfers,
            "staking_sized_transfers": staking_sized_transfers,
            "staking_contract_interactions": sum(staking_interactions.values()),
        }

        signals = deposit_contract_transfers + len(staking_interactions)
        reason = (
            f"{deposit_contract_transfers} deposit contract transfer(s), "
            f"{len(staking_interactions)} staking contract(s) touched"
            if signals
            else "no staking-related patterns detected"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["StakingSkill"]
