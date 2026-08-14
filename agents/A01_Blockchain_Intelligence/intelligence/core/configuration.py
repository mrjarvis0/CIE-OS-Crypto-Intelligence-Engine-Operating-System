"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.configuration

Purpose:
    Engine configuration model and defaults.

    Rules:
        - No secrets, no environment-specific values.
        - Values are immutable and safe to import anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from ..utils.constants import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_MAX_EVIDENCE,
    DEFAULT_PIPELINE_TIMEOUT_SECONDS,
)
from ..utils.helpers import clamp


@dataclass(frozen=True, slots=True)
class IntelligenceConfig:
    """
    Immutable configuration for an intelligence engine instance.

    Values are validated at construction time (post-init) so an invalid
    configuration fails fast rather than surfacing deep in a pipeline.
    """

    pipeline_timeout_seconds: float = DEFAULT_PIPELINE_TIMEOUT_SECONDS
    max_evidence_per_claim: int = DEFAULT_MAX_EVIDENCE
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    enabled_stages: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.pipeline_timeout_seconds <= 0:
            raise ValueError("pipeline_timeout_seconds must be positive")
        if self.max_evidence_per_claim < 1:
            raise ValueError("max_evidence_per_claim must be >= 1")
        object.__setattr__(
            self,
            "confidence_threshold",
            clamp(self.confidence_threshold, 0.0, 1.0),
        )

    def with_metadata(self, **metadata: Any) -> "IntelligenceConfig":
        """
        Return a copy of this config merged with the given metadata.
        """
        merged = {**self.metadata, **metadata}
        return IntelligenceConfig(
            pipeline_timeout_seconds=self.pipeline_timeout_seconds,
            max_evidence_per_claim=self.max_evidence_per_claim,
            confidence_threshold=self.confidence_threshold,
            enabled_stages=self.enabled_stages,
            metadata=merged,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to a plain dictionary."""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
        }
