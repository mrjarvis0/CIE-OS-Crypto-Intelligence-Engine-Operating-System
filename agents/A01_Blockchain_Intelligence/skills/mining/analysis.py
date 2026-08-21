"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.mining.analysis

Purpose:
    Report transfers involving labelled mining pool addresses. Attribution
    comes from the label ledger with category ``mining_pool``.

Notes:
    Mining pool identification cannot be inferred from transfer patterns
    alone. Without loaded labels this skill declines. With them it reports
    which pools received (rewards) or sent (payouts) in the stored window.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult

DEFAULT_SCAN_LIMIT: Final[int] = 10_000


class MiningSkill(Skill):
    """
    Transfers involving labelled mining pool addresses.

    One responsibility: attribute transfers to mining pools. Whether the
    distribution implies centralization is decided elsewhere.
    """

    name = "mining"
    description = "Transfers to/from labelled mining pool addresses"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        labels = LabelRepository(analytics.database).label_set(
            request.chain, category="mining_pool"
        )
        if not labels:
            return self.undetermined(
                coverage,
                "no mining_pool labels loaded; pool activity cannot be attributed",
            )

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        limit = int(request.option("scan_limit", DEFAULT_SCAN_LIMIT))
        transfers, capped = analytics.transfers_by_height(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=limit,
        )

        address = request.address
        pool_inflows: list[dict[str, Any]] = []
        pool_outflows: list[dict[str, Any]] = []
        entities: dict[str, int] = {}

        for t in transfers:
            to_pool = t.to_address and labels.is_labelled(t.to_address)
            from_pool = labels.is_labelled(t.from_address)

            if to_pool and from_pool:
                continue

            if address is not None:
                if address.value not in (t.from_address, t.to_address):
                    continue

            if to_pool:
                entity = labels.entity_of(t.to_address) or "unknown"
                entities[entity] = entities.get(entity, 0) + 1
                pool_inflows.append({
                    "entity": entity,
                    "value": float(t.value.raw),
                    "tx_hash": t.tx_hash,
                    "height": t.height,
                })
            elif from_pool:
                entity = labels.entity_of(t.from_address) or "unknown"
                entities[entity] = entities.get(entity, 0) + 1
                pool_outflows.append({
                    "entity": entity,
                    "value": float(t.value.raw),
                    "tx_hash": t.tx_hash,
                    "height": t.height,
                })

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value if address else None,
            "labelled_pools": len(labels),
            "inflow_count": len(pool_inflows),
            "outflow_count": len(pool_outflows),
            "entities": entities,
            "capped": capped,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "attribution depends on loaded mining_pool labels",
                "native value only; token rewards are not tracked",
            ],
        }

        subject: dict[str, Any] = {
            "mining_inflows": len(pool_inflows),
            "mining_outflows": len(pool_outflows),
            "pool_entities": len(entities),
        }
        if address is not None:
            subject["address"] = address.value

        total = len(pool_inflows) + len(pool_outflows)
        reason = (
            f"{total} mining pool transfer(s) across {len(entities)} pool(s)"
            if total
            else "no mining pool activity in the stored window"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["MiningSkill"]
