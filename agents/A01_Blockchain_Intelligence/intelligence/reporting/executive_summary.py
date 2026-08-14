"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.executive_summary

Purpose:
    Executive summary generation.
"""

from __future__ import annotations

from ..schemas.report import ExecutiveSummary, IntelligenceReport


class ExecutiveSummaryGenerator:
    """
    Builds a concise executive summary from a report.
    """

    def generate(self, report: IntelligenceReport) -> ExecutiveSummary:
        """
        Produce an executive summary from report findings.

        Key findings are the highest-scoring items (descending), so the
        most important finding is listed first regardless of the order
        the scores were supplied in.
        """
        ranked = sorted(report.scores, key=lambda s: s.value, reverse=True)
        top_score = ranked[0] if ranked else None
        return ExecutiveSummary(
            headline=report.title,
            key_findings=tuple(s.name for s in ranked[:3]),
            bottom_line=f"top score: {top_score.name}={top_score.value:.0f}"
            if top_score
            else None,
            confidence=report.summary.confidence if report.summary else 0.0,
        )
