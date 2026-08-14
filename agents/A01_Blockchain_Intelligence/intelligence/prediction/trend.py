"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.prediction.trend

Purpose:
    Trend extrapolation.
"""

from __future__ import annotations

from typing import Any

from ..schemas.prediction import ForecastPoint, Prediction
from ..utils.helpers import new_id


class TrendExtrapolator:
    """
    Extrapolates a simple linear trend into the future.

    Confidence decays with horizon (longer forecasts are less certain)
    and forecast bounds widen proportionally, capturing growing
    uncertainty over time.
    """

    def extrapolate(
        self,
        subject: dict[str, Any],
        metric: str = "price",
        horizons: list[str] | None = None,
        **_: Any,
    ) -> Prediction:
        """
        Produce forecast points along a linear trend.

        Reads ``trend_slope`` (per-step change), ``base_value``, and the
        input ``confidence``. Horizon i adds widening bounds and decaying
        confidence.
        """
        horizons = horizons or ["24h", "7d", "30d"]
        slope = float(subject.get("trend_slope", 0))
        base = float(subject.get("base_value", 0))
        base_confidence = float(subject.get("confidence", 0.5))

        points: list[ForecastPoint] = []
        for i, horizon in enumerate(horizons, start=1):
            value = base + slope * i
            # Confidence decays per step; bounds widen with the horizon.
            confidence = max(0.05, base_confidence * (0.8 ** (i - 1)))
            spread = abs(slope) * i * 0.5 + 0.01
            points.append(
                ForecastPoint(
                    horizon=horizon,
                    metric=metric,
                    value=value,
                    confidence=round(confidence, 4),
                    lower_bound=round(value - spread, 4),
                    upper_bound=round(value + spread, 4),
                )
            )
        return Prediction(
            prediction_id=new_id("pred"),
            subject=subject,
            metric=metric,
            points=tuple(points),
            confidence=round(max(0.05, base_confidence * (0.8 ** (len(horizons) - 1))), 4),
            basis=("linear_trend", "horizon_decay"),
        )
