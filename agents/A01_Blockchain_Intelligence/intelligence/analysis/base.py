"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.base

Purpose:
    Shared base for all domain analyzers.

    Each analyzer produces an ``AnalyzerResult``: a subject-derived
    analysis payload plus any evidence artifacts it generated. All
    analyzers must validate and normalize the subject before use and
    back their conclusions with evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ..evidence.builder import EvidenceBuilder
from ..evidence.confidence import ConfidenceEngine
from ..schemas.evidence import ClaimTier, ErrorRate, EvidenceArtifact
from ..utils.normalization import normalize_address


@dataclass(slots=True)
class AnalyzerResult:
    """
    Output of a single domain analyzer.

    Fields:
        analyzer    Name of the producing analyzer.
        data        Structured analysis payload.
        evidence    Evidence artifacts backing the analysis.
        summary     Human-readable one-line summary.
        confidence  Aggregate confidence (0..1) of the analysis.
    """

    analyzer: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceArtifact] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "data": self.data,
            "evidence": [e.to_dict() for e in self.evidence],
            "summary": self.summary,
            "confidence": self.confidence,
        }


class Analyzer(Protocol):
    """
    Protocol every domain analyzer must satisfy.
    """

    name: str

    def analyze(self, subject: dict[str, Any], **kwargs: Any) -> AnalyzerResult:
        ...


class BaseAnalyzer:
    """
    Convenience base providing evidence building and defensive subject
    access. Subclasses set ``name`` and implement :meth:`analyze`.
    """

    name: str = "base"

    def __init__(self) -> None:
        self._evidence_builder = EvidenceBuilder()
        self._confidence_engine = ConfidenceEngine()

    def _result(
        self,
        data: dict[str, Any],
        evidence: list[EvidenceArtifact] | None = None,
        summary: str = "",
        confidence: float | None = None,
    ) -> AnalyzerResult:
        """
        Assemble an analyzer result.

        When ``confidence`` is omitted it is derived from the attached
        evidence through :class:`ConfidenceEngine`, so the result cannot
        disagree with the evidence backing it. A result asserting a
        confidence its own evidence does not support is the exact
        inconsistency the evidence standard exists to prevent -- and it also
        reads as maximally miscalibrated to the evaluation harness.

        Pass an explicit value only when an analyzer has a principled reason
        to differ from the aggregate.
        """
        artifacts = list(evidence or [])
        if confidence is None:
            confidence = (
                self._confidence_engine.score(artifacts) if artifacts else 0.0
            )

        return AnalyzerResult(
            analyzer=self.name,
            data=data,
            evidence=artifacts,
            summary=summary,
            confidence=confidence,
        )

    def _evidence(
        self,
        claim: str,
        data: dict[str, Any],
        source_type: str = "inferred",
        tier: ClaimTier | str = ClaimTier.ATTRIBUTION,
        confidence: float = 0.5,
        reference: str | None = None,
        *,
        error_rate: ErrorRate | None = None,
        derivation: tuple[str, ...] = (),
        expires_at: datetime | None = None,
        completeness: tuple[str, ...] = (),
        method: str | None = None,
    ) -> EvidenceArtifact:
        """
        Build a standard evidence artifact for this analyzer.

        ``confidence`` is a request, not a guarantee: the builder clamps it to
        the tier ceiling and, where the analyzer has not measured its error
        rate, to the unmeasured ceiling. An analyzer that has been backtested
        should pass its measured :class:`ErrorRate` to lift that cap.

        ``method`` defaults to the analyzer name so every artifact records
        what produced it, which the Daubert testability criterion requires.
        """
        return self._evidence_builder.build(
            claim=claim,
            source_type=source_type,
            data=data,
            reference=reference,
            confidence=confidence,
            tier=tier,
            metadata={"analyzer": self.name},
            error_rate=error_rate,
            derivation=derivation,
            expires_at=expires_at,
            completeness=completeness,
            method=method or self.name,
        )

    @staticmethod
    def _get(subject: dict[str, Any], key: str, default: Any = None) -> Any:
        """Defensive subject accessor."""
        if not subject:
            return default
        return subject.get(key, default)

    @staticmethod
    def _address(subject: dict[str, Any], key: str = "address") -> str | None:
        """Normalize an address from the subject, or None."""
        return normalize_address(BaseAnalyzer._get(subject, key))
