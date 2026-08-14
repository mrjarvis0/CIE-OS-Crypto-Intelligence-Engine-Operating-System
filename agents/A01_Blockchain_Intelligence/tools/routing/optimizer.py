"""
Tools :: Routing :: Optimization
================================

Optimizes routing decisions for latency, cost, quality, reliability and
token usage with configurable multi-objective weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .scorer import RouteCandidate

__all__ = ["OptimizationWeights", "OptimizationResult", "RouteOptimizer"]


@dataclass
class OptimizationWeights:
    """Multi-objective weights; normalized to 1.0."""

    latency: float = 0.20
    cost: float = 0.20
    quality: float = 0.30
    reliability: float = 0.20
    tokens: float = 0.10

    def normalized(self) -> Dict[str, float]:
        total = sum([self.latency, self.cost, self.quality, self.reliability, self.tokens])
        if total <= 0:
            raise ValueError("optimization weights must be positive")
        return {
            "latency": self.latency / total,
            "cost": self.cost / total,
            "quality": self.quality / total,
            "reliability": self.reliability / total,
            "tokens": self.tokens / total,
        }


@dataclass
class OptimizationResult:
    """Optimized ordering of candidates with scores."""

    ranked: List[RouteCandidate] = field(default_factory=list)
    best: Optional[RouteCandidate] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "best": self.best.as_dict() if self.best else None,
            "ranked": [c.as_dict() for c in self.ranked],
        }


class RouteOptimizer:
    """Multi-objective route optimizer."""

    def __init__(self, weights: Optional[OptimizationWeights] = None) -> None:
        self.weights = weights if weights is not None else OptimizationWeights()

    def optimize(self, candidates: Sequence[RouteCandidate]) -> OptimizationResult:
        if not candidates:
            return OptimizationResult(ranked=[], best=None)
        w = self.weights.normalized()
        scored: List[RouteCandidate] = []
        for candidate in candidates:
            s = candidate.signals
            latency = 1.0 - _clamp01(s.get("latency", 0.5))
            cost = 1.0 - _clamp01(s.get("cost", 0.5))
            quality = _clamp01(s.get("capability", 0.5))
            reliability = _clamp01(s.get("success", 0.5)) * 0.5 + _clamp01(s.get("health", 0.5)) * 0.5
            tokens = _clamp01(candidate.meta.get("token_frugality", 0.5))
            total = (
                w["latency"] * (1.0 - latency)
                + w["cost"] * (1.0 - cost)
                + w["quality"] * quality
                + w["reliability"] * reliability
                + w["tokens"] * tokens
            )
            copy = RouteCandidate(
                target_id=candidate.target_id,
                kind=candidate.kind,
                score=round(total, 4),
                signals=dict(candidate.signals),
                meta=dict(candidate.meta),
            )
            scored.append(copy)
        ranked = sorted(scored, key=lambda c: c.score, reverse=True)
        return OptimizationResult(ranked=ranked, best=ranked[0])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))