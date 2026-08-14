"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.evidence_report

Purpose:
    Evidence-focused report rendering.
"""

from __future__ import annotations

from ..schemas.report import IntelligenceReport


class EvidenceReportRenderer:
    """
    Renders an evidence-centric view of a report.
    """

    def render(self, report: IntelligenceReport) -> str:
        """
        Return a Markdown listing of evidence with confidence.
        """
        lines = ["# Evidence Report", ""]
        for artifact in report.evidence:
            lines.append(
                f"- {artifact.claim} | source={artifact.source_type} "
                f"| confidence={artifact.confidence:.0%} | hash={artifact.content_hash}"
            )
        if not report.evidence:
            lines.append("No evidence recorded.")
        return "\n".join(lines)
