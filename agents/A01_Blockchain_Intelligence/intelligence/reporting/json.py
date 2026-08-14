"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.json

Purpose:
    JSON report rendering.
"""

from __future__ import annotations

import json

from ..schemas.report import IntelligenceReport


class JsonRenderer:
    """
    Renders an intelligence report as JSON.
    """

    def render(self, report: IntelligenceReport, indent: int = 2) -> str:
        """
        Return a JSON string for the report.
        """
        return json.dumps(report.to_dict(), indent=indent, default=str)
