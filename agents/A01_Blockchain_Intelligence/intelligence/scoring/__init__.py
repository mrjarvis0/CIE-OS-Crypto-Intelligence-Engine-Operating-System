"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.scoring

Purpose:
    Decision-layer scoring engines.

    Produces named 0..100 scores (risk, trust, fraud, reputation,
    whale, smart-money, liquidity, influence, anomaly) and an
    aggregated final score, all with qualitative bands.

Submodules
----------
base           Shared band mapping helper.
risk           Risk score.
trust          Trust score.
fraud          Fraud score.
reputation     Reputation score.
whale          Whale score.
smart_money    Smart-money score.
liquidity      Liquidity score.
influence      Influence score.
anomaly        Anomaly score.
final_score    Aggregated final score.
"""

from __future__ import annotations

from .anomaly import AnomalyScorer
from .final_score import FinalScoreEngine
from .fraud import FraudScorer
from .influence import InfluenceScorer
from .liquidity import LiquidityScorer
from .reputation import ReputationScorer
from .risk import RiskScorer
from .smart_money import SmartMoneyScorer
from .trust import TrustScorer
from .whale import WhaleScorer

__all__ = [
    "RiskScorer",
    "TrustScorer",
    "FraudScorer",
    "ReputationScorer",
    "WhaleScorer",
    "SmartMoneyScorer",
    "LiquidityScorer",
    "InfluenceScorer",
    "AnomalyScorer",
    "FinalScoreEngine",
]
