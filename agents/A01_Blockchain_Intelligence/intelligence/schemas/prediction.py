"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.prediction

Purpose:
    Canonical prediction data models.

    A ForecastPoint is a single predicted value at a horizon.
    A Prediction bundles forecast points with a confidence and basis.
    A Scenario is a conditional, alternative future path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """
    A single predicted value at a future horizon.
    """

    horizon: str
    metric: str
    value: float
    confidence: float = 0.5
    lower_bound: float | None = None
    upper_bound: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "metric": self.metric,
            "value": self.value,
            "confidence": self.confidence,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
        }


@dataclass(frozen=True, slots=True)
class Prediction:
    """
    A forecast bundle for a subject and metric.
    """

    prediction_id: str
    subject: dict[str, Any]
    metric: str
    points: tuple[ForecastPoint, ...] = ()
    confidence: float = 0.5
    basis: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "subject": self.subject,
            "metric": self.metric,
            "points": [p.to_dict() for p in self.points],
            "confidence": self.confidence,
            "basis": list(self.basis),
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class Scenario:
    """
    A conditional alternative future path.
    """

    scenario_id: str
    name: str
    probability: float = 0.0
    conditions: tuple[str, ...] = ()
    outcomes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "probability": self.probability,
            "conditions": list(self.conditions),
            "outcomes": self.outcomes,
            "created_at": self.created_at.isoformat(),
        }
