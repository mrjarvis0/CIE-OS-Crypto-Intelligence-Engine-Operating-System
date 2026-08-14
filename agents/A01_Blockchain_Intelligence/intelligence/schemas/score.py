"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.score

Purpose:
    Canonical scoring data models.

    A Score is a named 0..100 value with a confidence band and an
    optional breakdown into components. ScoreBand describes the
    qualitative interpretation of a score range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ScoreBand(StrEnum):
    """
    Qualitative interpretation bands for a score.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    """
    A single contributing factor to an aggregate score.
    """

    name: str
    value: float
    weight: float = 1.0
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class Score:
    """
    A named 0..100 score with confidence and component breakdown.
    """

    name: str
    value: float
    confidence: float = 1.0
    band: ScoreBand | str = ScoreBand.NONE
    components: tuple[ScoreComponent, ...] = ()
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "band": str(self.band),
            "components": [c.to_dict() for c in self.components],
            "computed_at": self.computed_at.isoformat(),
            "metadata": self.metadata,
        }
