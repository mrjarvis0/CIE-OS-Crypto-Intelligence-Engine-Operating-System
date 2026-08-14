"""
Tools :: Routing :: Priority
============================

Priority-aware routing: assigns and compares priority levels, orders
candidates by priority before scoring and serves as the priority signal
for the scorer and strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["PRIORITY_LEVELS", "PriorityRouter", "priority_value"]

PRIORITY_LEVELS = ["critical", "high", "normal", "low", "background"]
_PRIORITY_VALUES = {"critical": 4, "high": 3, "normal": 2, "low": 1, "background": 0}


def priority_value(level: str) -> int:
    return _PRIORITY_VALUES.get(level, 2)


class PriorityRouter:
    """Orders candidates by priority level, then by score."""

    def prioritize(
        self,
        candidates: Sequence[Mapping[str, Any]],
        *,
        default: str = "normal",
    ) -> List[Dict[str, Any]]:
        scored: List[Dict[str, Any]] = []
        for candidate in candidates:
            entry = dict(candidate)
            level = str(entry.get("priority", default))
            entry["priority_value"] = priority_value(level)
            entry["priority"] = level
            scored.append(entry)
        return sorted(
            scored,
            key=lambda c: (c["priority_value"], float(c.get("score", 0.0))),
            reverse=True,
        )

    def gate(self, candidates: Sequence[Mapping[str, Any]], minimum: str = "normal") -> List[Dict[str, Any]]:
        """Keep only candidates at or above the minimum priority."""
        minimum_value = priority_value(minimum)
        return [dict(c) for c in candidates if priority_value(str(c.get("priority", "normal"))) >= minimum_value]