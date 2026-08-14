"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.prediction.market_forecast

Purpose:
    Market forecasting.

    Forecasts price/direction values across horizons. Forecast values
    are floored at zero — a price metric can never go negative.
"""

from __future__ import annotations

from typing import Any

from ..schemas.prediction import ForecastPoint, Prediction
from ..utils.helpers import new_id


class MarketForecaster:
    """
    Forecasts market price/direction.
    """

    def forecast(
        self,
        subject: dict[str, Any],
        metric: str = "price",
        horizons: list[str] | None = None,
        **_: Any,
    ) -> Prediction:
        """
        Forecast market values across horizons.

        Values follow ``price * (1 + drift * step)`` and are clamped to
        non-negative figures.
        """
        horizons = horizons or ["24h", "7d", "30d"]
        price = float(subject.get("price", 0))
        drift = float(subject.get("drift", 0))
        points = []
        for i, horizon in enumerate(horizons, start=1):
            points.append(
                ForecastPoint(
                    horizon=horizon,
                    metric=metric,
                    value=max(0.0, price * (1 + drift * i)),
                    confidence=0.45,
                )
            )
        return Prediction(
            prediction_id=new_id("pred"),
            subject=subject,
            metric=metric,
            points=tuple(points),
        )
