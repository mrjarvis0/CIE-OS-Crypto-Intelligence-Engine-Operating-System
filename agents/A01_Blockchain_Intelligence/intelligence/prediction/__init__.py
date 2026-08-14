"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.prediction

Purpose:
    Future forecasting for wallets, markets, and scenarios.

Submodules
----------
predictor           Central prediction orchestrator.
trend               Trend extrapolation.
anomaly_prediction  Anomaly likelihood prediction.
wallet_forecast     Wallet activity forecasting.
market_forecast     Market forecasting.
scenario            Scenario generation.
"""

from __future__ import annotations

from .anomaly_prediction import AnomalyPredictor
from .market_forecast import MarketForecaster
from .predictor import Predictor
from .scenario import ScenarioGenerator
from .trend import TrendExtrapolator
from .wallet_forecast import WalletForecaster

__all__ = [
    "Predictor",
    "TrendExtrapolator",
    "AnomalyPredictor",
    "WalletForecaster",
    "MarketForecaster",
    "ScenarioGenerator",
]
