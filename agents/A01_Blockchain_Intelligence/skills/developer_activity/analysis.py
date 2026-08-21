"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.developer_activity.analysis

Purpose:
    Report on-chain developer activity: contract deployment frequency and
    interaction patterns with deployed contracts, from stored transfers.

Notes:
    Without repository sensors (GitHub, GitLab), off-chain development
    activity is invisible. This skill reports the on-chain shadow: contract
    creation transactions (to=null) and their frequency, which indicates
    active deployment behavior.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository

from ..base import Skill, SkillRequest, SkillResult


class DeveloperActivitySkill(Skill):
    """
    On-chain developer activity from contract creation patterns.

    One responsibility: count and characterize contract deployments.
    Code quality, commit frequency, and repository health require off-chain
    sensors that A01 does not have.
    """

    name = "developer_activity"
    description = "Contract deployment frequency and patterns from stored transfers"

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
                coverage, "developer_activity requires an address"
            )

        address = request.address
        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=10_000,
        )

        creations = [
            t for t in transfers
            if t.from_address == address.value and t.to_address is None
        ]

        total_sent = sum(
            1 for t in transfers if t.from_address == address.value
        )

        deployment_heights = sorted(t.height for t in creations)
        if len(deployment_heights) >= 2:
            intervals = [
                deployment_heights[i + 1] - deployment_heights[i]
                for i in range(len(deployment_heights) - 1)
            ]
            mean_interval = sum(intervals) / len(intervals)
        else:
            mean_interval = 0.0

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "contract_deployments": len(creations),
            "total_outbound": total_sent,
            "deployment_ratio": (
                round(len(creations) / total_sent, 4) if total_sent else 0.0
            ),
            "mean_deployment_interval": round(mean_interval, 1),
            "first_deployment_height": deployment_heights[0] if deployment_heights else None,
            "last_deployment_height": deployment_heights[-1] if deployment_heights else None,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no repository sensors; off-chain development activity is invisible",
                "contract creation detected by to=null; factory-deployed contracts "
                "are not attributed to the original developer",
                "contract verification, audit status, and code quality are unavailable",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "contract_deployments": len(creations),
            "deployment_ratio": data["deployment_ratio"],
        }

        reason = (
            f"{len(creations)} contract deployment(s) out of {total_sent} "
            "outbound transfer(s)"
            if creations
            else "no contract deployments detected"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["DeveloperActivitySkill"]
