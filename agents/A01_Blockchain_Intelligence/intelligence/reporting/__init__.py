"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.reporting

Purpose:
    Final intelligence report rendering.

Submodules
----------
report           Report model operations.
executive_summary Executive summary generation.
markdown         Markdown report rendering.
json             JSON report rendering.
pdf              PDF report rendering (stub).
evidence_report  Evidence-focused report rendering.
dashboard        Dashboard-style rendering.
"""

from __future__ import annotations

from .dashboard import DashboardRenderer
from .evidence_report import EvidenceReportRenderer
from .executive_summary import ExecutiveSummaryGenerator
from .json import JsonRenderer
from .markdown import MarkdownRenderer
from .pdf import PdfRenderer
from .report import ReportService

__all__ = [
    "ReportService",
    "ExecutiveSummaryGenerator",
    "MarkdownRenderer",
    "JsonRenderer",
    "PdfRenderer",
    "EvidenceReportRenderer",
    "DashboardRenderer",
]
