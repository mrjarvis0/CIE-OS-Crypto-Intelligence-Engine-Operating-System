"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.smart_money

Purpose:
    Smart-money score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score
from .base import clamp, to_band


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SmartMoneyScorer:
    """
    Computes a 0..100 smart-money score from signal quality.
    """

    name = "smart_money"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        profitable_trades = _to_float(subject.get("profitable_trades", 0))
        track_record = _to_float(subject.get("track_record", 0))
        value = clamp(profitable_trades * 10 + track_record * 5)
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
