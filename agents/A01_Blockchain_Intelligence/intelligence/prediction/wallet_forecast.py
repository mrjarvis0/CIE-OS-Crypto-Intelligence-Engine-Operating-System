"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.prediction.wallet_forecast

Purpose:
    Wallet activity forecasting.
"""

from __future__ import annotations

from typing import Any

from ..schemas.prediction import ForecastPoint, Prediction
from ..utils.helpers import new_id


class WalletForecaster:
    """
    Forecasts future wallet activity levels.
    """

    def forecast(
        self,
        subject: dict[str, Any],
        metric: str = "activity",
        horizons: list[str] | None = None,
        **_: Any,
    ) -> Prediction:
        """
        Forecast wallet activity across horizons.
        """
        horizons = horizons or ["24h", "7d", "30d"]
        base_activity = float(subject.get("average_activity", 0))
        momentum = float(subject.get("activity_momentum", 0))
        points = []
        for i, horizon in enumerate(horizons, start=1):
            value = max(0.0, base_activity + momentum * i)
            points.append(
                ForecastPoint(
                    horizon=horizon,
                    metric=metric,
                    value=value,
                    confidence=0.5,
                )
            )
        return Prediction(
            prediction_id=new_id("pred"),
            subject=subject,
            metric=metric,
            points=tuple(points),
        )
