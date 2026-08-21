"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.cross_chain.analysis

Purpose:
    Compare stored windows across chains for one address: where it has
    activity, relative volume, and timing.

Notes:
    Real cross-chain correlation needs bridge event matching and timing
    analysis. This skill can only report what the stored windows show for
    the same address on different chains — it is a starting point, not a
    flow trace.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository
from schemas.address import Address

from ..base import Skill, SkillRequest, SkillResult


class CrossChainSkill(Skill):
    """
    Multi-chain presence for one address from stored windows.

    One responsibility: show where the address appears across chains.
    Whether the pattern implies bridging, arbitrage, or multi-chain
    operations is decided elsewhere.
    """

    name = "cross_chain"
    description = "Multi-chain address presence and relative activity from stored windows"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if request.address is None:
            return self.undetermined(coverage, "cross_chain requires an address")

        chains = analytics.chains()
        if not chains:
            return self.undetermined(coverage, "no chain history stored")

        address = request.address
        chain_profiles: list[dict[str, Any]] = []

        for chain in chains:
            chain_addr = Address.parse(address.value, chain)
            window = analytics.window(chain)
            if window.empty:
                continue

            summary = analytics.address_summary(chain_addr)
            if summary.seen:
                chain_profiles.append({
                    "chain": chain,
                    "transaction_count": summary.transaction_count,
                    "sent_count": summary.sent_count,
                    "received_count": summary.received_count,
                    "counterparties": summary.counterparties,
                    "first_height": summary.first_height,
                    "last_height": summary.last_height,
                    "stored_blocks": window.blocks,
                })

        data: dict[str, Any] = {
            "address": address.value,
            "chains_stored": len(chains),
            "chains_with_activity": len(chain_profiles),
            "profiles": chain_profiles,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "same address only; different addresses on different chains cannot be linked",
                "no bridge event matching; cross-chain flows are not traced",
                "relative activity depends on each chain's stored window depth",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "chains_active": len(chain_profiles),
            "chains_stored": len(chains),
        }

        reason = (
            f"active on {len(chain_profiles)} of {len(chains)} stored chain(s)"
            if chain_profiles
            else f"no activity on any of {len(chains)} stored chain(s)"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["CrossChainSkill"]
