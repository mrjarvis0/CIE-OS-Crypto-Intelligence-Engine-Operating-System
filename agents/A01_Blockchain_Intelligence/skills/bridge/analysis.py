"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.bridge.analysis

Purpose:
    Report transfers involving labelled bridge addresses over the stored
    window. Attribution comes from the label ledger; without bridge labels
    loaded, the question cannot be asked.

Notes:
    Like exchange_flow, the answer is only as good as the loaded labels.
    Bridge activity cannot be inferred from transfer patterns alone: a
    deposit to a bridge looks identical to any other transfer without knowing
    what the recipient address is.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository, TransferRecord
from schemas.address import Address
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult

DEFAULT_SCAN_LIMIT: Final[int] = 10_000


class BridgeSkill(Skill):
    """
    Transfers involving labelled bridge addresses.

    One responsibility: attribute transfers to bridge operators. Whether the
    flow implies capital flight, arbitrage, or routine bridging is not
    decided here.
    """

    name = "bridge"
    description = "Transfers to/from labelled bridge addresses with operator attribution"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        labels = LabelRepository(analytics.database).label_set(
            request.chain, category="bridge"
        )
        if not labels:
            return self.undetermined(
                coverage,
                "no bridge address labels loaded; bridge activity cannot be "
                "attributed without them",
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

        deposits: list[dict[str, Any]] = []
        withdrawals: list[dict[str, Any]] = []

        for t in transfers:
            to_bridge = t.to_address and labels.is_labelled(t.to_address)
            from_bridge = labels.is_labelled(t.from_address)

            if to_bridge and from_bridge:
                continue
            if to_bridge:
                deposits.append(self._entry(t, labels, "deposit"))
            elif from_bridge:
                withdrawals.append(self._entry(t, labels, "withdrawal"))

        address = request.address
        if address is not None:
            deposits = [
                d for d in deposits if d["counterparty"] == address.value
                or d["bridge_address"] == address.value
            ]
            withdrawals = [
                w for w in withdrawals if w["counterparty"] == address.value
                or w["bridge_address"] == address.value
            ]

        entities: dict[str, int] = {}
        for entry in deposits + withdrawals:
            entity = entry.get("entity", "unknown")
            entities[entity] = entities.get(entity, 0) + 1

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value if address else None,
            "labelled_bridges": len(labels),
            "deposit_count": len(deposits),
            "withdrawal_count": len(withdrawals),
            "entities": entities,
            "deposits": deposits[:20],
            "withdrawals": withdrawals[:20],
            "capped": capped,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "native value only; token bridge transfers are not attributed",
                "attribution depends on loaded bridge labels; unlisted bridges are invisible",
            ],
        }

        subject: dict[str, Any] = {
            "bridge_deposits": len(deposits),
            "bridge_withdrawals": len(withdrawals),
            "bridge_entities": len(entities),
        }
        if address is not None:
            subject["address"] = address.value

        total = len(deposits) + len(withdrawals)
        reason = (
            f"{total} bridge transfer(s) across {len(entities)} operator(s)"
            if total
            else "no bridge activity in the stored window"
        )
        return self.answer(coverage, data, subject, reason)

    @staticmethod
    def _entry(
        t: TransferRecord, labels: Any, direction: str
    ) -> dict[str, Any]:
        if direction == "deposit":
            bridge_addr = t.to_address
            counterparty = t.from_address
        else:
            bridge_addr = t.from_address
            counterparty = t.to_address

        return {
            "direction": direction,
            "bridge_address": bridge_addr,
            "counterparty": counterparty,
            "entity": labels.entity_of(bridge_addr) if bridge_addr else None,
            "value": float(t.value.raw),
            "tx_hash": t.tx_hash,
            "height": t.height,
        }


__all__ = ["BridgeSkill"]
