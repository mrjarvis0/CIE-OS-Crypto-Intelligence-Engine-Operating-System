"""
Tools :: Routing Layer
======================

The intelligent decision engine of the CIE-OS Tools Platform. The
routing layer decides which tool, agent, adapter, model, RPC or MCP
server executes, whether execution is sequential or parallel, and which
fallback path to use on failure. It never performs business logic.

Pipeline: intent extraction -> candidate discovery -> policy validation
-> scoring -> optimization -> route selection -> executable plan.

Modules: intent, strategy, selector, scorer, policy, context, planner,
workflow, balancing, optimization, fallback, cache, receipt, validator,
priority, router. :class:`Router` is the entry point.
"""

from __future__ import annotations

__all__ = [
    "Intent",
    "INTENT_TYPES",
    "IntentExtractor",
    "RoutingStrategy",
    "DirectStrategy",
    "CapabilityStrategy",
    "PriorityStrategy",
    "RuleBasedStrategy",
    "DynamicStrategy",
    "HybridStrategy",
    "MultiAgentStrategy",
    "STRATEGY_REGISTRY",
    "RouteCandidate",
    "ScoringWeights",
    "RouteScorer",
    "Selector",
    "SelectionResult",
    "RoutingPolicyRule",
    "RoutingPolicyEngine",
    "internal_tools_first_rule",
    "local_model_preferred_rule",
    "premium_model_critical_only_rule",
    "blockchain_write_requires_approval_rule",
    "privacy_stays_local_rule",
    "RoutingContext",
    "ExecutionStep",
    "RoutingPlan",
    "Planner",
    "WorkflowResult",
    "WorkflowRouter",
    "BalancerStats",
    "LoadBalancer",
    "OptimizationWeights",
    "OptimizationResult",
    "RouteOptimizer",
    "FallbackResult",
    "FallbackChain",
    "RouteCache",
    "CacheEntry",
    "RoutingReceipt",
    "ReceiptLog",
    "RouteValidation",
    "RouteValidator",
    "PRIORITY_LEVELS",
    "PriorityRouter",
    "priority_value",
    "RouteRequest",
    "Router",
]

from .intent import Intent, INTENT_TYPES, IntentExtractor  # noqa: E402
from .strategy import (  # noqa: E402
    RoutingStrategy,
    DirectStrategy,
    CapabilityStrategy,
    PriorityStrategy,
    RuleBasedStrategy,
    DynamicStrategy,
    HybridStrategy,
    MultiAgentStrategy,
    STRATEGY_REGISTRY,
)
from .scorer import RouteCandidate, ScoringWeights, RouteScorer  # noqa: E402
from .selector import Selector, SelectionResult  # noqa: E402
from .policy import (  # noqa: E402
    RoutingPolicyRule,
    RoutingPolicyEngine,
    internal_tools_first_rule,
    local_model_preferred_rule,
    premium_model_critical_only_rule,
    blockchain_write_requires_approval_rule,
    privacy_stays_local_rule,
)
from .context import RoutingContext  # noqa: E402
from .planner import ExecutionStep, RoutingPlan, Planner  # noqa: E402
from .workflow import WorkflowResult, WorkflowRouter  # noqa: E402
from .balancing import BalancerStats, LoadBalancer  # noqa: E402
from .optimizer import OptimizationWeights, OptimizationResult, RouteOptimizer  # noqa: E402
from .fallback import FallbackResult, FallbackChain  # noqa: E402
from .cache import RouteCache, CacheEntry  # noqa: E402
from .receipt import RoutingReceipt, ReceiptLog  # noqa: E402
from .validator import RouteValidation, RouteValidator  # noqa: E402
from .priority import PRIORITY_LEVELS, PriorityRouter, priority_value  # noqa: E402
from .router import RouteRequest, Router  # noqa: E402