"""
Tools :: Monitoring :: Diagnostics
==================================

Failure diagnosis: root-cause analysis, error categorization, retry
analysis and execution anomalies.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["DiagnosticReport", "DiagnosticEngine", "ERROR_CATEGORIES"]

ERROR_CATEGORIES = ("validation", "connection", "timeout", "execution", "permission", "dependency", "unknown")


@dataclass
class DiagnosticReport:
    """One diagnosed failure."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    subject: str = ""
    category: str = "unknown"
    summary: str = ""
    root_cause: str = ""
    retries: int = 0
    anomalies: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "subject": self.subject,
            "category": self.category,
            "summary": self.summary,
            "root_cause": self.root_cause,
            "retries": self.retries,
            "anomalies": list(self.anomalies),
            "created_at": self.created_at,
        }


def categorize_error(error: BaseException) -> str:
    """Map an exception to a category by type name heuristics."""
    name = type(error).__name__.lower()
    for category in ERROR_CATEGORIES:
        if category in name:
            return category
    return "unknown"


class DiagnosticEngine:
    """Records failures and aggregates diagnostics."""

    def __init__(self) -> None:
        self._reports: List[DiagnosticReport] = []

    def diagnose(
        self,
        error: BaseException,
        *,
        subject: str = "",
        retries: int = 0,
        context: Optional[Mapping[str, Any]] = None,
    ) -> DiagnosticReport:
        category = categorize_error(error)
        report = DiagnosticReport(
            subject=subject,
            category=category,
            summary=str(error),
            root_cause=f"{type(error).__name__}: {error}",
            retries=int(retries),
            anomalies=self._detect_anomalies(subject, retries, category),
        )
        self._reports.append(report)
        return report

    def _detect_anomalies(self, subject: str, retries: int, category: str) -> List[str]:
        anomalies = []
        if retries >= 3:
            anomalies.append("high retry count")
        if category == "timeout":
            anomalies.append("repeated timeouts suggest capacity issue")
        if category == "dependency":
            anomalies.append("dependency failure may cascade")
        return anomalies

    def reports(self, *, category: str = "", subject: str = "", limit: int = 200) -> List[DiagnosticReport]:
        result = self._reports
        if category:
            result = [r for r in result if r.category == category]
        if subject:
            result = [r for r in result if r.subject == subject]
        return list(result[-max(1, int(limit)):])

    def categories(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for report in self._reports:
            counts[report.category] = counts.get(report.category, 0) + 1
        return counts