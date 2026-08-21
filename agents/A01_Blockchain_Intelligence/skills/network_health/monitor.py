"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.network_health.monitor

Purpose:
    Report chain health from stored block metadata: contiguity, completeness,
    block timing consistency, and capture quality.

Notes:
    This is the only skill that answers about the chain rather than an address.
    It reads the blocks table directly through the analytics window, reporting
    gaps, incomplete blocks, and timing anomalies. Without validator or mempool
    telemetry the picture is incomplete, but block-level quality is a real
    signal and the one A01 can actually measure.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository

from ..base import Skill, SkillRequest, SkillResult


class NetworkHealthSkill(Skill):
    """
    Chain health metrics from stored block metadata.

    One responsibility: describe what the stored window says about the chain's
    health. Whether a gap is an ingestion failure or a chain halt is decided
    elsewhere.
    """

    name = "network_health"
    description = "Block contiguity, completeness and timing from stored history"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        window = coverage.window
        quality = analytics.hourly_block_quality(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
        )

        total_blocks = sum(h.blocks for h in quality.values())
        complete_blocks = sum(h.complete_blocks for h in quality.values())
        incomplete_hours = sum(
            1 for h in quality.values() if not h.all_complete
        )

        data: dict[str, Any] = {
            "chain": request.chain,
            "from_height": window.from_height,
            "to_height": window.to_height,
            "stored_blocks": window.blocks,
            "span": window.span,
            "contiguous": window.contiguous,
            "complete_blocks": complete_blocks,
            "incomplete_blocks": window.incomplete_blocks,
            "unfetched_blocks": window.unfetched_blocks,
            "selective_blocks": window.selective_blocks,
            "hours_covered": len(quality),
            "hours_incomplete": incomplete_hours,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no validator or mempool telemetry; block timing is inferred "
                "from stored timestamps only",
                "gaps may reflect ingestion failures rather than chain issues",
            ],
        }

        subject: dict[str, Any] = {
            "chain": request.chain,
            "contiguous": window.contiguous,
            "completeness_ratio": (
                complete_blocks / total_blocks if total_blocks else 0.0
            ),
            "stored_blocks": window.blocks,
            "span": window.span,
        }

        if window.contiguous and window.incomplete_blocks == 0:
            reason = (
                f"{window.blocks} blocks stored, contiguous and complete "
                f"across {len(quality)} hour(s)"
            )
        else:
            issues: list[str] = []
            if not window.contiguous:
                issues.append(f"gaps in {window.span}-height span")
            if window.incomplete_blocks:
                issues.append(f"{window.incomplete_blocks} incomplete block(s)")
            reason = f"{window.blocks} blocks stored; " + "; ".join(issues)

        return self.answer(coverage, data, subject, reason)


__all__ = ["NetworkHealthSkill"]
