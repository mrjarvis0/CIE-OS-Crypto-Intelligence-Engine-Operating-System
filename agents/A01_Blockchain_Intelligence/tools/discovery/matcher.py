"""
Tools :: Discovery :: Matcher
=============================

Matches user intent against tool capabilities.

Scored dimensions: name, description, tags, categories, capabilities,
parameters, supported inputs/outputs and search hints. Supports exact,
fuzzy (difflib ratio), prefix and capability matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .catalog import DiscoveryEntry

__all__ = ["MatchResult", "Matcher", "WEIGHTS"]

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "name": 0.30,
    "description": 0.20,
    "tags": 0.15,
    "capabilities": 0.20,
    "category": 0.05,
    "namespace": 0.05,
    "inputs": 0.05,
}
WEIGHTS = dict(_DEFAULT_WEIGHTS)


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


@dataclass
class MatchResult:
    """A scored match between a query and one entry."""

    entry: DiscoveryEntry
    score: float
    breakdown: Dict[str, float] = field(default_factory=dict)
    matched_terms: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.entry.tool_id,
            "name": self.entry.name,
            "score": self.score,
            "breakdown": dict(self.breakdown),
            "matched_terms": list(self.matched_terms),
        }


class Matcher:
    """Dimension-weighted intent-to-capability matcher."""

    def __init__(self, weights: Optional[Mapping[str, float]] = None) -> None:
        self.weights = dict(_DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)

    # -- per-dimension scorers -------------------------------------------------- #

    def _score_name(self, entry: DiscoveryEntry, query: str, q_tokens: Sequence[str]) -> float:
        name = entry.name.lower()
        query_l = query.lower()
        if name == query_l:
            return 1.0
        if name.startswith(query_l) or query_l in name:
            return 0.8
        if any(t in name for t in q_tokens):
            return 0.6
        return _ratio(name, query_l)

    def _score_description(self, entry: DiscoveryEntry, q_tokens: Sequence[str]) -> float:
        text = entry.description.lower()
        if not text:
            return 0.0
        hits = sum(1 for t in q_tokens if t in text)
        return min(1.0, hits / max(1, len(q_tokens)) * 1.0)

    def _score_tags(self, entry: DiscoveryEntry, q_tokens: Sequence[str]) -> float:
        tags = {t.lower() for t in entry.tags}
        if not tags:
            return 0.0
        hits = sum(1 for t in q_tokens if t in tags)
        return min(1.0, hits / max(1, len(q_tokens)) * 1.2)

    def _score_capabilities(self, entry: DiscoveryEntry, q_tokens: Sequence[str]) -> float:
        caps = {c.lower() for c in entry.capabilities}
        if not caps:
            return 0.0
        hits = sum(1 for t in q_tokens if t in caps or any(c.startswith(t) for c in caps))
        return min(1.0, hits / max(1, len(q_tokens)) * 1.4)

    def _score_category(self, entry: DiscoveryEntry, query: str) -> float:
        category = entry.category.lower()
        query_l = query.lower()
        if category == query_l or query_l in category:
            return 1.0
        return 0.0

    def _score_namespace(self, entry: DiscoveryEntry, namespace: str) -> float:
        if not namespace:
            return 1.0
        return 1.0 if entry.namespace == namespace else 0.0

    def _score_inputs(self, entry: DiscoveryEntry, q_tokens: Sequence[str]) -> float:
        inputs = {i.lower() for i in entry.supported_inputs}
        if not inputs:
            return 0.0
        hits = sum(1 for t in q_tokens if t in inputs)
        return min(1.0, hits / max(1, len(q_tokens)))

    # -- public ---------------------------------------------------------------- #

    def match(self, entry: DiscoveryEntry, query: str, *, namespace: str = "") -> MatchResult:
        query = (query or "").strip()
        q_tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 2]
        breakdown = {
            "name": self._score_name(entry, query, q_tokens),
            "description": self._score_description(entry, q_tokens),
            "tags": self._score_tags(entry, q_tokens),
            "capabilities": self._score_capabilities(entry, q_tokens),
            "category": self._score_category(entry, query),
            "namespace": self._score_namespace(entry, namespace),
            "inputs": self._score_inputs(entry, q_tokens),
        }
        score = sum(breakdown[dim] * self.weights[dim] for dim in self.weights)
        matched = [t for t in q_tokens if t in entry.name.lower() or t in {c.lower() for c in entry.capabilities}]
        return MatchResult(entry=entry, score=round(score, 6), breakdown=breakdown, matched_terms=matched)

    def matches(self, entries: Iterable[DiscoveryEntry], query: str, *, namespace: str = "") -> List[MatchResult]:
        return [self.match(entry, query, namespace=namespace) for entry in entries]