"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.token_unlock.analysis

Purpose:
    Report token unlock / vesting-related patterns from stored transfers.
    Without vesting contract state, this detects large periodic outflows
    from a single source — the pattern a vesting contract produces when
    tokens unlock on a schedule.

Notes:
    Real vesting schedule tracking needs the contract's cliff, duration,
    and beneficiary list. This skill detects the execution-layer shadow
    of an unlock: large transfers from the same address at regular intervals.
    The signal is heuristic and stated as such.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository

from ..base import Skill, SkillRequest, SkillResult


class TokenUnlockSkill(Skill):
    """
    Token unlock pattern detection from stored transfers.

    One responsibility: identify periodic large outflow patterns. Whether
    they represent vesting unlocks, OTC deals, or scheduled distributions
    cannot be determined without contract state.
    """

    name = "token_unlock"
    description = "Periodic large outflow detection consistent with vesting unlocks"

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
                coverage, "token_unlock analysis requires an address"
            )

        address = request.address
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

        outflows = [
            t for t in transfers
            if t.from_address == address.value and t.value.raw > 0
        ]

        if len(outflows) < 2:
            data: dict[str, Any] = {
                "chain": request.chain,
                "address": address.value,
                "outflow_count": len(outflows),
                "periodic_pattern": False,
                "coverage_limitation": coverage.limitation,
                "bounds": self._bounds(),
            }
            return self.answer(
                coverage, data,
                {"address": address.value, "unlock_pattern": False},
                f"{len(outflows)} outflow(s), not enough for pattern detection",
            )

        heights = sorted(t.height for t in outflows)
        intervals = [heights[i + 1] - heights[i] for i in range(len(heights) - 1)]

        if intervals:
            mean_interval = sum(intervals) / len(intervals)
            variance = sum((i - mean_interval) ** 2 for i in intervals) / len(intervals)
            cv = (variance ** 0.5 / mean_interval) if mean_interval > 0 else float("inf")
        else:
            mean_interval = 0.0
            cv = float("inf")

        periodic = cv < 0.5 and len(intervals) >= 2

        values = sorted((float(t.value.raw) for t in outflows), reverse=True)
        value_cv = 0.0
        if len(values) >= 2:
            v_mean = sum(values) / len(values)
            if v_mean > 0:
                v_var = sum((v - v_mean) ** 2 for v in values) / len(values)
                value_cv = (v_var ** 0.5) / v_mean

        recipients: dict[str | None, int] = {}
        for t in outflows:
            recipients[t.to_address] = recipients.get(t.to_address, 0) + 1
        concentrated = (
            max(recipients.values()) / len(outflows) > 0.5
            if recipients and outflows
            else False
        )

        data = {
            "chain": request.chain,
            "address": address.value,
            "outflow_count": len(outflows),
            "mean_interval_blocks": round(mean_interval, 1),
            "interval_cv": round(cv, 4),
            "periodic_pattern": periodic,
            "value_cv": round(value_cv, 4),
            "consistent_values": value_cv < 1.0,
            "concentrated_recipient": concentrated,
            "unique_recipients": len(recipients),
            "coverage_limitation": coverage.limitation,
            "bounds": self._bounds(),
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "unlock_pattern": periodic,
            "outflow_count": len(outflows),
            "interval_regularity": round(1.0 - min(cv, 1.0), 4) if cv != float("inf") else 0.0,
        }

        if periodic:
            reason = (
                f"{len(outflows)} outflows at ~{mean_interval:.0f}-block intervals "
                f"(CV {cv:.2f}); pattern consistent with scheduled unlocks"
            )
        else:
            reason = (
                f"{len(outflows)} outflows, intervals too irregular for unlock "
                f"pattern (CV {cv:.2f})"
            )

        return self.answer(coverage, data, subject, reason)

    @staticmethod
    def _bounds() -> list[str]:
        return [
            "no vesting contract state; cliff, duration, and beneficiary list "
            "are unavailable",
            "periodic outflow detection is heuristic; OTC deals and scheduled "
            "distributions produce the same pattern",
            "token unlocks (ERC-20) are not tracked; only native value outflows",
        ]


__all__ = ["TokenUnlockSkill"]
