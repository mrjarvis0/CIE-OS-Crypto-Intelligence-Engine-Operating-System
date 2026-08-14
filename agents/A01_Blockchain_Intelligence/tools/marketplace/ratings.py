"""
Tools :: Marketplace :: Ratings
===============================

Package reputation: rating scores, download counts, popularity,
reliability and community scores. Ranking may use these signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

__all__ = ["Rating", "RatingsStore"]


@dataclass
class Rating:
    """Aggregated reputation for one package."""

    package_id: str
    score: float = 0.0
    count: int = 0
    downloads: int = 0
    reliability: float = 0.0
    community_score: float = 0.0

    @property
    def popularity(self) -> float:
        return min(1.0, self.downloads / 1000.0)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "score": self.score,
            "count": self.count,
            "downloads": self.downloads,
            "reliability": self.reliability,
            "community_score": self.community_score,
            "popularity": self.popularity,
        }


class RatingsStore:
    """Rating aggregation store."""

    def __init__(self) -> None:
        self._ratings: Dict[str, Rating] = {}

    def get(self, package_id: str) -> Rating:
        rating = self._ratings.get(package_id)
        if rating is None:
            rating = Rating(package_id=package_id)
            self._ratings[package_id] = rating
        return rating

    def rate(self, package_id: str, score: float, *, weight: float = 1.0) -> Rating:
        score = max(0.0, min(5.0, float(score)))
        rating = self.get(package_id)
        rating.count += 1
        rating.score = (rating.score * (rating.count - 1) + score * weight) / (rating.count - 1 + weight) if rating.count > 1 else score
        return rating

    def set_downloads(self, package_id: str, downloads: int) -> Rating:
        rating = self.get(package_id)
        rating.downloads = max(0, int(downloads))
        return rating

    def set_reliability(self, package_id: str, reliability: float) -> Rating:
        rating = self.get(package_id)
        rating.reliability = max(0.0, min(1.0, float(reliability)))
        return rating

    def set_community_score(self, package_id: str, score: float) -> Rating:
        rating = self.get(package_id)
        rating.community_score = max(0.0, min(1.0, float(score)))
        return rating

    def all(self) -> Dict[str, Rating]:
        return dict(self._ratings)

    def top(self, limit: int = 10) -> list[Rating]:
        return sorted(self._ratings.values(), key=lambda r: (r.score, r.downloads), reverse=True)[: max(1, int(limit))]