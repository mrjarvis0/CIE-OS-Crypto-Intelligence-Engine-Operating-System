"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.whale

Purpose:
    Whale score.
"""

from __future__ import annotations

import math
from typing import Any

from ..schemas.score import Score
from .base import clamp, to_band


def _as_eth(value: Any) -> float:
    """
    Coerce a balance/transfer figure to ETH.

    Blockchain tools report raw wei (integers), while callers may
    supply already-converted ETH figures. Values >= 1e10 are treated
    as raw wei; everything else is assumed to be ETH already.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v >= 1e10:
        return v / 1e18
    return v


def _eth_component(eth: float) -> float:
    """
    Log-scaled 0..100 magnitude: 1 ETH ~ 6, 1K ETH ~ 60, 100K ETH ~ 100.
    """
    if eth <= 0:
        return 0.0
    return clamp(20.0 * math.log10(1.0 + eth))


class WhaleScorer:
    """
    Computes a 0..100 whale score from holding/transfer magnitude.
    """

    name = "whale"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        balance = _eth_component(_as_eth(subject.get("balance", 0)))
        largest_transfer = _eth_component(_as_eth(subject.get("largest_transfer", 0)))
        value = clamp(balance * 0.5 + largest_transfer * 0.5)
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=(),
        )
