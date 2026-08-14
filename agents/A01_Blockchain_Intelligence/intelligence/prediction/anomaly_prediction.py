"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.prediction.anomaly_prediction

Purpose:
    Anomaly likelihood prediction.

    Anomaly probability is horizon-aware (a longer window always has
    at least as much exposure as a shorter one) and clamped to the
    valid probability range [0, 1].
"""

from __future__ import annotations

from typing import Any

from ..schemas.prediction import ForecastPoint, Prediction
from ..utils.helpers import new_id


class AnomalyPredictor:
    """
    Predicts the likelihood of an anomaly in a horizon.
    """

    def predict(
        self,
        subject: dict[str, Any],
        metric: str = "anomaly_probability",
        horizons: list[str] | None = None,
        **_: Any,
    ) -> Prediction:
        """
        Forecast anomaly probability across horizons.

        Each additional horizon step adds exposure, so the probability
        for a longer window is never below that of a shorter one.
        """
        horizons = horizons or ["24h", "7d", "30d"]
        base_probability = float(subject.get("baseline_anomaly_probability", 0.2))
        risk_factor = float(subject.get("risk_factor", 1.0))
        points = []
        for i, horizon in enumerate(horizons, start=1):
            prob = base_probability * risk_factor * (1.0 + 0.2 * (i - 1))
            value = max(0.0, min(1.0, prob))
            points.append(
                ForecastPoint(
                    horizon=horizon,
                    metric=metric,
                    value=value,
                    confidence=0.4,
                )
            )
        return Prediction(
            prediction_id=new_id("pred"),
            subject=subject,
            metric=metric,
            points=tuple(points),
        )
