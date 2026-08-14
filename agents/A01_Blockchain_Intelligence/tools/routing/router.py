"""
Tools :: Routing :: Router
==========================

Central routing orchestrator: receives planner requests, extracts
intent, discovers candidates, validates policy, scores, optimizes,
validates the final route and produces executable plans with receipts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import elapsed_ms
from .cache import RouteCache
from .context import RoutingContext
from .intent import Intent, IntentExtractor
from .optimizer import OptimizationWeights, OptimizationResult, RouteOptimizer
from .planner import Planner, RoutingPlan
from .policy import RoutingPolicyEngine, RoutingPolicyRule
from .receipt import ReceiptLog, RoutingReceipt
from .scorer import RouteCandidate, RouteScorer
from .selector import Selector
from .validator import RouteValidation, RouteValidator
from .workflow import WorkflowRouter

__all__ = ["RouteRequest", "Router"]


@dataclass
class RouteRequest:
    """A request the router must turn into an executable plan."""

    request: str
    correlation_id: str = ""
    context: Optional[Mapping[str, Any]] = None
    candidates: List[Mapping[str, Any]] = field(default_factory=list)
    mode: str = "sequential"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "correlation_id": self.correlation_id,
            "mode": self.mode,
            "candidates": [dict(c) for c in self.candidates],
        }


class Router:
    """End-to-end routing pipeline."""

    def __init__(
        self,
        *,
        intent_extractor: Optional[IntentExtractor] = None,
        policy_engine: Optional[RoutingPolicyEngine] = None,
        scorer: Optional[RouteScorer] = None,
        optimizer: Optional[RouteOptimizer] = None,
        validator: Optional[RouteValidator] = None,
        planner: Optional[Planner] = None,
        workflow: Optional[WorkflowRouter] = None,
        cache: Optional[RouteCache] = None,
        receipts: Optional[ReceiptLog] = None,
    ) -> None:
        self.intents = intent_extractor if intent_extractor is not None else IntentExtractor()
        self.policies = policy_engine if policy_engine is not None else RoutingPolicyEngine()
        self.scorer = scorer if scorer is not None else RouteScorer()
        self.optimizer = optimizer if optimizer is not None else RouteOptimizer()
        self.validator = validator if validator is not None else RouteValidator()
        self.planner = planner if planner is not None else Planner()
        self.workflow = workflow if workflow is not None else WorkflowRouter()
        self.cache = cache if cache is not None else RouteCache()
        self.receipts = receipts if receipts is not None else ReceiptLog()

    def route(self, req: RouteRequest, *, use_cache: bool = True) -> Dict[str, Any]:
        """Run the full pipeline: intent -> candidates -> policy ->
        scoring -> optimization -> validation -> plan -> receipt."""
        started = time.perf_counter()
        cache_key = self.cache.key_for(req.request, req.mode, req.correlation_id)
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        intent = self.intents.classify(req.request)
        context = RoutingContext(request=req.request, session_metadata=dict(req.context or {}))
        if req.correlation_id:
            context.correlation_id = req.correlation_id

        policy_request = {"target_kind": intent.targets[0] if intent.targets else "tool", **dict(req.context or {})}
        policy_decisions = self.policies.evaluate(policy_request)

        if not self.policies.permitted(policy_request):
            result = self._build_result(
                req=req,
                intent=intent,
                context=context,
                selected=None,
                candidates=[],
                policy_decisions=policy_decisions,
                plan=RoutingPlan(),
                score=0.0,
                status="denied",
                started=started,
            )
            if use_cache:
                self.cache.set(cache_key, result)
            return result

        scored = self.scorer.rank(req.candidates or [])
        optimized = self.optimizer.optimize(scored)
        best = optimized.best

        selected = best.as_dict() if best else None
        validation = self.validator.validate(
            {"selected": selected, "policy_outcome": "allow"},
            security_ok=True,
        )
        status = "validated" if validation.valid else "invalid"
        if selected is not None and not validation.valid:
            selected = None

        plan = self.planner.plan({"selected": selected or {}, "additional": []}, parallel=req.mode == "parallel")
        if plan.steps:
            self.workflow.route(plan, req.mode)

        result = self._build_result(
            req=req,
            intent=intent,
            context=context,
            selected=selected,
            candidates=[c.as_dict() for c in optimized.ranked],
            policy_decisions=policy_decisions,
            plan=plan,
            score=best.score if best else 0.0,
            status=status,
            started=started,
        )
        if use_cache:
            self.cache.set(cache_key, result)
        return result

    def _build_result(
        self,
        *,
        req: RouteRequest,
        intent: Intent,
        context: RoutingContext,
        selected: Optional[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        policy_decisions: Sequence[RoutingPolicyRule],
        plan: RoutingPlan,
        score: float,
        status: str,
        started: float,
    ) -> Dict[str, Any]:
        latency = round(elapsed_ms(started), 3)
        rejected = [c for c in candidates if not selected or c.get("target_id") != selected.get("target_id")]
        receipt = RoutingReceipt(
            request_id=req.correlation_id or context.correlation_id,
            selected_target=(selected or {}).get("target_id", ""),
            rejected_candidates=rejected,
            policy_decisions=[rule.as_dict() for rule in policy_decisions],
            scores={c["target_id"]: c["score"] for c in candidates},
            context_summary={"request": req.request, "intent": intent.primary, "mode": req.mode},
            decision_score=score,
            latency_ms=latency,
            execution_status=status,
        )
        self.receipts.record(receipt)
        return {
            "ok": selected is not None and status in ("validated", "planned"),
            "intent": intent.as_dict(),
            "selected": selected,
            "candidates": candidates,
            "policy_decisions": [rule.as_dict() for rule in policy_decisions],
            "plan": plan.as_dict(),
            "receipt": receipt.as_dict(),
            "latency_ms": latency,
            "status": status,
        }