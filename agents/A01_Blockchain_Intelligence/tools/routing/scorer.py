"""
Tools :: Routing :: Scorer
==========================

Ranks routing candidates. Weighted signals produce a composite score;
the highest-ranked candidate becomes the preferred route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["RouteCandidate", "ScoringWeights", "RouteScorer"]


@dataclass
class ScoringWeights:
    """Signal weights for candidate ranking (must sum to 1.0)."""

    capability: float = 0.30
    health: float = 0.10
    trust: float = 0.15
    cost: float = 0.10
    latency: float = 0.10
    success: float = 0.15
    resources: float = 0.05
    policy_priority: float = 0.05

    def validate(self) -> None:
        total = sum([self.capability, self.health, self.trust, self.cost, self.latency, self.success, self.resources, self.policy_priority])
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"scoring weights must sum to 1.0, got {total:.4f}")


@dataclass
class RouteCandidate:
    """One candidate execution target with its score."""

    target_id: str
    kind: str = "tool"
    score: float = 0.0
    signals: Dict[str, float] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "kind": self.kind,
            "score": round(self.score, 4),
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
        }


class RouteScorer:
    """Computes composite scores for routing candidates."""

    def __init__(self, weights: Optional[ScoringWeights] = None) -> None:
        self.weights = weights if weights is not None else ScoringWeights()

    def score(self, candidate: Mapping[str, Any]) -> RouteCandidate:
        s = self.weights
        capability = _clamp01(float(candidate.get("capability_match", candidate.get("capability", 1.0))))
        health = _clamp01(float(candidate.get("health", 1.0)))
        trust = _clamp01(float(candidate.get("trust", 0.5)))
        cost = 1.0 - _clamp01(float(candidate.get("cost", 0.0)) / max(1.0, float(candidate.get("max_cost", 1.0))))
        latency = 1.0 - _clamp01(float(candidate.get("latency_ms", 0.0)) / max(1.0, float(candidate.get("max_latency_ms", 1000.0))))
        success = _clamp01(float(candidate.get("success_rate", 0.95)))
        resources = _clamp01(float(candidate.get("resource_available", 1.0)))
        policy_priority = _clamp01(float(candidate.get("policy_priority", 0.5)))

        signals = {
            "capability": capability,
            "health": health,
            "trust": trust,
            "cost": cost,
            "latency": latency,
            "success": success,
            "resources": resources,
            "policy_priority": policy_priority,
        }
        total = (
            s.capability * capability
            + s.health * health
            + s.trust * trust
            + s.cost * cost
            + s.latency * latency
            + s.success * success
            + s.resources * resources
            + s.policy_priority * policy_priority
        )
        return RouteCandidate(
            target_id=str(candidate.get("id", candidate.get("target_id", ""))),
            kind=str(candidate.get("kind", "tool")),
            score=round(total, 4),
            signals=signals,
            meta=dict(candidate),
        )

    def rank(self, candidates: Sequence[Mapping[str, Any]]) -> List[RouteCandidate]:
        return sorted((self.score(c) for c in candidates), key=lambda c: c.score, reverse=True)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))