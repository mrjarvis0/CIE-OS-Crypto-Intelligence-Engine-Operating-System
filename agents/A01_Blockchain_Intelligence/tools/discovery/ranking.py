"""
Tools :: Discovery :: Ranking
=============================

Deterministic ranking of candidate tools.

Final score blends the matcher's relevance with trust, usage frequency,
historical success, version stability, latency class, health status and
policy priority. Ties break on name for reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .catalog import DiscoveryEntry
from .matcher import MatchResult

__all__ = ["RankedTool", "Ranker", "DEFAULT_RANK_WEIGHTS"]

DEFAULT_RANK_WEIGHTS: Dict[str, float] = {
    "relevance": 0.45,
    "trust": 0.10,
    "usage": 0.10,
    "success": 0.10,
    "stability": 0.10,
    "latency": 0.05,
    "health": 0.05,
    "policy": 0.05,
}

_LATENCY_SCORES = {"fast": 1.0, "medium": 0.6, "slow": 0.3, "unknown": 0.5}


@dataclass
class RankedTool:
    """A candidate with its final score and factor breakdown."""

    match: MatchResult
    score: float
    factors: Dict[str, float] = field(default_factory=dict)

    @property
    def entry(self) -> DiscoveryEntry:
        return self.match.entry

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.entry.tool_id,
            "name": self.entry.name,
            "namespace": self.entry.namespace,
            "category": self.entry.category,
            "version": self.entry.version,
            "score": self.score,
            "factors": dict(self.factors),
        }


class Ranker:
    """Ranker combining relevance with quality-of-service factors."""

    def __init__(self, weights: Optional[Mapping[str, float]] = None) -> None:
        self.weights = dict(DEFAULT_RANK_WEIGHTS)
        if weights:
            self.weights.update(weights)

    def _factors(self, match: MatchResult) -> Dict[str, float]:
        entry = match.entry
        stability = min(1.0, float(entry.version.count(".")) / 2.0 + 0.5)
        return {
            "relevance": match.score,
            "trust": float(entry.trust_score),
            "usage": float(entry.usage_frequency),
            "success": float(entry.success_rate),
            "stability": stability,
            "latency": _LATENCY_SCORES.get(entry.latency_class, 0.5),
            "health": 1.0 if entry.health_status == "healthy" else 0.3,
            "policy": float(entry.policy_priority),
        }

    def rank(self, matches: Iterable[MatchResult], *, top_k: int = 5) -> List[RankedTool]:
        ranked = []
        for match in matches:
            factors = self._factors(match)
            score = sum(self.weights[key] * factors[key] for key in self.weights if key in factors)
            ranked.append(RankedTool(match=match, score=round(score, 6), factors=factors))
        ranked.sort(key=lambda r: (-r.score, r.entry.name))
        return ranked[: max(0, int(top_k))]