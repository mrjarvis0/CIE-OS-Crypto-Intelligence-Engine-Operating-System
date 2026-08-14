"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.report

Purpose:
    Canonical report data models.

    An IntelligenceReport aggregates findings, evidence, scores,
    predictions, and an executive summary into a consumable package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceArtifact
from .score import Score
from .timeline import Timeline


@dataclass(frozen=True, slots=True)
class ExecutiveSummary:
    """
    Concise, human-readable overview of an intelligence report.
    """

    headline: str
    key_findings: tuple[str, ...] = ()
    bottom_line: str | None = None
    confidence: float = 0.0
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "key_findings": list(self.key_findings),
            "bottom_line": self.bottom_line,
            "confidence": self.confidence,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class IntelligenceReport:
    """
    A complete, evidence-backed intelligence report.
    """

    title: str
    report_id: str
    subject: dict[str, Any]
    summary: ExecutiveSummary | None = None
    scores: tuple[Score, ...] = ()
    evidence: tuple[EvidenceArtifact, ...] = ()
    timelines: tuple[Timeline, ...] = ()
    sections: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: str = "0.1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "report_id": self.report_id,
            "subject": self.subject,
            "summary": self.summary.to_dict() if self.summary else None,
            "scores": [s.to_dict() for s in self.scores],
            "evidence": [e.to_dict() for e in self.evidence],
            "timelines": [t.to_dict() for t in self.timelines],
            "sections": self.sections,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
            "metadata": self.metadata,
        }
