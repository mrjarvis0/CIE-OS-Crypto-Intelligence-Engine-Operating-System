"""
Tools :: Routing :: Planner
===========================

Transforms routing decisions into executable plans: ordered steps,
dependencies, parallel branches, retry paths and success criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import iso_now
from ..utils.ids import new_id

__all__ = ["ExecutionStep", "RoutingPlan", "Planner"]


@dataclass
class ExecutionStep:
    """One step of an executable routing plan."""

    target_id: str
    kind: str = "tool"
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    parallel: bool = False
    retries: int = 0
    success_criteria: str = "ok"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "kind": self.kind,
            "action": self.action,
            "params": dict(self.params),
            "dependencies": list(self.dependencies),
            "parallel": self.parallel,
            "retries": self.retries,
            "success_criteria": self.success_criteria,
        }


@dataclass
class RoutingPlan:
    """An executable plan produced by the planner."""

    plan_id: str = field(default_factory=new_id)
    steps: List[ExecutionStep] = field(default_factory=list)
    created_at: str = field(default_factory=iso_now)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "steps": [step.as_dict() for step in self.steps],
        }


class Planner:
    """Builds executable plans from selected routes."""

    def plan(
        self,
        route: Mapping[str, Any],
        *,
        parallel: bool = False,
        retries: int = 0,
    ) -> RoutingPlan:
        steps: List[ExecutionStep] = []
        selected = route.get("selected") or route.get("target")
        if isinstance(selected, dict):
            steps.append(
                ExecutionStep(
                    target_id=str(selected.get("id", selected.get("target_id", ""))),
                    kind=str(selected.get("kind", "tool")),
                    action=str(selected.get("action", "")),
                    params=dict(selected.get("params", {})),
                    parallel=parallel,
                    retries=retries,
                )
            )
        for extra in route.get("additional", []) or []:
            if isinstance(extra, dict):
                steps.append(
                    ExecutionStep(
                        target_id=str(extra.get("id", extra.get("target_id", ""))),
                        kind=str(extra.get("kind", "tool")),
                        action=str(extra.get("action", "")),
                        params=dict(extra.get("params", {})),
                        dependencies=[str(d) for d in extra.get("dependencies", [])],
                        parallel=bool(extra.get("parallel", parallel)),
                        retries=int(extra.get("retries", retries)),
                    )
                )
        return RoutingPlan(steps=steps)

    def to_route(self, plan: RoutingPlan) -> Dict[str, Any]:
        return plan.as_dict()