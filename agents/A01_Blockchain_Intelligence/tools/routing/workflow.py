"""
Tools :: Routing :: Workflow
============================

Routes complex workflows: sequential, parallel, DAG, conditional
branching and loop handling. Used for multi-step agent tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .planner import ExecutionStep, RoutingPlan

__all__ = ["WorkflowMode", "WorkflowResult", "WorkflowRouter"]

WorkflowMode = "sequential|parallel|dag|conditional|loop"


@dataclass
class WorkflowResult:
    """Outcome of a workflow execution decision."""

    ok: bool
    order: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "order": list(self.order),
            "skipped": list(self.skipped),
            "reason": self.reason,
        }


class WorkflowRouter:
    """Computes execution order for workflow steps."""

    def sequential(self, steps: Sequence[ExecutionStep]) -> WorkflowResult:
        order = [step.target_id for step in steps]
        return WorkflowResult(ok=True, order=order)

    def parallel(self, steps: Sequence[ExecutionStep]) -> WorkflowResult:
        return WorkflowResult(ok=True, order=[step.target_id for step in steps], reason="parallel")

    def dag(self, steps: Sequence[ExecutionStep]) -> WorkflowResult:
        """Topological order by step dependencies."""
        remaining = {step.target_id: step for step in steps}
        order: List[str] = []
        while remaining:
            ready = [sid for sid, step in remaining.items() if all(dep not in remaining for dep in step.dependencies)]
            if not ready:
                return WorkflowResult(ok=False, order=order, skipped=[sid for sid in remaining], reason="dependency cycle detected")
            for sid in sorted(ready):
                order.append(sid)
                del remaining[sid]
        return WorkflowResult(ok=True, order=order, reason="dag")

    def conditional(
        self,
        steps: Sequence[ExecutionStep],
        condition: Callable[[ExecutionStep, Mapping[str, Any]], bool],
        state: Mapping[str, Any],
    ) -> WorkflowResult:
        order: List[str] = []
        skipped: List[str] = []
        for step in steps:
            if condition(step, state):
                order.append(step.target_id)
            else:
                skipped.append(step.target_id)
        return WorkflowResult(ok=True, order=order, skipped=skipped, reason="conditional")

    def loop(self, steps: Sequence[ExecutionStep], max_iterations: int = 10) -> WorkflowResult:
        order: List[str] = []
        for _ in range(max_iterations):
            order.extend(step.target_id for step in steps)
        return WorkflowResult(ok=True, order=order, reason=f"loop:{max_iterations}")

    def route(self, plan: RoutingPlan, mode: str, **kwargs: Any) -> WorkflowResult:
        if mode == "sequential":
            return self.sequential(plan.steps)
        if mode == "parallel":
            return self.parallel(plan.steps)
        if mode == "dag":
            return self.dag(plan.steps)
        if mode == "conditional":
            return self.conditional(plan.steps, kwargs["condition"], kwargs.get("state", {}))
        if mode == "loop":
            return self.loop(plan.steps, kwargs.get("max_iterations", 10))
        return WorkflowResult(ok=False, reason=f"unsupported mode {mode!r}")