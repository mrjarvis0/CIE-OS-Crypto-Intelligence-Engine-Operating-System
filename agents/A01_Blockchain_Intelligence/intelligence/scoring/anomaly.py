"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.scoring.anomaly

Purpose:
    Anomaly score.
"""

from __future__ import annotations

from typing import Any

from ..schemas.score import Score, ScoreComponent
from .base import clamp, to_band


class AnomalyScorer:
    """
    Computes a 0..100 anomaly score from detected deviations.

    Each anomaly is recorded as a component with its severity and
    evidence references, so the contribution of individual deviations is
    auditable.
    """

    name = "anomaly"

    def score(self, subject: dict[str, Any], **_: Any) -> Score:
        anomalies = subject.get("anomalies", [])
        components: list[ScoreComponent] = []
        for idx, a in enumerate(anomalies):
            if isinstance(a, dict):
                label = str(a.get("name", f"anomaly_{idx}"))
                severity = float(a.get("severity", 0.5))
                refs = tuple(a.get("evidence_refs", []))
            else:
                label = str(a)
                severity = 0.5
                refs = ()
            components.append(
                ScoreComponent(
                    name=f"anomaly:{label}",
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
