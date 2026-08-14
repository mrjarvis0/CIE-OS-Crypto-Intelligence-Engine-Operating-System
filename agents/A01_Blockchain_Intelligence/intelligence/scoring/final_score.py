"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.final_score

Purpose:
    Aggregated final score engine.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..schemas.score import Score, ScoreComponent
from .base import clamp, to_band


class FinalScoreEngine:
    """
    Aggregates multiple scores into a single final score.

    The result preserves its component breakdown and reflects the
    confidence of the least-reliable input (conservative bias: an
    aggregate is only as strong as its weakest contributing signal).
    """

    def aggregate(
        self, scores: Iterable[Score], weights: dict[str, float] | None = None
    ) -> Score:
        """
        Combine scores using optional per-name weights (default equal).
        """
        score_list = list(scores)
        if not score_list:
            return Score(name="final", value=0.0, band=to_band(0.0))

        weights = weights or {}
        total_weight = sum(weights.get(s.name, 1.0) for s in score_list) or 1.0
        value = sum(s.value * weights.get(s.name, 1.0) for s in score_list) / total_weight

        components = tuple(
            ScoreComponent(
                name=s.name,
                value=s.value,
                weight=weights.get(s.name, 1.0),
                evidence_refs=tuple(s.metadata.get("evidence_refs", [])),
            )
            for s in score_list
        )
        # Conservative: final confidence = minimum input confidence.
        confidence = min((s.confidence for s in score_list), default=1.0)

        value = clamp(value)
        return Score(
            name="final",
            value=value,
            confidence=confidence,
            band=to_band(value),
            components=components,
        )
