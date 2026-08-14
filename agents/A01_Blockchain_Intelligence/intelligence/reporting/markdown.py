"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.markdown

Purpose:
    Markdown report rendering.
"""

from __future__ import annotations

from ..schemas.report import IntelligenceReport


class MarkdownRenderer:
    """
    Renders an intelligence report as Markdown.
    """

    def render(self, report: IntelligenceReport) -> str:
        """
        Return a Markdown string for the report.
        """
        lines = [f"# {report.title}", ""]
        if report.summary:
            lines.extend(["## Executive Summary", f"**{report.summary.headline}**", ""])
            if report.summary.key_findings:
                lines.append("Key findings:")
                for finding in report.summary.key_findings:
                    lines.append(f"- {finding}")
                lines.append("")
            if report.summary.bottom_line:
                lines.append(f"**Bottom line:** {report.summary.bottom_line}")
                lines.append("")
            lines.append(f"Confidence: {report.summary.confidence:.0%}")
            lines.append("")
        if report.scores:
            lines.append("## Scores")
            for score in report.scores:
                lines.append(
                    f"- **{score.name}**: {score.value:.0f} ({score.band}) "
                    f"conf={score.confidence:.0%}"
                )
            lines.append("")
        if report.evidence:
            lines.append("## Evidence")
            for artifact in report.evidence:
                lines.append(
                    f"- {artifact.claim} [{artifact.source_type}] "
                    f"tier={artifact.tier} conf={artifact.confidence:.0%}"
                )
            lines.append("")
        if report.timelines:
            lines.append("## Timelines")
            for timeline in report.timelines:
                lines.append(
                    f"- {timeline.subject_id}: {len(timeline.events)} events, "
                    f"{len(timeline.milestones)} milestones"
                )
            lines.append("")
        return "\n".join(lines)
