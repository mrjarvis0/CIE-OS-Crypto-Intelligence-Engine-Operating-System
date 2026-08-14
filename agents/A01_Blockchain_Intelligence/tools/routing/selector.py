"""
Tools :: Routing :: Selector
============================

Selects execution targets: tools, agents, adapters, plugins, MCP
servers, AI models, blockchain RPCs and workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["Selector", "SelectionResult"]

TARGET_KINDS = ["tool", "agent", "adapter", "plugin", "mcp", "model", "rpc", "workflow"]


@dataclass
class SelectionResult:
    """Outcome of a selection pass."""

    selected: Optional[Dict[str, Any]] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "selected": self.selected,
            "candidates": list(self.candidates),
            "reason": self.reason,
        }


class Selector:
    """Picks the best execution target for a request from a pool."""

    def __init__(self) -> None:
        self._pool: List[Dict[str, Any]] = []

    def register(self, target: Mapping[str, Any]) -> None:
        entry = dict(target)
        if "id" not in entry:
            raise ValueError("target requires an 'id'")
        entry.setdefault("kind", "tool")
        self._pool.append(entry)

    def register_many(self, targets: Sequence[Mapping[str, Any]]) -> None:
        for target in targets:
            self.register(target)

    def pool(self, kind: str = "") -> List[Dict[str, Any]]:
        if not kind:
            return list(self._pool)
        return [t for t in self._pool if t.get("kind") == kind]

    def select(
        self,
        request: str = "",
        *,
        kind: str = "",
        capability: str = "",
        top_k: int = 1,
        min_score: float = 0.0,
    ) -> SelectionResult:
        """Select the best target(s). Scores come from the routing scorer;
        targets without a score default to a lexical match."""

        query = request.lower()
        scored: List[Dict[str, Any]] = []
        for target in self._pool:
            if kind and target.get("kind") != kind:
                continue
            if capability and capability not in target.get("capabilities", []):
                continue
            raw_score = float(target.get("score", 0.0))
            if not raw_score and query:
                raw_score = _match_score(query, target)
            entry = dict(target)
            entry["score"] = raw_score
            scored.append(entry)

        ranked = sorted(scored, key=lambda t: float(t.get("score", 0.0)), reverse=True)
        ranked = [t for t in ranked if float(t.get("score", 0.0)) >= min_score]
        if not ranked:
            return SelectionResult(candidates=[], reason="no candidate met the selection threshold")
        return SelectionResult(selected=ranked[0], candidates=ranked[:top_k], reason="score_ranked")


def _match_score(query: str, target: Mapping[str, Any]) -> float:
    haystack = " ".join(
        [
            str(target.get("name", "")),
            str(target.get("description", "")),
            str(target.get("id", "")),
        ]
    ).lower()
    if not query:
        return 0.0
    return 1.0 if query in haystack else 0.0