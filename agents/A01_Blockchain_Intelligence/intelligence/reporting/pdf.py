"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.pdf

Purpose:
    PDF report rendering.

    This module provides a structural stub. Actual PDF generation
    should delegate to a dedicated PDF library (e.g. ReportLab) in a
    later phase and must remain deterministic and evidence-accurate.
"""

from __future__ import annotations

from ..schemas.report import IntelligenceReport


class PdfRenderer:
    """
    Renders an intelligence report to a PDF document.
    """

    def render(self, report: IntelligenceReport) -> bytes:
        """
        Return PDF bytes for the report.

        Note:
            Implemented as a placeholder returning UTF-8 Markdown; a real
            PDF backend must be wired in during a later phase.
        """
        from .markdown import MarkdownRenderer

        return MarkdownRenderer().render(report).encode("utf-8")
