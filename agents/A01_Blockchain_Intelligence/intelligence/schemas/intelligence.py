"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.intelligence

Purpose:
    Canonical intelligence package and pipeline models.

    An IntelligencePackage bundles all outputs of the intelligence
    cycle for a single subject into one transportable unit. The
    IntelligencePipeline describes the ordered stages an investigation
    passes through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .evidence import EvidenceChain
from .report import IntelligenceReport
from .score import Score


class PipelineStage(StrEnum):
    """
    Ordered stage of the intelligence pipeline.
    """

    COLLECT = "collect"
    NORMALIZE = "normalize"
    CORRELATE = "correlate"
    REASON = "reason"
    HYPOTHESIZE = "hypothesize"
    VERIFY = "verify"
    SCORE = "score"
    PREDICT = "predict"
    REPORT = "report"


@dataclass(frozen=True, slots=True)
class IntelligencePipeline:
    """
    Description of an intelligence pipeline execution.
    """

    stages: tuple[PipelineStage | str, ...] = (
        PipelineStage.COLLECT,
        PipelineStage.NORMALIZE,
        PipelineStage.CORRELATE,
        PipelineStage.REASON,
        PipelineStage.HYPOTHESIZE,
        PipelineStage.VERIFY,
        PipelineStage.SCORE,
        PipelineStage.PREDICT,
        PipelineStage.REPORT,
    )
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    stage_timings: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [str(s) for s in self.stages],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "stage_timings": self.stage_timings,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class IntelligencePackage:
    """
    The complete, transportable output of an intelligence investigation.
    """

    package_id: str
    subject: dict[str, Any]
    report: IntelligenceReport | None = None
    evidence_chains: tuple[EvidenceChain, ...] = ()
    scores: tuple[Score, ...] = ()
    pipeline: IntelligencePipeline | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "subject": self.subject,
            "report": self.report.to_dict() if self.report else None,
            "evidence_chains": [c.to_dict() for c in self.evidence_chains],
            "scores": [s.to_dict() for s in self.scores],
            "pipeline": self.pipeline.to_dict() if self.pipeline else None,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }
