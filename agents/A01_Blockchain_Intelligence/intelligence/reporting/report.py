"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.report

Purpose:
    Report model operations.
"""

from __future__ import annotations

from ..schemas.report import IntelligenceReport
from ..utils.helpers import new_id


class ReportService:
    """
    High-level operations over IntelligenceReport models.
    """

    def create(self, title: str, subject: dict) -> IntelligenceReport:
        """
        Create a new, empty report.
        """
        return IntelligenceReport(
            title=title,
            report_id=new_id("report"),
            subject=subject,
        )

    def summarize(self, report: IntelligenceReport) -> dict:
        """
        Return a lightweight summary of a report.
        """
        return {
            "report_id": report.report_id,
            "title": report.title,
            "score_count": len(report.scores),
            "evidence_count": len(report.evidence),
            "timeline_count": len(report.timelines),
        }
