"""
Tools :: Governance :: Trust
============================

Trust evaluation: scores, reputation, risk classification and history.

Trust may influence routing decisions; it never grants permissions by
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["TrustScore", "TrustRegistry", "classify_risk"]

_RISK_LEVELS = ("low", "medium", "high", "critical")


def classify_risk(score: float) -> str:
    """Map a 0..1 trust score to a risk level."""
    score = max(0.0, min(1.0, float(score)))
    if score >= 0.8:
        return "low"
    if score >= 0.6:
        return "medium"
    if score >= 0.4:
        return "high"
    return "critical"


@dataclass
class TrustScore:
    """Composite trust for one entity."""

    entity_id: str
    score: float = 0.5
    reputation: float = 0.5
    health_confidence: float = 0.5
    history_len: int = 0

    @property
    def risk(self) -> str:
        return classify_risk(self.score)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "score": self.score,
            "reputation": self.reputation,
            "health_confidence": self.health_confidence,
            "history_len": self.history_len,
            "risk": self.risk,
        }


class TrustRegistry:
    """Trust store with event-driven score adjustment."""

    def __init__(self) -> None:
        self._scores: Dict[str, TrustScore] = {}
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    def get(self, entity_id: str) -> TrustScore:
        score = self._scores.get(entity_id)
        if score is None:
            score = TrustScore(entity_id=entity_id)
            self._scores[entity_id] = score
        return score

    def set(self, score: TrustScore) -> TrustScore:
        self._scores[score.entity_id] = score
        return score

    def adjust(self, entity_id: str, *, delta: float, reason: str) -> TrustScore:
        score = self.get(entity_id)
        score.score = max(0.0, min(1.0, score.score + delta))
        score.history_len += 1
        self._events.setdefault(entity_id, []).append({"delta": delta, "reason": reason, "score": score.score})
        return score

    def record_success(self, entity_id: str) -> TrustScore:
        return self.adjust(entity_id, delta=0.01, reason="success")

    def record_failure(self, entity_id: str) -> TrustScore:
        return self.adjust(entity_id, delta=-0.05, reason="failure")

    def events(self, entity_id: str) -> List[Dict[str, Any]]:
        return list(self._events.get(entity_id, []))

    def all(self) -> List[TrustScore]:
        return list(self._scores.values())