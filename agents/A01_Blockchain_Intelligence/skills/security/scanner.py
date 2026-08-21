"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.security.scanner

Purpose:
    Report security-relevant transfer patterns from stored history:
    interactions with labelled mixers, counterparty concentration that
    suggests a single operator, and high-frequency small transfers that
    suggest dusting or spam.

Notes:
    Without contract bytecode analysis or ABI resolution, this skill cannot
    detect rug pulls or contract vulnerabilities. What it can detect from
    transfer patterns alone is interaction with known bad actors (mixer
    labels) and suspicious volume patterns.

    Approval exposure is a separate case, and the reason is worth stating
    precisely rather than lumping it in with the above. Approval *decoding*
    now exists -- ``blockchain/security/approval_risk`` reads ERC-20,
    ERC-721 and ApprovalForAll grants and replays them into a live set. What
    is missing is capture: no approvals table exists, and
    ``contracts/events.py`` refuses approval logs before they could reach
    one. So this skill still reports nothing about approvals, and the bound
    below says which of the two is the blocker.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from schemas.address import Address
from tiers.ledger import LabelRepository

from ..base import Skill, SkillRequest, SkillResult

DUST_THRESHOLD_WEI: Final[int] = 10**14  # 0.0001 ETH


class SecuritySkill(Skill):
    """
    Security-relevant transfer pattern analysis.

    One responsibility: flag suspicious patterns. Whether they constitute a
    threat is decided in the intelligence layer.
    """

    name = "security"
    description = "Mixer interactions, dust attacks, and suspicious transfer patterns"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        if request.address is None:
            return self.undetermined(coverage, "security scan requires an address")

        address = request.address
        summary = analytics.address_summary(address)

        if not summary.seen:
            return self.answer(
                coverage,
                {"chain": request.chain, "address": address.value, "seen": False},
                {},
                "address not present in stored history",
            )

        mixer_labels = LabelRepository(analytics.database).label_set(
            request.chain, category="mixer"
        )

        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=1_000,
        )

        addr_transfers = [
            t for t in transfers
            if address.value in (t.from_address, t.to_address)
        ]

        mixer_interactions = 0
        dust_transfers = 0
        for t in addr_transfers:
            counterparty = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if counterparty and mixer_labels and mixer_labels.is_labelled(counterparty):
                mixer_interactions += 1
            if t.value.raw > 0 and t.value.raw < DUST_THRESHOLD_WEI:
                dust_transfers += 1

        counterparties: dict[str, int] = {}
        for t in addr_transfers:
            cp = (
                t.to_address if t.from_address == address.value else t.from_address
            )
            if cp:
                counterparties[cp] = counterparties.get(cp, 0) + 1

        top_share = 0.0
        if counterparties and addr_transfers:
            top_share = max(counterparties.values()) / len(addr_transfers)

        flags: list[str] = []
        if mixer_interactions > 0:
            flags.append(f"{mixer_interactions} interaction(s) with labelled mixer(s)")
        if dust_transfers > 3:
            flags.append(f"{dust_transfers} dust-sized transfer(s)")
        if top_share > 0.8 and len(addr_transfers) > 5:
            flags.append(
                f"concentrated counterparty ({top_share:.0%} of transfers to one address)"
            )

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "transaction_count": len(addr_transfers),
            "mixer_interactions": mixer_interactions,
            "mixer_labels_loaded": len(mixer_labels) > 0,
            "dust_transfers": dust_transfers,
            "top_counterparty_share": round(top_share, 4),
            "flags": flags,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no contract bytecode analysis; rug-pull indicators are not detectable",
                (
                    "approval exposure is not screened here: the decoder exists at "
                    "blockchain/security/approval_risk, but no approval log is stored "
                    "-- there is no approvals table and contracts/events.py refuses "
                    "approval logs as non-transfers"
                ),
                "mixer detection depends on loaded mixer labels",
                f"dust threshold is hardcoded at {DUST_THRESHOLD_WEI} wei",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "security_flags": len(flags),
            "mixer_interactions": mixer_interactions,
            "dust_transfers": dust_transfers,
        }

        reason = (
            f"{len(flags)} security flag(s) from {len(addr_transfers)} transfer(s)"
            if flags
            else f"no suspicious patterns in {len(addr_transfers)} transfer(s)"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["SecuritySkill"]
