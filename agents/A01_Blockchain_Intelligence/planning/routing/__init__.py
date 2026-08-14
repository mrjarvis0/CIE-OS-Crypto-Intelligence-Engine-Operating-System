"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.routing

Purpose:
    Routing of tasks to tools and agents, including strategies,
    policies, and selectors, for the planning subsystem.
"""

from __future__ import annotations

# ==============================================================================
# Strategy
# ==============================================================================

from .strategy import (
    RouteResult,
    RoutingStrategyImpl,
    Scorer,
    build_strategy,
    default_scorer,
    FirstMatchStrategy,
    BestScoreStrategy,
    RoundRobinStrategy,
    RandomStrategy,
    FallbackStrategy,
)

# ==============================================================================
# Policy
# ==============================================================================

from .policy import (
    PolicyCheck,
    PolicyDecision,
    RoutingPolicy,
)

# ==============================================================================
# Router
# ==============================================================================

from .router import (
    NoRouteFoundError,
    RoutingError,
    Router,
)

# ==============================================================================
# Tool Selector
# ==============================================================================

from .selector import (
    Agent,
    AgentSelector,
    Tool,
    ToolSelector,
)

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Strategy
    "RoutingStrategyImpl",
    "FirstMatchStrategy",
    "BestScoreStrategy",
    "RoundRobinStrategy",
    "RandomStrategy",
    "FallbackStrategy",
    "RouteResult",
    "Scorer",
    "default_scorer",
    "build_strategy",
    # Policy
    "PolicyCheck",
    "PolicyDecision",
    "RoutingPolicy",
    # Router
    "RoutingError",
    "NoRouteFoundError",
    "Router",
    # Tool & Agent Selector
    "Tool",
    "ToolSelector",
    "Agent",
    "AgentSelector",
]
