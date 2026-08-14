"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.dashboard

Purpose:
    Dashboard-style rendering.
"""

from __future__ import annotations

from ..schemas.report import IntelligenceReport


class DashboardRenderer:
    """
    Renders a compact dashboard-style view of a report.
    """

    def render(self, report: IntelligenceReport) -> dict:
        """
        Return a structured dashboard payload.
        """
        return {
            "title": report.title,
            "scores": {s.name: s.value for s in report.scores},
            "summary": report.summary.to_dict() if report.summary else None,
            "evidence_count": len(report.evidence),
            "timeline_count": len(report.timelines),
        }
