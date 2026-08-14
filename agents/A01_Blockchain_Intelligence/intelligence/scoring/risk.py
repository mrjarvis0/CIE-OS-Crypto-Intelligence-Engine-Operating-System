"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.risk

Purpose:
    Risk score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score, ScoreComponent
from .base import clamp, to_band


class RiskScorer:
    """
    Computes a 0..100 risk score from risk signals.

    Each signal contributes a named component so analysts can see which
    factor (mixer contact, sanction list, exploit interaction, ...)
    drove the score.
    """

    name = "risk"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        signals = subject.get("risk_signals", [])
        components: list[ScoreComponent] = []
        for idx, signal in enumerate(signals):
            if isinstance(signal, dict):
                label = str(signal.get("name", f"signal_{idx}"))
                severity = float(signal.get("severity", 1.0))
                refs = tuple(signal.get("evidence_refs", []))
            else:
                label = str(signal)
                severity = 1.0
                refs = ()
            components.append(
                ScoreComponent(
                    name=f"risk:{label}",
                    value=clamp(severity * 20.0),
                    weight=1.0,
                    evidence_refs=refs,
                )
            )
        value = clamp(sum(c.value for c in components))
        return Score(
            name=self.name,
            value=value,
            band=to_band(value),
            components=tuple(components),
        )
