"""
Tools :: Routing :: Context
===========================

Builds routing context: user request, planner state, memory references,
previous routes, active policies, session metadata and runtime
constraints. Context enables adaptive routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import iso_now
from ..utils.ids import new_id

__all__ = ["RoutingContext"]


@dataclass
class RoutingContext:
    """Snapshot of everything the router knows about a request."""

    request: str = ""
    planner_state: Dict[str, Any] = field(default_factory=dict)
    memory_references: List[str] = field(default_factory=list)
    previous_routes: List[str] = field(default_factory=list)
    policies: List[str] = field(default_factory=list)
    session_metadata: Dict[str, Any] = field(default_factory=dict)
    runtime_constraints: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=iso_now)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "planner_state": dict(self.planner_state),
            "memory_references": list(self.memory_references),
            "previous_routes": list(self.previous_routes),
            "policies": list(self.policies),
            "session_metadata": dict(self.session_metadata),
            "runtime_constraints": dict(self.runtime_constraints),
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
        }

    def merged(self, extra: Mapping[str, Any]) -> "RoutingContext":
        """Return a copy enriched with extra session/constraint data."""
        copy = RoutingContext(
            request=self.request,
            planner_state=dict(self.planner_state),
            memory_references=list(self.memory_references),
            previous_routes=list(self.previous_routes),
            policies=list(self.policies),
            session_metadata={**self.session_metadata, **extra.get("session_metadata", {})},
            runtime_constraints={**self.runtime_constraints, **extra.get("runtime_constraints", {})},
            correlation_id=self.correlation_id,
            created_at=self.created_at,
        )
        if extra.get("request"):
            copy.request = str(extra["request"])
        return copy